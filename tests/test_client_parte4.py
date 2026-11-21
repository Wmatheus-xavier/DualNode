"""Testes da Parte 4 do peer/client.py (GameView, tela e espera do inicio).
Rodar da raiz do projeto:

    python3 -m unittest tests.test_client_parte4 -v

Usa uma tela FALSA (nao abre curses) e datagramas reais em 127.0.0.1.
"""

import socket
import time
import unittest

from common import protocol as proto
import peer.client as client_mod
from peer.client import Client

try:
    from peer.ui import GameView
    TEM_UI = True
except ImportError:                      # curses indisponivel (ex.: Windows sem windows-curses)
    TEM_UI = False

STATE = {"width": 40, "height": 20, "tick_ms": 100, "players": [
    {"pid": 0, "x": 5, "y": 5, "dir": "R"},
    {"pid": 1, "x": 34, "y": 14, "dir": "L"},
    {"pid": 2, "x": 20, "y": 1, "dir": "D"},
]}
WELCOME = proto.welcome("m7", STATE, 3000)
CFG = {"peer": {"bind_host": "127.0.0.1"},
       "timeouts": {"hello_retry_ms": 50, "hello_deadline_ms": 500, "host_timeout_ms": 300}}


def rec(n):
    return {"n": n, "mv": [[0, 5 + n, 5]], "el": [], "end": None}


def porta_livre():
    tmp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tmp.bind(("127.0.0.1", 0))
    porta = tmp.getsockname()[1]
    tmp.close()
    return porta


class TelaFalsa:
    """Imita a TerminalUI: guarda o que foi desenhado e entrega teclas roteirizadas."""

    def __init__(self, teclas=()):
        self.teclas = list(teclas)
        self.status_desenhados = []
        self.chamadas_draw = 0
        self.entrou = False
        self.saiu = False

    def __enter__(self):
        self.entrou = True
        return self

    def __exit__(self, *exc):
        self.saiu = True
        return False

    def poll_input(self):
        return self.teclas.pop(0) if self.teclas else None

    def draw(self, view):
        self.chamadas_draw += 1
        self.status_desenhados.append(view.status)

    def wait_key(self):
        pass


@unittest.skipUnless(TEM_UI, "peer.ui (curses) indisponivel neste ambiente")
class Base(unittest.TestCase):
    def setUp(self):
        self.host = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.host.bind(("127.0.0.1", 0))
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
        self.cli._guardar_welcome(WELCOME)     # como se o handshake ja tivesse dado certo

    def tearDown(self):
        self.cli.fechar()
        self.host.close()

    def do_host(self, msg):
        self.host.sendto(proto.encode(msg), self.cli_addr)


class TestMontarView(Base):
    def test_view_reflete_o_welcome(self):
        v = self.cli.montar_view()
        self.assertEqual((v.width, v.height), (40, 20))
        self.assertEqual(v.my_pid, 1)
        self.assertEqual(v.heads, {0: (5, 5), 1: (34, 14), 2: (20, 1)})
        self.assertEqual(v.alive, {0: True, 1: True, 2: True})
        self.assertEqual(v.cells[(34, 14)], 1)       # a celula inicial ja e rastro
        self.assertEqual(v.tick, 0)
        self.assertIsNone(v.result)

    def test_nomes_vem_do_match_start(self):
        v = self.cli.montar_view()
        self.assertEqual(v.name(0), "Alice")
        self.assertEqual(v.name(1), "Bob")
        self.assertEqual(v.name(2), "Carol")

    def test_sem_handshake_da_erro_claro(self):
        self.cli.state = None
        with self.assertRaises(RuntimeError):
            self.cli.montar_view()


class TestAguardarInicio(Base):
    def test_comeca_no_primeiro_tick_com_registros(self):
        self.do_host(proto.tick("m7", [rec(1)]))
        r = self.cli.aguardar_inicio()
        self.assertTrue(r["ok"])
        self.assertEqual(r["tick"]["recs"][0]["n"], 1)

    def test_nao_aplica_o_tick_na_view(self):
        """Quem aplica em ordem e a Parte 6; aqui so avisa que comecou."""
        self.do_host(proto.tick("m7", [rec(1)]))
        self.cli.aguardar_inicio()
        self.assertEqual(self.cli.view.tick, 0)
        self.assertEqual(self.cli.view.heads[0], (5, 5))

    def test_tick_vazio_nao_inicia(self):
        for _ in range(3):
            self.do_host(proto.tick("m7", []))
        self.do_host(proto.tick("m7", [rec(1)]))
        r = self.cli.aguardar_inicio()
        self.assertTrue(r["ok"])

    def test_welcome_repetido_e_ignorado(self):
        self.do_host(WELCOME)
        self.do_host(proto.tick("m7", [rec(1)]))
        self.assertTrue(self.cli.aguardar_inicio()["ok"])

    def test_abort_do_host(self):
        self.do_host(proto.abort("m7", "jogadores insuficientes"))
        r = self.cli.aguardar_inicio()
        self.assertEqual(r, {"ok": False, "motivo": "ABORT",
                             "reason": "jogadores insuficientes"})

    def test_q_sai(self):
        self.tela.teclas = [None, None, "QUIT"]
        self.assertEqual(self.cli.aguardar_inicio(), {"ok": False, "motivo": "QUIT"})

    def test_host_sumiu_antes_do_inicio(self):
        t0 = time.monotonic()
        r = self.cli.aguardar_inicio()                 # nenhum TICK chega
        dur = time.monotonic() - t0
        self.assertEqual(r, {"ok": False, "motivo": "HOST_LOST"})
        self.assertGreaterEqual(dur, 0.29)             # host_timeout_ms = 300
        self.assertLess(dur, 0.8)

    def test_tick_vazio_renova_o_prazo_do_host(self):
        """Enquanto o host manda TICK (mesmo vazio), ele nao e dado como perdido."""
        import threading

        def mandar():
            for _ in range(8):                         # 8 x 100 ms = 0,8 s > 0,3 s
                time.sleep(0.1)
                self.do_host(proto.tick("m7", []))
            self.do_host(proto.tick("m7", [rec(1)]))
        t = threading.Thread(target=mandar, daemon=True)
        t.start()
        r = self.cli.aguardar_inicio()
        t.join()
        self.assertTrue(r["ok"])

    def test_teclas_na_espera_atualizam_a_direcao_desejada(self):
        self.tela.teclas = ["U", None, "R"]
        self.do_host(proto.tick("m7", [rec(1)]))
        # em cada volta o teclado e lido ANTES da rede: so "U" chega a ser lida,
        # porque o TICK com registros ja esta na fila e encerra a espera
        self.cli.aguardar_inicio()
        self.assertEqual(self.cli.dir_desejada, "U")

    def test_sem_teclas_mantem_a_direcao_do_welcome(self):
        self.do_host(proto.tick("m7", [rec(1)]))
        self.cli.aguardar_inicio()
        self.assertEqual(self.cli.dir_desejada, "L")

    def test_desenha_a_arena_com_mensagem_de_espera(self):
        self.do_host(proto.tick("m7", [rec(1)]))
        self.cli.aguardar_inicio()
        self.assertGreaterEqual(self.tela.chamadas_draw, 1)
        self.assertIn("Aguardando", self.tela.status_desenhados[0])

    def test_exige_tela_aberta(self):
        self.cli.ui = None
        with self.assertRaises(RuntimeError):
            self.cli.aguardar_inicio()


class TestTela(Base):
    def test_ui_do_main_nao_e_fechada_pelo_client(self):
        self.assertIs(self.cli.abrir_tela(), self.tela)
        self.cli.fechar_tela()
        self.assertFalse(self.tela.entrou)
        self.assertFalse(self.tela.saiu)
        self.assertIs(self.cli.ui, self.tela)          # continua sendo a do main

    def test_sem_ui_o_client_abre_e_fecha_a_propria(self):
        propria = TelaFalsa()
        original = client_mod._criar_tela
        client_mod._criar_tela = lambda: propria
        try:
            self.cli.ui = None
            self.assertIs(self.cli.abrir_tela(), propria)
            self.assertTrue(propria.entrou)
            self.assertFalse(propria.saiu)
            self.cli.fechar_tela()
            self.assertTrue(propria.saiu)
            self.assertIsNone(self.cli.ui)
            self.cli.fechar_tela()                     # chamar de novo nao quebra
        finally:
            client_mod._criar_tela = original

    def test_host_timeout_le_da_config_ou_usa_padrao(self):
        self.assertEqual(self.cli.host_timeout_s(), 0.3)
        self.cli.cfg = {}
        self.assertEqual(self.cli.host_timeout_s(), 3.0)


if __name__ == "__main__":
    unittest.main()
