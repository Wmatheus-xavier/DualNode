"""Testes da Parte 3 do peer/client.py (handshake com reenvio do HELLO).
Rodar da raiz do projeto:

    python3 -m unittest tests.test_client_parte3 -v

Um "host falso" (thread com socket UDP em 127.0.0.1) responde, ignora ou
atrapalha os HELLO, e o Client tem que se comportar como manda o README.
"""

import socket
import threading
import time
import unittest

from common import protocol as proto
from peer.client import Client

STATE = {"width": 40, "height": 20, "tick_ms": 100, "players": [
    {"pid": 0, "x": 5, "y": 5, "dir": "R"},
    {"pid": 1, "x": 34, "y": 14, "dir": "L"},
    {"pid": 2, "x": 20, "y": 1, "dir": "D"},
]}
WELCOME = proto.welcome("m7", STATE, 3000)

# prazos curtos para os testes rodarem rapido
CFG = {"peer": {"bind_host": "127.0.0.1"},
       "timeouts": {"hello_retry_ms": 50, "hello_deadline_ms": 600}}


def porta_livre():
    tmp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tmp.bind(("127.0.0.1", 0))
    porta = tmp.getsockname()[1]
    tmp.close()
    return porta


class HostFalso(threading.Thread):
    """Recebe HELLO e, a cada um, chama reagir(numero_do_hello) -> lista de
    mensagens a devolver ao remetente."""

    def __init__(self, sock, reagir):
        super().__init__(daemon=True)
        self.sock = sock
        self.reagir = reagir
        self.hellos = []           # (mensagem, origem)
        self.parar = threading.Event()

    def run(self):
        self.sock.settimeout(0.02)
        while not self.parar.is_set():
            try:
                dados, origem = self.sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                return
            msg = proto.decode(dados)
            if msg is None or msg["t"] != "HELLO":
                continue
            self.hellos.append((msg, origem))
            for resposta in self.reagir(len(self.hellos)) or []:
                self.sock.sendto(proto.encode(resposta), origem)


class Base(unittest.TestCase):
    def setUp(self):
        self.host_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.host_sock.bind(("127.0.0.1", 0))
        host_port = self.host_sock.getsockname()[1]
        ms = {"v": 1, "t": "MATCH_START", "match_id": "m7", "host_slot": 0,
              "config": {"width": 40, "height": 20, "tick_ms": 100},
              "players": [
                  {"slot": 0, "name": "Alice", "host": "127.0.0.1", "port": host_port},
                  {"slot": 1, "name": "Bob", "host": "127.0.0.1", "port": porta_livre()},
                  {"slot": 2, "name": "Carol", "host": "127.0.0.1", "port": 6003},
              ]}
        self.cli = Client(CFG, ms, 1)
        self.cli.abrir()
        self.cli_addr = self.cli.sock.getsockname()
        self.host = None
        self.extras = []

    def tearDown(self):
        if self.host:
            self.host.parar.set()
            self.host.join(1)
        self.cli.fechar()
        self.host_sock.close()
        for s in self.extras:
            s.close()

    def iniciar_host(self, reagir):
        self.host = HostFalso(self.host_sock, reagir)
        self.host.start()
        return self.host


class TestHandshake(Base):
    def test_responde_ao_primeiro_hello(self):
        self.iniciar_host(lambda n: [WELCOME])
        r = self.cli.handshake()
        self.assertTrue(r["ok"])
        self.assertEqual(r["welcome"]["t"], "WELCOME")
        self.assertEqual(self.cli.tentativas_hello, 1)

    def test_hello_tem_o_formato_certo_e_sai_da_porta_registrada(self):
        h = self.iniciar_host(lambda n: [WELCOME])
        self.cli.handshake()
        msg, origem = h.hellos[0]
        self.assertEqual((msg["t"], msg["m"], msg["pid"], msg["v"]), ("HELLO", "m7", 1, 1))
        self.assertEqual(origem, self.cli_addr)

    def test_reenvia_hello_ate_o_host_responder(self):
        h = self.iniciar_host(lambda n: [WELCOME] if n >= 4 else [])
        t0 = time.monotonic()
        r = self.cli.handshake()
        self.assertTrue(r["ok"])
        self.assertEqual(len(h.hellos), 4)
        self.assertEqual(self.cli.tentativas_hello, 4)
        # 3 intervalos de 50 ms entre o 1o e o 4o HELLO
        self.assertGreaterEqual(time.monotonic() - t0, 0.14)

    def test_welcome_perdido_o_proximo_hello_pede_de_novo(self):
        # o host "recebeu" o 1o HELLO mas o WELCOME dele se perdeu
        self.iniciar_host(lambda n: [WELCOME] if n == 2 else [])
        self.assertTrue(self.cli.handshake()["ok"])
        self.assertEqual(self.cli.tentativas_hello, 2)

    def test_desiste_no_prazo_sem_welcome(self):
        h = self.iniciar_host(lambda n: [])
        t0 = time.monotonic()
        r = self.cli.handshake()
        dur = time.monotonic() - t0
        self.assertEqual(r, {"ok": False, "motivo": "DEADLINE"})
        self.assertGreaterEqual(dur, 0.58)
        self.assertLess(dur, 1.2)
        self.assertGreaterEqual(len(h.hellos), 8)      # ~600/50 = 12 tentativas
        self.assertIsNone(self.cli.welcome)

    def test_abort_do_host_encerra_o_handshake(self):
        self.iniciar_host(lambda n: [proto.abort("m7", "host saiu")])
        r = self.cli.handshake()
        self.assertEqual(r, {"ok": False, "motivo": "ABORT", "reason": "host saiu"})

    def test_tick_antes_do_welcome_e_ignorado(self):
        self.iniciar_host(lambda n: [proto.tick("m7", []), WELCOME])
        r = self.cli.handshake()
        self.assertTrue(r["ok"])
        self.assertEqual(r["welcome"]["t"], "WELCOME")

    def test_welcome_invalido_e_ignorado(self):
        ruim = proto.welcome("m7", {"width": 40, "height": 20, "players": []}, 3000)
        self.iniciar_host(lambda n: [ruim] if n == 1 else [WELCOME])
        r = self.cli.handshake()
        self.assertTrue(r["ok"])
        self.assertEqual(self.cli.tentativas_hello, 2)

    def test_welcome_de_outro_endereco_e_ignorado(self):
        estranho = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        estranho.bind(("127.0.0.1", 0))
        self.extras.append(estranho)

        def reagir(n):
            estranho.sendto(proto.encode(WELCOME), self.cli_addr)
            return []
        self.iniciar_host(reagir)
        self.assertEqual(self.cli.handshake()["motivo"], "DEADLINE")

    def test_welcome_de_outra_partida_e_ignorado(self):
        outra = proto.welcome("m99", STATE, 3000)
        self.iniciar_host(lambda n: [outra])
        self.assertEqual(self.cli.handshake()["motivo"], "DEADLINE")


class TestEstadoGuardado(Base):
    def test_guarda_o_que_as_proximas_partes_precisam(self):
        self.iniciar_host(lambda n: [WELCOME])
        antes = time.monotonic()
        self.cli.handshake()
        self.assertEqual(self.cli.state["width"], 40)
        self.assertEqual(self.cli.countdown_ms, 3000)
        self.assertEqual(self.cli.dir_desejada, "L")    # direcao do pid 1 no WELCOME
        self.assertEqual(self.cli.tick_ms, 100)
        self.assertGreaterEqual(self.cli.t_welcome, antes)

    def test_tick_ms_do_welcome_tem_prioridade(self):
        estado = dict(STATE, tick_ms=50)
        self.iniciar_host(lambda n: [proto.welcome("m7", estado, 3000)])
        self.cli.handshake()
        self.assertEqual(self.cli.tick_ms, 50)

    def test_estado_nao_e_preenchido_se_falhar(self):
        self.iniciar_host(lambda n: [])
        self.cli.handshake()
        self.assertIsNone(self.cli.state)
        self.assertIsNone(self.cli.dir_desejada)


class TestPrazos(unittest.TestCase):
    MS = {"v": 1, "t": "MATCH_START", "match_id": "m7", "host_slot": 0,
          "config": {"width": 40, "height": 20, "tick_ms": 100},
          "players": [
              {"slot": 0, "name": "A", "host": "192.168.0.21", "port": 6001},
              {"slot": 1, "name": "B", "host": "192.168.0.22", "port": 6002}]}

    def test_le_da_config(self):
        c = Client({"timeouts": {"hello_retry_ms": 250, "hello_deadline_ms": 4000}}, self.MS, 1)
        self.assertEqual(c.prazos(), (0.25, 4.0))

    def test_padroes_do_readme(self):
        self.assertEqual(Client({}, self.MS, 1).prazos(), (0.5, 10.0))

    def test_handshake_abre_o_socket_sozinho_se_preciso(self):
        porta = porta_livre()
        ms = dict(self.MS, players=[
            {"slot": 0, "name": "A", "host": "127.0.0.1", "port": porta_livre()},
            {"slot": 1, "name": "B", "host": "127.0.0.1", "port": porta}])
        cfg = {"peer": {"bind_host": "127.0.0.1"},
               "timeouts": {"hello_retry_ms": 20, "hello_deadline_ms": 100}}
        c = Client(cfg, ms, 1)
        try:
            self.assertEqual(c.handshake()["motivo"], "DEADLINE")
            self.assertEqual(c.sock.getsockname(), ("127.0.0.1", porta))
        finally:
            c.fechar()


if __name__ == "__main__":
    unittest.main()
