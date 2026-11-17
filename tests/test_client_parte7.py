"""Testes da Parte 7 do peer/client.py (fim confiavel e run() completo).
Rodar da raiz do projeto:

    python3 -m unittest tests.test_client_parte7 -v

Blocos:
  1. confirmar_fim: INPUT com o ack final por um tempo.
  2. run() contra um host falso roteirizado (tela falsa, sem curses).
  3. ponta a ponta: Host REAL + Client.run(); o host tem que encerrar logo
     (porque o cliente confirmou o fim), e nao so no timeout.
"""

import socket
import threading
import time
import unittest

from common import protocol as proto
import peer.client as client_mod
from peer.client import Client

try:
    import peer.ui  # noqa: F401
    TEM_UI = True
except ImportError:
    TEM_UI = False

try:
    from peer.host import Host
    from common.game_logic import step  # noqa: F401
    TEM_HOST = True
except ImportError:
    TEM_HOST = False

STATE = {"width": 40, "height": 20, "tick_ms": 100, "players": [
    {"pid": 0, "x": 5, "y": 5, "dir": "R"},
    {"pid": 1, "x": 34, "y": 14, "dir": "L"},
    {"pid": 2, "x": 20, "y": 1, "dir": "D"},
]}
WELCOME = proto.welcome("m7", STATE, 3000)
CFG = {"peer": {"bind_host": "127.0.0.1"},
       "timeouts": {"hello_retry_ms": 50, "hello_deadline_ms": 500, "host_timeout_ms": 300}}
FIM_WIN = {"result": "WIN", "winner": 0}


def rec(n, end=None, el=None):
    return {"n": n, "mv": [[0, 5 + n, 5]], "el": el or [], "end": end}


def porta_livre():
    tmp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tmp.bind(("127.0.0.1", 0))
    porta = tmp.getsockname()[1]
    tmp.close()
    return porta


class TelaFalsa:
    def __init__(self, teclas=()):
        self.teclas = list(teclas)
        self.status = []
        self.entrou = False
        self.saiu = False
        self.wait_key_chamado = False

    def __enter__(self):
        self.entrou = True
        return self

    def __exit__(self, *exc):
        self.saiu = True
        return False

    def poll_input(self):
        return self.teclas.pop(0) if self.teclas else None

    def draw(self, view):
        self.status.append(view.status)

    def wait_key(self):
        self.wait_key_chamado = True


def montar_ms(host_port, peer_port=None):
    return {"v": 1, "t": "MATCH_START", "match_id": "m7", "host_slot": 0,
            "config": {"width": 40, "height": 20, "tick_ms": 100},
            "players": [
                {"slot": 0, "name": "Alice", "host": "127.0.0.1", "port": host_port},
                {"slot": 1, "name": "Bob", "host": "127.0.0.1",
                 "port": peer_port or porta_livre()},
                {"slot": 2, "name": "Carol", "host": "127.0.0.1", "port": 6003}]}


# ---------------------------------------------------------------------------
# 1. confirmar_fim
# ---------------------------------------------------------------------------

@unittest.skipUnless(TEM_UI, "peer.ui (curses) indisponivel neste ambiente")
class TestConfirmarFim(unittest.TestCase):
    def setUp(self):
        self.host = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.host.bind(("127.0.0.1", 0))
        self.host.settimeout(0.3)
        self.tela = TelaFalsa()
        self.cli = Client(CFG, montar_ms(self.host.getsockname()[1]), 1, ui=self.tela)
        self.cli.abrir()
        self.cli_addr = self.cli.sock.getsockname()
        self.cli._guardar_welcome(WELCOME)
        self.cli.montar_view()
        self.cli.ack = 3                                      # ultimo ciclo aplicado
        self.cli.iseq = 5                                     # ja enviou 5 INPUT antes

    def tearDown(self):
        self.cli.fechar()
        self.host.close()

    def inputs(self):
        saida = []
        while True:
            try:
                dados, _ = self.host.recvfrom(2048)
            except socket.timeout:
                return saida
            msg = proto.decode(dados)
            if msg and msg["t"] == "INPUT":
                saida.append(msg)

    def test_manda_varios_input_com_o_ack_final(self):
        t0 = time.monotonic()
        self.cli.confirmar_fim(0.45)
        dur = time.monotonic() - t0
        msgs = self.inputs()
        self.assertGreaterEqual(len(msgs), 4)                 # ~1 a cada 100 ms
        self.assertTrue(all(m["ack"] == 3 for m in msgs))
        self.assertGreaterEqual(dur, 0.44)
        self.assertLess(dur, 0.7)

    def test_iseq_continua_de_onde_estava(self):
        self.cli.confirmar_fim(0.25)
        iseqs = [m["iseq"] for m in self.inputs()]
        self.assertEqual(iseqs, list(range(6, 6 + len(iseqs))))   # 6, 7, 8...

    def test_primeiro_input_sai_na_hora(self):
        self.cli._prox_input = time.monotonic() + 10          # como se so fosse a hora daqui a 10 s
        self.cli.confirmar_fim(0.05)
        self.assertGreaterEqual(len(self.inputs()), 1)

    def test_ignora_o_que_o_host_reenviar(self):
        self.cli.view.result = FIM_WIN
        for msg in (proto.tick("m7", [rec(3)]), proto.tick("m7", []), WELCOME,
                    proto.abort("m7", "qualquer")):
            self.host.sendto(proto.encode(msg), self.cli_addr)
        self.cli.confirmar_fim(0.2)                           # nao levanta nada, nao trava
        self.assertEqual(self.cli.ack, 3)

    def test_duracao_padrao_e_de_2_segundos(self):
        self.assertEqual(self.cli.fim_duracao_s, 2.0)

    def test_usa_fim_duracao_s_do_objeto_quando_nao_ha_argumento(self):
        self.cli.fim_duracao_s = 0.15
        t0 = time.monotonic()
        self.cli.confirmar_fim()
        self.assertLess(time.monotonic() - t0, 0.4)

    def test_mantem_a_tela_desenhada(self):
        self.cli.confirmar_fim(0.2)
        self.assertGreaterEqual(len(self.tela.status), 2)


# ---------------------------------------------------------------------------
# 2. run() contra um host falso
# ---------------------------------------------------------------------------

class HostFalso(threading.Thread):
    """Espera o HELLO, responde WELCOME e executa um roteiro de mensagens."""

    def __init__(self, sock, roteiro=None, responder_welcome=True):
        super().__init__(daemon=True)
        self.sock = sock
        self.roteiro = roteiro
        self.responder_welcome = responder_welcome
        self.inputs = []
        self.origem = None
        self.parar = threading.Event()

    def enviar(self, msg):
        self.sock.sendto(proto.encode(msg), self.origem)

    def _ler(self, timeout):
        self.sock.settimeout(timeout)
        try:
            dados, origem = self.sock.recvfrom(2048)
        except (socket.timeout, OSError):
            return None
        return proto.decode(dados), origem

    def run(self):
        while not self.parar.is_set():
            r = self._ler(0.05)
            if r and r[0] and r[0]["t"] == "HELLO":
                self.origem = r[1]
                if self.responder_welcome:
                    self.enviar(WELCOME)
                    break
                # sem welcome: continua ignorando os HELLO
        if self.origem and self.roteiro:
            self.roteiro(self)
        while not self.parar.is_set():                         # so coleta INPUT
            r = self._ler(0.05)
            if r and r[0] and r[0]["t"] == "INPUT":
                self.inputs.append(r[0])


@unittest.skipUnless(TEM_UI, "peer.ui (curses) indisponivel neste ambiente")
class TestRun(unittest.TestCase):
    def setUp(self):
        self.host_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.host_sock.bind(("127.0.0.1", 0))
        self.ms = montar_ms(self.host_sock.getsockname()[1])
        self.tela = TelaFalsa()
        self.cli = Client(CFG, self.ms, 1, ui=self.tela)
        self.cli.fim_duracao_s = 0.35                          # testes rapidos
        self.host = None

    def tearDown(self):
        if self.host:
            self.host.parar.set()
            self.host.join(1)
        self.cli.fechar()
        self.host_sock.close()

    def iniciar(self, roteiro=None, **kw):
        self.host = HostFalso(self.host_sock, roteiro, **kw)
        self.host.start()

    # ---- partidas que terminam ----

    @staticmethod
    def roteiro_vitoria(h):
        time.sleep(0.1)
        h.enviar(proto.tick("m7", []))
        time.sleep(0.1)
        h.enviar(proto.tick("m7", [rec(1)]))
        time.sleep(0.15)
        h.enviar(proto.tick("m7", [rec(1), rec(2, end=FIM_WIN, el=[[1, "WALL"]])]))

    def test_partida_completa_vitoria(self):
        self.iniciar(self.roteiro_vitoria)
        r = self.cli.run()
        self.assertEqual(r, {"result": "WIN", "winner": 0})
        self.assertEqual(self.cli.ack, 2)

    def test_empate(self):
        def roteiro(h):
            time.sleep(0.1)
            h.enviar(proto.tick("m7", [rec(1, end={"result": "DRAW"})]))
        self.iniciar(roteiro)
        self.assertEqual(self.cli.run(), {"result": "DRAW", "winner": None})

    def test_depois_do_fim_o_host_recebe_o_ack_final(self):
        self.iniciar(self.roteiro_vitoria)
        self.cli.run()
        time.sleep(0.1)
        self.host.parar.set()
        self.host.join(1)
        acks = [m["ack"] for m in self.host.inputs]
        self.assertGreaterEqual(len([a for a in acks if a == 2]), 2, acks)   # ack final, mais de uma vez
        self.assertEqual(acks, sorted(acks))
        self.assertEqual([m["iseq"] for m in self.host.inputs],
                         list(range(1, len(acks) + 1)))        # iseq sem falhas nem repeticao

    def test_fecha_o_socket_no_fim(self):
        self.iniciar(self.roteiro_vitoria)
        self.cli.run()
        self.assertIsNone(self.cli.sock)

    def test_welcome_repetido_no_meio_do_jogo_e_ignorado(self):
        def roteiro(h):
            time.sleep(0.1)
            h.enviar(WELCOME)
            h.enviar(proto.tick("m7", [rec(1)]))
            h.enviar(WELCOME)
            time.sleep(0.1)
            h.enviar(proto.tick("m7", [rec(2, end=FIM_WIN)]))
        self.iniciar(roteiro)
        self.assertEqual(self.cli.run()["result"], "WIN")

    # ---- falhas ----

    def test_host_nunca_responde_vira_abort_sem_abrir_a_tela(self):
        propria = TelaFalsa()
        original = client_mod._criar_tela
        client_mod._criar_tela = lambda: propria
        try:
            cli = Client(CFG, self.ms, 1)                      # sem ui do main
            self.iniciar(responder_welcome=False)
            r = cli.run()
        finally:
            client_mod._criar_tela = original
        self.assertEqual(r["result"], "ABORT")
        self.assertIn("HELLO", r["reason"])
        self.assertFalse(propria.entrou)                       # nem chegou a abrir a tela
        self.assertIsNone(cli.sock)

    def test_abort_do_host_no_meio(self):
        def roteiro(h):
            time.sleep(0.1)
            h.enviar(proto.tick("m7", [rec(1)]))
            time.sleep(0.1)
            h.enviar(proto.abort("m7", "host saiu"))
        self.iniciar(roteiro)
        r = self.cli.run()
        self.assertEqual(r, {"result": "ABORT", "winner": None, "reason": "host saiu"})
        self.assertTrue(any("host saiu" in (s or "") for s in self.tela.status))

    def test_abort_antes_de_comecar(self):
        def roteiro(h):
            h.enviar(proto.abort("m7", "jogadores insuficientes"))
        self.iniciar(roteiro)
        r = self.cli.run()
        self.assertEqual(r["result"], "ABORT")
        self.assertEqual(r["reason"], "jogadores insuficientes")

    def test_host_some_no_meio_da_partida(self):
        def roteiro(h):
            time.sleep(0.1)
            h.enviar(proto.tick("m7", [rec(1)]))               # e depois silencio
        self.iniciar(roteiro)
        r = self.cli.run()
        self.assertEqual(r, {"result": "HOST_LOST", "winner": None})
        self.assertTrue(any("host" in (s or "") for s in self.tela.status))

    def test_host_some_antes_do_inicio(self):
        self.iniciar(lambda h: None)                           # welcome e silencio
        self.assertEqual(self.cli.run()["result"], "HOST_LOST")

    def test_q_sai_e_nao_espera_tecla(self):
        propria = TelaFalsa(teclas=["QUIT"])
        original = client_mod._criar_tela
        client_mod._criar_tela = lambda: propria
        try:
            cli = Client(CFG, self.ms, 1)
            self.iniciar()
            r = cli.run()
        finally:
            client_mod._criar_tela = original
        self.assertEqual(r, {"result": "QUIT", "winner": None})
        self.assertFalse(propria.wait_key_chamado)
        self.assertTrue(propria.saiu)

    def test_porta_ocupada_devolve_abort_em_vez_de_quebrar(self):
        ocupada = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ocupada.bind(("127.0.0.1", 0))
        try:
            ms = montar_ms(self.host_sock.getsockname()[1], ocupada.getsockname()[1])
            r = Client(CFG, ms, 1, ui=self.tela).run()
        finally:
            ocupada.close()
        self.assertEqual(r["result"], "ABORT")
        self.assertIn("porta UDP", r["reason"])

    def test_ctrl_c_devolve_abort_e_limpa(self):
        self.iniciar()
        self.cli.aguardar_inicio = lambda: (_ for _ in ()).throw(KeyboardInterrupt())
        r = self.cli.run()
        self.assertEqual(r["result"], "ABORT")
        self.assertIsNone(self.cli.sock)

    # ---- tela propria x tela do main ----

    def test_ui_do_main_nao_e_aberta_nem_fechada_nem_espera_tecla(self):
        self.iniciar(self.roteiro_vitoria)
        self.cli.run()
        self.assertFalse(self.tela.entrou)
        self.assertFalse(self.tela.saiu)
        self.assertFalse(self.tela.wait_key_chamado)           # quem espera tecla e o main

    def test_tela_propria_abre_espera_tecla_e_fecha(self):
        propria = TelaFalsa()
        original = client_mod._criar_tela
        client_mod._criar_tela = lambda: propria
        try:
            cli = Client(CFG, self.ms, 1)
            cli.fim_duracao_s = 0.3
            self.iniciar(self.roteiro_vitoria)
            r = cli.run()
        finally:
            client_mod._criar_tela = original
        self.assertEqual(r["result"], "WIN")
        self.assertTrue(propria.entrou)
        self.assertTrue(propria.wait_key_chamado)
        self.assertTrue(propria.saiu)
        self.assertIsNone(cli.ui)

    def test_tela_propria_fecha_mesmo_com_erro_inesperado(self):
        propria = TelaFalsa()
        original = client_mod._criar_tela
        client_mod._criar_tela = lambda: propria
        try:
            cli = Client(CFG, self.ms, 1)
            cli.aguardar_inicio = lambda: (_ for _ in ()).throw(ValueError("bug"))
            self.iniciar()
            with self.assertRaises(ValueError):
                cli.run()
        finally:
            client_mod._criar_tela = original
        self.assertTrue(propria.saiu)                          # o terminal e restaurado
        self.assertIsNone(cli.sock)


# ---------------------------------------------------------------------------
# 3. ponta a ponta com o Host REAL
# ---------------------------------------------------------------------------

@unittest.skipUnless(TEM_HOST and TEM_UI, "peer.host/ui/game_logic indisponiveis")
class TestPontaAPontaComHostReal(unittest.TestCase):
    """Host real + Client.run(). Se o cliente confirma o fim, o host sai do
    estado ENDING na hora; se nao, ficaria esperando os 5 s do peer_timeout."""

    def test_host_encerra_logo_porque_o_cliente_confirmou(self):
        porta_host, porta_peer = porta_livre(), porta_livre()
        ms = {"v": 1, "t": "MATCH_START", "match_id": "m7", "host_slot": 0,
              "config": {"width": 40, "height": 20, "tick_ms": 20},
              "players": [
                  {"slot": 0, "name": "Alice", "host": "127.0.0.1", "port": porta_host},
                  {"slot": 1, "name": "Bob", "host": "127.0.0.1", "port": porta_peer}]}
        cfg = {"peer": {"bind_host": "127.0.0.1"},
               "timeouts": {"hello_retry_ms": 100, "hello_deadline_ms": 5000,
                            "host_timeout_ms": 3000, "peer_timeout_ms": 5000}}
        host = Host(cfg, ms)
        resultado_host = {}
        erro = []

        def rodar_host():
            try:
                resultado_host.update(host.run())
            except Exception as e:                             # noqa: BLE001
                erro.append(e)
        t = threading.Thread(target=rodar_host, daemon=True)
        t.start()

        cli = Client(cfg, ms, 1, ui=TelaFalsa())
        cli.fim_duracao_s = 0.5
        r = cli.run()
        t_cliente = time.monotonic()
        t.join(4)                                              # bem menos que os 5 s do timeout
        espera = time.monotonic() - t_cliente

        self.assertEqual(erro, [])
        self.assertFalse(t.is_alive(), "o host ainda esperava a confirmacao do cliente")
        self.assertLess(espera, 3.0)
        self.assertEqual(r["result"], resultado_host["result"])
        self.assertEqual(r.get("winner"), resultado_host.get("winner"))
        self.assertEqual(host.jog[1]["ack"], len(host.historico))   # o host viu o ack final
        self.assertEqual(host.estado, "FINISHED")


if __name__ == "__main__":
    unittest.main()
