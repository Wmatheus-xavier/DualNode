"""Testes da Parte 5 do peer/client.py (INPUT a cada ciclo).
Rodar da raiz do projeto:

    python3 -m unittest tests.test_client_parte5 -v

Usa uma tela FALSA (sem curses) e um host falso em 127.0.0.1. A ultima classe
alimenta o Host REAL (peer/host.py) com os INPUT do cliente.
"""

import socket
import threading
import time
import unittest

from common import protocol as proto
from peer.client import Client, proximo_instante

try:
    import peer.ui  # noqa: F401  (o aguardar_inicio usa o GameView)
    TEM_UI = True
except ImportError:
    TEM_UI = False

STATE = {"width": 40, "height": 20, "tick_ms": 100, "players": [
    {"pid": 0, "x": 5, "y": 5, "dir": "R"},
    {"pid": 1, "x": 34, "y": 14, "dir": "L"},
    {"pid": 2, "x": 20, "y": 1, "dir": "D"},
]}
WELCOME = proto.welcome("m7", STATE, 3000)
CFG = {"peer": {"bind_host": "127.0.0.1"},
       "timeouts": {"hello_retry_ms": 50, "hello_deadline_ms": 500, "host_timeout_ms": 2000}}


def porta_livre():
    tmp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tmp.bind(("127.0.0.1", 0))
    porta = tmp.getsockname()[1]
    tmp.close()
    return porta


class TelaFalsa:
    def __init__(self, teclas=()):
        self.teclas = list(teclas)

    def poll_input(self):
        return self.teclas.pop(0) if self.teclas else None

    def draw(self, view):
        pass

    def wait_key(self):
        pass


class Base(unittest.TestCase):
    def setUp(self):
        self.host = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.host.bind(("127.0.0.1", 0))
        self.host.settimeout(0.3)
        host_port = self.host.getsockname()[1]
        ms = {"v": 1, "t": "MATCH_START", "match_id": "m7", "host_slot": 0,
              "config": {"width": 40, "height": 20, "tick_ms": 100},
              "players": [
                  {"slot": 0, "name": "Alice", "host": "127.0.0.1", "port": host_port},
                  {"slot": 1, "name": "Bob", "host": "127.0.0.1", "port": porta_livre()},
                  {"slot": 2, "name": "Carol", "host": "127.0.0.1", "port": 6003},
              ]}
        self.tela = TelaFalsa()
        self.cli = Client(CFG, ms, 1, ui=self.tela)
        self.cli.abrir()
        self.cli_addr = self.cli.sock.getsockname()
        self.cli._guardar_welcome(WELCOME)

    def tearDown(self):
        self.cli.fechar()
        self.host.close()

    def inputs_recebidos(self):
        """Tudo que o host falso recebeu ate ficar 0,3 s em silencio."""
        saida = []
        while True:
            try:
                dados, origem = self.host.recvfrom(2048)
            except socket.timeout:
                return saida
            msg = proto.decode(dados)
            if msg is not None and msg["t"] == "INPUT":
                saida.append((msg, origem))


class TestEnviarInput(Base):
    def test_primeiro_input_tem_iseq_1(self):
        self.assertTrue(self.cli.enviar_input())
        msg, origem = self.inputs_recebidos()[0]
        self.assertEqual(msg["iseq"], 1)                 # o host so aceita iseq > 0
        self.assertEqual((msg["t"], msg["m"], msg["pid"], msg["v"]), ("INPUT", "m7", 1, 1))
        self.assertEqual(origem, self.cli_addr)          # mesma porta registrada

    def test_direcao_inicial_vem_do_welcome(self):
        self.cli.enviar_input()
        self.assertEqual(self.inputs_recebidos()[0][0]["dir"], "L")   # pid 1 comeca para a esquerda

    def test_iseq_cresce_sem_repetir(self):
        for _ in range(4):
            self.cli.enviar_input()
        self.assertEqual([m["iseq"] for m, _ in self.inputs_recebidos()], [1, 2, 3, 4])

    def test_envia_a_direcao_e_o_ack_atuais(self):
        self.cli.dir_desejada = "U"
        self.cli.ack = 7
        self.cli.enviar_input()
        msg = self.inputs_recebidos()[0][0]
        self.assertEqual((msg["dir"], msg["ack"]), ("U", 7))

    def test_ack_comeca_em_zero(self):
        self.cli.enviar_input()
        self.assertEqual(self.inputs_recebidos()[0][0]["ack"], 0)

    def test_sem_direcao_nao_envia_nem_gasta_iseq(self):
        self.cli.dir_desejada = None
        self.assertFalse(self.cli.enviar_input())
        self.assertEqual(self.cli.iseq, 0)
        self.assertEqual(self.inputs_recebidos(), [])

    def test_repete_a_direcao_mesmo_sem_tecla_nova(self):
        self.cli.enviar_input()
        self.cli.enviar_input()
        direcoes = [m["dir"] for m, _ in self.inputs_recebidos()]
        self.assertEqual(direcoes, ["L", "L"])           # INPUT e estado, nao evento

    def test_envio_que_falha_nao_derruba(self):
        self.cli.fechar()
        self.assertFalse(self.cli.enviar_input())


class TestTeclado(Base):
    def test_direcao_atualiza_dir_desejada(self):
        self.tela.teclas = ["U"]
        self.assertIsNone(self.cli.ler_teclado())
        self.assertEqual(self.cli.dir_desejada, "U")

    def test_sem_tecla_mantem(self):
        self.assertIsNone(self.cli.ler_teclado())
        self.assertEqual(self.cli.dir_desejada, "L")

    def test_quit(self):
        self.tela.teclas = ["QUIT"]
        self.assertEqual(self.cli.ler_teclado(), "QUIT")
        self.assertEqual(self.cli.dir_desejada, "L")

    def test_direcao_oposta_tambem_e_guardada_o_host_ignora(self):
        self.tela.teclas = ["R"]                          # moto indo para L
        self.cli.ler_teclado()
        self.assertEqual(self.cli.dir_desejada, "R")


class TestRitmo(Base):
    """Relogio falso: nada de dormir de verdade."""

    def test_proximo_instante_soma_o_tick_ao_previsto(self):
        self.assertAlmostEqual(proximo_instante(10.0, 10.03, 0.1), 10.1)

    def test_atraso_grande_reajusta_o_relogio(self):
        # previsto 10.0, agora 12.0: mais de 5 ciclos de atraso
        self.assertAlmostEqual(proximo_instante(10.0, 12.0, 0.1), 12.1)

    def test_atraso_pequeno_nao_reajusta(self):
        self.assertAlmostEqual(proximo_instante(10.0, 10.3, 0.1), 10.1)

    def test_primeiro_sai_na_hora_e_depois_um_por_tick(self):
        envios = [self.cli.enviar_input_se_for_hora(t) for t in (0.0, 0.05, 0.1, 0.19, 0.21)]
        self.assertEqual(envios, [True, False, True, False, True])
        self.assertEqual(self.cli.iseq, 3)

    def test_atraso_longo_nao_gera_rajada(self):
        self.cli.enviar_input_se_for_hora(0.0)
        self.assertTrue(self.cli.enviar_input_se_for_hora(5.0))    # volta de uma pausa longa
        self.assertFalse(self.cli.enviar_input_se_for_hora(5.01))  # e nao recupera os perdidos
        self.assertEqual(self.cli.iseq, 2)

    def test_usa_o_tick_ms_do_welcome(self):
        self.cli.tick_ms = 50
        envios = [self.cli.enviar_input_se_for_hora(t) for t in (0.0, 0.04, 0.05, 0.1)]
        self.assertEqual(envios, [True, False, True, True])


@unittest.skipUnless(TEM_UI, "peer.ui (curses) indisponivel neste ambiente")
class TestNaEspera(Base):
    """O INPUT ja sai durante aguardar_inicio (sinal de vida desde o WELCOME)."""

    def test_envia_input_a_cada_tick_enquanto_espera(self):
        def host_inicia():
            time.sleep(0.45)
            self.host.sendto(proto.encode(proto.tick("m7", [
                {"n": 1, "mv": [[0, 6, 5]], "el": [], "end": None}])), self.cli_addr)
        t = threading.Thread(target=host_inicia, daemon=True)
        t.start()
        r = self.cli.aguardar_inicio()
        t.join()
        self.assertTrue(r["ok"])
        iseqs = [m["iseq"] for m, _ in self.inputs_recebidos()]
        self.assertGreaterEqual(len(iseqs), 4)               # ~1 a cada 100 ms em 450 ms
        self.assertEqual(iseqs, list(range(1, len(iseqs) + 1)))

    def test_tecla_apertada_na_espera_vai_no_primeiro_input(self):
        self.tela.teclas = ["U"]
        self.host.sendto(proto.encode(proto.tick("m7", [
            {"n": 1, "mv": [[0, 6, 5]], "el": [], "end": None}])), self.cli_addr)
        self.cli.aguardar_inicio()
        msg = self.inputs_recebidos()[0][0]
        self.assertEqual((msg["iseq"], msg["dir"]), (1, "U"))


# ---------------------------------------------------------------------------
# Compatibilidade com o Host REAL
# ---------------------------------------------------------------------------

try:
    from peer.host import Host
    TEM_HOST = True
except ImportError:
    TEM_HOST = False


@unittest.skipUnless(TEM_HOST and TEM_UI, "peer.host/peer.ui indisponiveis neste ambiente")
class TestCompatibilidadeComHostReal(unittest.TestCase):
    """Os INPUT do cliente precisam passar no porteiro do Host de verdade."""

    IP_PEER = "192.168.0.22"

    def setUp(self):
        self.ms = {"v": 1, "t": "MATCH_START", "match_id": "m7", "host_slot": 0,
                   "config": {"width": 40, "height": 20, "tick_ms": 100},
                   "players": [
                       {"slot": 0, "name": "Alice", "host": "192.168.0.21", "port": 6001},
                       {"slot": 1, "name": "Bob", "host": self.IP_PEER, "port": 6002},
                       {"slot": 2, "name": "Carol", "host": "192.168.0.23", "port": 6003}]}
        self.host = Host({"timeouts": {}}, self.ms)
        self.host.estado = "RUNNING"
        self.host.jog[1]["presente"] = True                  # ja mandou HELLO
        self.cli = Client({}, self.ms, 1)
        self.cli._guardar_welcome(WELCOME)
        self.enviados = []
        self.cli.enviar = lambda msg: self.enviados.append(proto.encode(msg)) or True

    def entregar(self, dados):
        """O Host real recebe o datagrama como se viesse do endereco do peer 1."""
        self.host._tratar_datagrama(dados, (self.IP_PEER, 6002))

    def test_input_do_cliente_e_aceito_pelo_host(self):
        self.cli.dir_desejada = "U"
        self.cli.enviar_input()
        self.entregar(self.enviados[0])
        j = self.host.jog[1]
        self.assertEqual((j["iseq"], j["dir"]), (1, "U"))

    def test_iseq_crescente_e_aceito_e_repetido_e_descartado(self):
        for _ in range(3):
            self.cli.enviar_input()
        for dados in self.enviados:
            self.entregar(dados)
        self.assertEqual(self.host.jog[1]["iseq"], 3)
        self.entregar(self.enviados[0])                      # iseq 1 de novo: atrasado
        self.assertEqual(self.host.jog[1]["iseq"], 3)

    def test_ack_do_cliente_e_respeitado_ate_o_historico_do_host(self):
        self.host.historico = [{"n": 1}, {"n": 2}, {"n": 3}]
        self.cli.ack = 2
        self.cli.enviar_input()
        self.entregar(self.enviados[0])
        self.assertEqual(self.host.jog[1]["ack"], 2)

    def test_host_aceita_input_ja_durante_a_espera(self):
        """O sinal de vida desde o WELCOME nao e descartado (COLLECTING e COUNTDOWN)."""
        for estado in ("COLLECTING", "COUNTDOWN"):
            self.host.estado = estado
            self.host.jog[1]["iseq"] = 0
            self.cli.iseq = 0
            self.enviados.clear()
            self.cli.enviar_input()
            self.entregar(self.enviados[0])
            self.assertEqual(self.host.jog[1]["iseq"], 1, estado)

    def test_input_antes_do_hello_e_ignorado_pelo_host(self):
        self.host.jog[1]["presente"] = False
        self.cli.enviar_input()
        self.entregar(self.enviados[0])
        self.assertEqual(self.host.jog[1]["iseq"], 0)


if __name__ == "__main__":
    unittest.main()
