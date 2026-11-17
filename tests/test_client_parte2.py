"""Testes da Parte 2 do peer/client.py (enviar, receber, filtrar e validar).
Rodar da raiz do projeto:

    python3 -m unittest tests.test_client_parte2 -v

Usa sockets reais em 127.0.0.1: um "host falso" manda datagramas para o Client.
"""

import copy
import socket
import time
import unittest

from common import protocol as proto
from peer.client import (Client, validar_recs, validar_registro, validar_state)

CFG = {"peer": {"bind_host": "127.0.0.1"}}

STATE = {"width": 40, "height": 20, "tick_ms": 100, "players": [
    {"pid": 0, "x": 5, "y": 5, "dir": "R"},
    {"pid": 1, "x": 34, "y": 14, "dir": "L"},
    {"pid": 2, "x": 20, "y": 1, "dir": "D"},
]}


def rec(n, mv=None, el=None, end=None):
    return {"n": n, "mv": mv if mv is not None else [[0, 5 + n, 5]],
            "el": el or [], "end": end}


def porta_livre():
    tmp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tmp.bind(("127.0.0.1", 0))
    porta = tmp.getsockname()[1]
    tmp.close()
    return porta


class Base(unittest.TestCase):
    """Cria um host falso (socket) e um Client (slot 1) apontando para ele."""

    def setUp(self):
        self.host = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.host.bind(("127.0.0.1", 0))
        self.host.settimeout(1)
        self.host_port = self.host.getsockname()[1]
        ms = {"v": 1, "t": "MATCH_START", "match_id": "m7", "host_slot": 0,
              "config": {"width": 40, "height": 20, "tick_ms": 100},
              "players": [
                  {"slot": 0, "name": "Alice", "host": "127.0.0.1", "port": self.host_port},
                  {"slot": 1, "name": "Bob", "host": "127.0.0.1", "port": porta_livre()},
                  {"slot": 2, "name": "Carol", "host": "127.0.0.1", "port": 6003},
              ]}
        self.cli = Client(CFG, ms, 1)
        self.cli.abrir()
        self.cli_addr = self.cli.sock.getsockname()
        self.extras = []

    def tearDown(self):
        self.cli.fechar()
        self.host.close()
        for s in self.extras:
            s.close()

    def do_host(self, msg):
        """O host falso manda uma mensagem ao cliente."""
        self.host.sendto(proto.encode(msg), self.cli_addr)

    def bytes_do_host(self, dados):
        self.host.sendto(dados, self.cli_addr)

    def socket_estranho(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0))
        self.extras.append(s)
        return s


class TestEnviar(Base):
    def test_enviar_chega_ao_host_com_a_porta_registrada(self):
        ok = self.cli.enviar(proto.hello("m7", 1))
        self.assertTrue(ok)
        dados, origem = self.host.recvfrom(2048)
        self.assertEqual(origem, self.cli_addr)          # mesma porta do bind
        msg = proto.decode(dados)
        self.assertEqual(msg["t"], "HELLO")
        self.assertEqual(msg["pid"], 1)

    def test_enviar_input(self):
        self.cli.enviar(proto.input_msg("m7", 1, 1, "U", 0))
        msg = proto.decode(self.host.recvfrom(2048)[0])
        self.assertEqual((msg["iseq"], msg["dir"], msg["ack"]), (1, "U", 0))

    def test_enviar_sem_socket_devolve_false(self):
        self.cli.fechar()
        self.assertFalse(self.cli.enviar(proto.hello("m7", 1)))

    def test_mensagem_grande_demais_nao_e_enviada(self):
        gigante = proto.hello("m7", 1)
        gigante["lixo"] = "x" * 2000
        self.assertFalse(self.cli.enviar(gigante))
        self.host.settimeout(0.2)
        with self.assertRaises(socket.timeout):
            self.host.recvfrom(4096)


class TestReceberValidas(Base):
    def test_welcome_valido(self):
        self.do_host(proto.welcome("m7", STATE, 3000))
        msg = self.cli.receber(1)
        self.assertEqual(msg["t"], "WELCOME")
        self.assertEqual(msg["countdown_ms"], 3000)

    def test_tick_com_registros(self):
        self.do_host(proto.tick("m7", [rec(1), rec(2)]))
        msg = self.cli.receber(1)
        self.assertEqual([r["n"] for r in msg["recs"]], [1, 2])

    def test_tick_vazio_e_sinal_de_vida(self):
        self.do_host(proto.tick("m7", []))
        self.assertEqual(self.cli.receber(1)["recs"], [])

    def test_abort(self):
        self.do_host(proto.abort("m7", "host saiu"))
        self.assertEqual(self.cli.receber(1)["reason"], "host saiu")

    def test_tick_com_fim(self):
        r = rec(5, el=[[1, "TRAIL"]], end={"result": "WIN", "winner": 0})
        self.do_host(proto.tick("m7", [r]))
        self.assertEqual(self.cli.receber(1)["recs"][0]["end"]["winner"], 0)


class TestReceberDescartes(Base):
    def test_timeout_devolve_none(self):
        t0 = time.monotonic()
        self.assertIsNone(self.cli.receber(0.2))
        self.assertGreaterEqual(time.monotonic() - t0, 0.19)

    def test_timeout_zero_nao_bloqueia(self):
        t0 = time.monotonic()
        self.assertIsNone(self.cli.receber(0))
        self.assertLess(time.monotonic() - t0, 0.1)

    def test_origem_desconhecida_e_ignorada(self):
        estranho = self.socket_estranho()
        estranho.sendto(proto.encode(proto.tick("m7", [])), self.cli_addr)
        self.assertIsNone(self.cli.receber(0.3))
        self.assertEqual(self.cli.descartados.get("origem"), 1)

    def test_lixo_e_ignorado_e_a_espera_continua(self):
        self.bytes_do_host(b"isso nao e json")
        self.bytes_do_host(b'{"x":1}')
        self.bytes_do_host(b"\xff\xfe\x00")
        self.do_host(proto.tick("m7", []))          # a valida vem depois
        msg = self.cli.receber(1)
        self.assertEqual(msg["t"], "TICK")
        self.assertEqual(self.cli.descartados.get("invalido"), 3)

    def test_datagrama_grande_demais(self):
        self.bytes_do_host(b"{" + b" " * 1300 + b"}")
        self.assertIsNone(self.cli.receber(0.3))
        self.assertEqual(self.cli.descartados.get("invalido"), 1)

    def test_outra_partida(self):
        self.do_host(proto.tick("m99", []))
        self.assertIsNone(self.cli.receber(0.3))
        self.assertEqual(self.cli.descartados.get("partida"), 1)

    def test_tipo_que_peer_nao_recebe(self):
        self.do_host(proto.hello("m7", 0))
        self.do_host(proto.input_msg("m7", 0, 1, "U", 0))
        self.assertIsNone(self.cli.receber(0.3))
        self.assertEqual(self.cli.descartados.get("tipo"), 2)

    def test_versao_errada(self):
        msg = proto.tick("m7", [])
        msg["v"] = 2
        self.do_host(msg)
        self.assertIsNone(self.cli.receber(0.3))

    def test_welcome_com_state_ruim(self):
        ruim = copy.deepcopy(STATE)
        ruim["players"][0]["dir"] = "X"
        self.do_host(proto.welcome("m7", ruim, 3000))
        self.assertIsNone(self.cli.receber(0.3))
        self.assertEqual(self.cli.descartados.get("welcome"), 1)

    def test_tick_com_registro_ruim(self):
        quebrado = rec(1)
        del quebrado["el"]
        self.do_host(proto.tick("m7", [quebrado]))
        self.assertIsNone(self.cli.receber(0.3))
        self.assertEqual(self.cli.descartados.get("tick"), 1)

    def test_tick_com_n_nao_consecutivo(self):
        self.do_host(proto.tick("m7", [rec(1), rec(3)]))
        self.assertIsNone(self.cli.receber(0.3))

    def test_tick_com_mais_de_8_registros(self):
        self.do_host(proto.tick("m7", [rec(n) for n in range(1, 10)]))
        self.assertIsNone(self.cli.receber(0.3))

    def test_receber_sem_socket(self):
        self.cli.fechar()
        self.assertIsNone(self.cli.receber(0.1))

    def test_varias_validas_saem_uma_por_chamada_em_ordem(self):
        self.do_host(proto.tick("m7", [rec(1)]))
        self.do_host(proto.tick("m7", [rec(2)]))
        time.sleep(0.1)
        self.assertEqual(self.cli.receber(0.5)["recs"][0]["n"], 1)
        self.assertEqual(self.cli.receber(0.5)["recs"][0]["n"], 2)


class TestValidadores(unittest.TestCase):
    def test_state_valido(self):
        self.assertTrue(validar_state(STATE, 1))

    def test_state_sem_meu_pid(self):
        self.assertFalse(validar_state(STATE, 3))

    def test_state_fora_da_arena(self):
        ruim = copy.deepcopy(STATE)
        ruim["players"][1]["x"] = 40
        self.assertFalse(validar_state(ruim, 1))

    def test_state_pid_repetido(self):
        ruim = copy.deepcopy(STATE)
        ruim["players"][1]["pid"] = 0
        self.assertFalse(validar_state(ruim, 0))

    def test_state_tipos_errados(self):
        for ruim in (None, [], {"width": 40}, {"width": True, "height": 20, "players": [1]},
                     {"width": 40, "height": 20, "players": []}):
            self.assertFalse(validar_state(ruim, 1))

    def test_registro_valido_variantes(self):
        self.assertTrue(validar_registro(rec(1)))
        self.assertTrue(validar_registro(rec(2, el=[[1, "WALL"]])))
        self.assertTrue(validar_registro(rec(9, mv=[], end={"result": "DRAW"})))

    def test_registro_invalido_variantes(self):
        ruins = [
            None, [], {},
            {"n": 0, "mv": [], "el": [], "end": None},
            {"n": True, "mv": [], "el": [], "end": None},
            {"n": 1, "mv": [[0, 1]], "el": [], "end": None},
            {"n": 1, "mv": [[0, 1, "a"]], "el": [], "end": None},
            {"n": 1, "mv": [], "el": [[0, "QUEDA"]], "end": None},
            {"n": 1, "mv": [], "el": [], "end": {"result": "WIN"}},
            {"n": 1, "mv": [], "el": [], "end": {"result": "XX"}},
            {"n": 1, "mv": [], "el": []},
        ]
        for r in ruins:
            self.assertFalse(validar_registro(r), r)

    def test_recs_lista_vazia_vale(self):
        self.assertTrue(validar_recs([]))

    def test_recs_nao_lista(self):
        self.assertFalse(validar_recs(None))


class TestCompatibilidadeComGameView(unittest.TestCase):
    """O que o cliente aceita tambem precisa funcionar no GameView do ui.py."""

    def test_registros_validados_passam_pelo_gameview(self):
        try:
            from peer.ui import GameView
        except ImportError:
            self.skipTest("curses indisponivel neste ambiente")
        view = GameView(1, {0: "A", 1: "B", 2: "C"})
        self.assertTrue(validar_state(STATE, 1))
        view.load_welcome(STATE)
        recs = [rec(1, mv=[[0, 6, 5], [1, 33, 14]]),
                rec(2, mv=[[0, 7, 5]], el=[[1, "WALL"]], end={"result": "WIN", "winner": 0})]
        self.assertTrue(validar_recs(recs))
        for r in recs:
            view.apply_record(r)
        self.assertEqual(view.tick, 2)
        self.assertEqual(view.result["winner"], 0)
        self.assertFalse(view.alive[1])


if __name__ == "__main__":
    unittest.main()
