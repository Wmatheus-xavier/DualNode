"""Testes da Parte 6 do peer/client.py (aplicar o TICK em ordem).
Rodar da raiz do projeto:

    python3 -m unittest tests.test_client_parte6 -v

Blocos:
  1. aplicar_tick (sem rede): ordem, duplicata, buraco, janela, fim.
  2. consistencia: jogo REAL (common/game_logic.py) entregue por uma rede com
     perda, duplicatas e reordenacao; a tela do cliente tem que ficar igual
     ao estado final do jogo.
  3. rodar_partida: laco com host falso (tela falsa, sem curses).
  4. ponta a ponta: Host REAL (peer/host.py) + Client em sockets de verdade.
"""

import random
import socket
import threading
import time
import unittest

from common import protocol as proto
from peer.client import Client, validar_recs

try:
    import peer.ui  # noqa: F401
    TEM_UI = True
except ImportError:
    TEM_UI = False

try:
    from common.game_logic import aplicar_registro, novo_estado, step
    TEM_LOGICA = True
except ImportError:
    TEM_LOGICA = False

try:
    from peer.host import Host
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


def rec(n, mv=None, el=None, end=None):
    return {"n": n, "mv": mv if mv is not None else [[0, 5 + n, 5]],
            "el": el or [], "end": end}


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

    def poll_input(self):
        return self.teclas.pop(0) if self.teclas else None

    def draw(self, view):
        self.status.append(view.status)

    def wait_key(self):
        pass


@unittest.skipUnless(TEM_UI, "peer.ui (curses) indisponivel neste ambiente")
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
        self.cli.montar_view()

    def tearDown(self):
        self.cli.fechar()
        self.host.close()

    def tick(self, *recs):
        return proto.tick("m7", list(recs))

    def do_host(self, msg):
        self.host.sendto(proto.encode(msg), self.cli_addr)

    def acks_recebidos(self):
        acks = []
        while True:
            try:
                dados, _ = self.host.recvfrom(2048)
            except socket.timeout:
                return acks
            msg = proto.decode(dados)
            if msg is not None and msg["t"] == "INPUT":
                acks.append(msg["ack"])


# ---------------------------------------------------------------------------
# 1. aplicar_tick
# ---------------------------------------------------------------------------

class TestAplicarTick(Base):
    def test_aplica_o_primeiro_registro(self):
        n = self.cli.aplicar_tick(self.tick(rec(1, mv=[[0, 6, 5], [1, 33, 14]])))
        self.assertEqual(n, 1)
        self.assertEqual(self.cli.ack, 1)
        self.assertEqual(self.cli.view.tick, 1)
        self.assertEqual(self.cli.view.heads[0], (6, 5))
        self.assertEqual(self.cli.view.heads[1], (33, 14))
        self.assertEqual(self.cli.view.cells[(6, 5)], 0)

    def test_aplica_varios_em_ordem(self):
        n = self.cli.aplicar_tick(self.tick(rec(1), rec(2), rec(3)))
        self.assertEqual((n, self.cli.ack, self.cli.view.tick), (3, 3, 3))

    def test_duplicata_e_ignorada(self):
        self.cli.aplicar_tick(self.tick(rec(1)))
        eventos = list(self.cli.view.events)
        n = self.cli.aplicar_tick(self.tick(rec(1)))
        self.assertEqual(n, 0)
        self.assertEqual(self.cli.ack, 1)
        self.assertEqual(self.cli.view.events, eventos)
        self.assertEqual(self.cli.descartados.get("tick_repetido"), 1)

    def test_janela_sobreposta_aplica_so_os_novos(self):
        self.cli.aplicar_tick(self.tick(rec(1), rec(2)))
        n = self.cli.aplicar_tick(self.tick(rec(1), rec(2), rec(3), rec(4)))
        self.assertEqual((n, self.cli.ack), (2, 4))
        self.assertEqual(self.cli.view.heads[0], (9, 5))

    def test_buraco_nao_aplica_nada(self):
        n = self.cli.aplicar_tick(self.tick(rec(3), rec(4)))
        self.assertEqual((n, self.cli.ack, self.cli.view.tick), (0, 0, 0))
        self.assertEqual(self.cli.view.heads[0], (5, 5))
        self.assertEqual(self.cli.descartados.get("tick_com_buraco"), 1)

    def test_buraco_depois_de_aplicar_mantem_o_ack(self):
        self.cli.aplicar_tick(self.tick(rec(1), rec(2)))
        n = self.cli.aplicar_tick(self.tick(rec(4)))
        self.assertEqual((n, self.cli.ack), (0, 2))
        n = self.cli.aplicar_tick(self.tick(rec(2), rec(3), rec(4)))   # o host reenvia do ack
        self.assertEqual((n, self.cli.ack), (2, 4))

    def test_tick_vazio_nao_faz_nada(self):
        self.assertEqual(self.cli.aplicar_tick(self.tick()), 0)
        self.assertEqual(self.cli.ack, 0)
        self.assertEqual(self.cli.descartados, {})

    def test_eliminacao_marca_a_moto_como_morta_e_o_rastro_fica(self):
        self.cli.aplicar_tick(self.tick(rec(1, mv=[[0, 6, 5]], el=[[1, "WALL"]])))
        v = self.cli.view
        self.assertFalse(v.alive[1])
        self.assertTrue(v.alive[0])
        self.assertEqual(v.cells[(34, 14)], 1)                # rastro continua
        self.assertEqual(len(v.events), 1)

    def test_fim_define_o_resultado_e_para_de_aplicar(self):
        fim = {"result": "WIN", "winner": 0}
        n = self.cli.aplicar_tick(self.tick(rec(1, end=fim), rec(2), rec(3)))
        self.assertEqual((n, self.cli.ack), (1, 1))
        self.assertEqual(self.cli.view.result, fim)
        self.assertEqual(self.cli.aplicar_tick(self.tick(rec(2))), 0)   # depois do fim, nada

    def test_monta_a_view_sozinho_se_preciso(self):
        self.cli.view = None
        self.assertEqual(self.cli.aplicar_tick(self.tick(rec(1))), 1)


# ---------------------------------------------------------------------------
# 2. consistencia com o jogo real, sobre rede ruim
# ---------------------------------------------------------------------------

def jogar_de_verdade(semente, pids=(0, 1, 2)):
    """Roda uma partida inteira com a logica oficial. Devolve (estado_final, historico)."""
    rnd = random.Random(semente)
    estado = novo_estado(40, 20, list(pids))
    historico = []
    for n in range(1, 400):
        desejadas = {p: rnd.choice("UDLR") for p in pids if rnd.random() < 0.3}
        registro = step(estado, desejadas, set(), n)
        estado = aplicar_registro(estado, registro)
        historico.append(registro)
        if registro["end"] is not None:
            break
    return estado, historico


@unittest.skipUnless(TEM_UI and TEM_LOGICA, "peer.ui/game_logic indisponiveis neste ambiente")
class TestConsistenciaComRedeRuim(Base):
    """O host (simulado aqui, igual ao real) manda historico[ack : ack+8] a cada
    ciclo, para quem ele acha que ja confirmou ate 'ack'. A rede perde, duplica
    e embaralha datagramas. A tela tem que terminar igual ao jogo."""

    def simular(self, semente, perda, duplica, embaralha):
        estado, historico = jogar_de_verdade(semente)
        rnd = random.Random(semente * 7 + 1)
        ack_no_host = 0
        em_voo = []                                           # datagramas na rede
        for _ in range(5000):
            if self.cli.view.result is not None:
                break
            # host: manda a janela a partir do ultimo ack que ele conhece
            recs = historico[ack_no_host: ack_no_host + 8]
            if recs:
                msg = self.tick(*recs)
                self.assertTrue(validar_recs(msg["recs"]))
                for _ in range(2 if rnd.random() < duplica else 1):
                    if rnd.random() >= perda:
                        em_voo.append(msg)
            if embaralha and len(em_voo) > 1 and rnd.random() < embaralha:
                rnd.shuffle(em_voo)
            # cliente: recebe um ou dois datagramas e responde com o INPUT (ack)
            for _ in range(rnd.choice((1, 1, 2))):
                if em_voo:
                    self.cli.aplicar_tick(em_voo.pop(0))
            if rnd.random() >= perda:                         # o INPUT tambem pode se perder
                ack_no_host = max(ack_no_host, min(self.cli.ack, len(historico)))
        return estado, historico

    def confere(self, estado, historico):
        v = self.cli.view
        self.assertIsNotNone(v.result, "a partida nao terminou na tela do cliente")
        self.assertEqual(self.cli.ack, len(historico))
        self.assertEqual(v.tick, len(historico))
        self.assertEqual(v.heads, estado["heads"])
        self.assertEqual(v.alive, estado["alive"])
        self.assertEqual(v.cells, estado["cells"])
        self.assertEqual(v.result, historico[-1]["end"])

    def test_rede_perfeita(self):
        self.confere(*self.simular(1, perda=0.0, duplica=0.0, embaralha=0.0))

    def test_com_perda(self):
        for semente in (2, 3, 4):
            with self.subTest(semente=semente):
                self.tearDown()
                self.setUp()      # socket e tela novos a cada semente
                self.confere(*self.simular(semente, perda=0.4, duplica=0.0, embaralha=0.0))

    def test_com_duplicatas_e_embaralhamento(self):
        for semente in (5, 6, 7):
            with self.subTest(semente=semente):
                self.tearDown()
                self.setUp()      # socket e tela novos a cada semente
                self.confere(*self.simular(semente, perda=0.0, duplica=0.5, embaralha=0.7))

    def test_com_tudo_junto(self):
        for semente in range(10, 16):
            with self.subTest(semente=semente):
                self.tearDown()
                self.setUp()      # socket e tela novos a cada semente
                self.confere(*self.simular(semente, perda=0.35, duplica=0.4, embaralha=0.6))


# ---------------------------------------------------------------------------
# 3. rodar_partida (laco)
# ---------------------------------------------------------------------------

class TestRodarPartida(Base):
    FIM_WIN = {"result": "WIN", "winner": 0}

    def test_aplica_ticks_ate_o_fim(self):
        self.do_host(self.tick(rec(1)))
        self.do_host(self.tick(rec(2)))
        self.do_host(self.tick(rec(3, end=self.FIM_WIN)))
        r = self.cli.rodar_partida()
        self.assertEqual(r, {"ok": True, "fim": self.FIM_WIN})
        self.assertEqual((self.cli.ack, self.cli.view.tick), (3, 3))

    def test_empate(self):
        self.do_host(self.tick(rec(1, end={"result": "DRAW"})))
        self.assertEqual(self.cli.rodar_partida()["fim"], {"result": "DRAW"})

    def test_tick_inicial_vindo_do_aguardar_inicio(self):
        self.do_host(self.tick(rec(2, end=self.FIM_WIN)))
        r = self.cli.rodar_partida(tick_inicial=self.tick(rec(1)))
        self.assertTrue(r["ok"])
        self.assertEqual(self.cli.ack, 2)

    def test_duplicatas_e_fora_de_ordem(self):
        self.do_host(self.tick(rec(2)))                       # buraco: ainda falta o 1
        self.do_host(self.tick(rec(1)))
        self.do_host(self.tick(rec(1), rec(2)))               # janela repetida
        self.do_host(self.tick(rec(2), rec(3, end=self.FIM_WIN)))
        r = self.cli.rodar_partida()
        self.assertTrue(r["ok"])
        self.assertEqual(self.cli.ack, 3)
        self.assertEqual(self.cli.view.heads[0], (8, 5))

    def test_abort(self):
        self.do_host(proto.abort("m7", "host saiu"))
        self.assertEqual(self.cli.rodar_partida(),
                         {"ok": False, "motivo": "ABORT", "reason": "host saiu"})

    def test_q_sai(self):
        self.tela.teclas = [None, "QUIT"]
        self.assertEqual(self.cli.rodar_partida(), {"ok": False, "motivo": "QUIT"})

    def test_host_mudo_vira_host_lost(self):
        t0 = time.monotonic()
        r = self.cli.rodar_partida()
        self.assertEqual(r, {"ok": False, "motivo": "HOST_LOST"})
        self.assertGreaterEqual(time.monotonic() - t0, 0.29)  # host_timeout_ms = 300

    def test_tick_vazio_e_sinal_de_vida(self):
        def host():
            for _ in range(8):                                # 0,8 s, mais que os 0,3 s do prazo
                time.sleep(0.1)
                self.do_host(self.tick())
            self.do_host(self.tick(rec(1, end=self.FIM_WIN)))
        t = threading.Thread(target=host, daemon=True)
        t.start()
        r = self.cli.rodar_partida()
        t.join()
        self.assertTrue(r["ok"])

    def test_tick_repetido_tambem_renova_o_prazo(self):
        self.cli.aplicar_tick(self.tick(rec(1)))
        def host():
            for _ in range(6):
                time.sleep(0.1)
                self.do_host(self.tick(rec(1)))               # so repete o que ja foi aplicado
            self.do_host(self.tick(rec(2, end=self.FIM_WIN)))
        t = threading.Thread(target=host, daemon=True)
        t.start()
        r = self.cli.rodar_partida()
        t.join()
        self.assertTrue(r["ok"])

    def test_input_leva_o_ack_atualizado(self):
        def host():
            time.sleep(0.1)
            self.do_host(self.tick(rec(1)))
            time.sleep(0.2)
            self.do_host(self.tick(rec(1), rec(2)))
            time.sleep(0.25)
            self.do_host(self.tick(rec(3, end=self.FIM_WIN)))
        t = threading.Thread(target=host, daemon=True)
        t.start()
        r = self.cli.rodar_partida()
        t.join()
        self.assertTrue(r["ok"])
        acks = self.acks_recebidos()
        self.assertEqual(acks, sorted(acks))                  # o ack so cresce
        self.assertTrue({0, 1, 2} <= set(acks), acks)

    def test_eliminado_continua_assistindo(self):
        self.do_host(self.tick(rec(1, el=[[1, "WALL"]])))
        self.do_host(self.tick(rec(2, end=self.FIM_WIN)))
        r = self.cli.rodar_partida()
        self.assertTrue(r["ok"])
        self.assertTrue(any("eliminado" in (s or "") for s in self.tela.status))

    def test_mensagem_vivo_nao_aparece(self):
        self.do_host(self.tick(rec(1, end=self.FIM_WIN)))
        self.cli.rodar_partida()
        self.assertFalse(any("eliminado" in (s or "") for s in self.tela.status))

    def test_exige_tela_aberta(self):
        self.cli.ui = None
        with self.assertRaises(RuntimeError):
            self.cli.rodar_partida()


# ---------------------------------------------------------------------------
# 4. ponta a ponta com o Host REAL
# ---------------------------------------------------------------------------

@unittest.skipUnless(TEM_HOST and TEM_UI and TEM_LOGICA, "peer.host/ui/game_logic indisponiveis")
class TestPontaAPontaComHostReal(unittest.TestCase):
    """Host real (thread) + Client real, em sockets de verdade.
    Dois jogadores: o host (slot 0, anda para a direita) e o peer (slot 1, para a
    esquerda). Sem teclado, os dois seguem reto ate a parede. O que o cliente
    desenha tem que ser igual ao que o host registrou."""

    def test_partida_completa(self):
        porta_host, porta_peer = porta_livre(), porta_livre()
        ms = {"v": 1, "t": "MATCH_START", "match_id": "m7", "host_slot": 0,
              "config": {"width": 40, "height": 20, "tick_ms": 20},
              "players": [
                  {"slot": 0, "name": "Alice", "host": "127.0.0.1", "port": porta_host},
                  {"slot": 1, "name": "Bob", "host": "127.0.0.1", "port": porta_peer}]}
        cfg = {"peer": {"bind_host": "127.0.0.1"},
               "timeouts": {"hello_retry_ms": 100, "hello_deadline_ms": 5000,
                            "host_timeout_ms": 3000, "peer_timeout_ms": 500}}
        host = Host(cfg, ms)                                  # sem tela
        resultado_host = {}
        erro = []

        def rodar_host():
            try:
                resultado_host.update(host.run())
            except Exception as e:                            # noqa: BLE001
                erro.append(e)
        t = threading.Thread(target=rodar_host, daemon=True)
        t.start()

        tela = TelaFalsa()
        cli = Client(cfg, ms, 1, ui=tela)
        try:
            cli.abrir()
            hs = cli.handshake()
            self.assertTrue(hs["ok"], hs)
            cli.montar_view()
            ini = cli.aguardar_inicio()
            self.assertTrue(ini["ok"], ini)
            r = cli.rodar_partida(tick_inicial=ini["tick"])
        finally:
            cli.fechar()
        t.join(10)
        self.assertEqual(erro, [])
        self.assertTrue(r["ok"], r)
        # mesmo resultado que o host
        self.assertEqual(r["fim"]["result"], resultado_host["result"])
        self.assertEqual(r["fim"].get("winner"), resultado_host.get("winner"))
        # mesma tela que o host
        self.assertEqual(cli.view.cells, host.view.cells)
        self.assertEqual(cli.view.alive, host.view.alive)
        self.assertEqual(cli.view.heads, host.view.heads)
        self.assertEqual(cli.ack, len(host.historico))
        self.assertEqual(cli.view.tick, host.view.tick)


if __name__ == "__main__":
    unittest.main()
