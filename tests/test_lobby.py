# tests/test_lobby.py
# Roda com: python3 -m unittest tests.test_lobby -v
import copy
import ipaddress
import socket
import threading
import time
import unittest

from common import protocol as p
from common.config import DEFAULTS
from lobby.server import LobbyServer


class Cli:
    """Cliente TCP mínimo para conversar com o lobby nos testes."""

    def __init__(self, porta):
        self.sock = socket.create_connection(("127.0.0.1", porta), timeout=2)
        self.buf = p.LineBuffer()
        self.pendentes = []

    def manda(self, msg):
        self.sock.sendall(msg if isinstance(msg, bytes) else p.encode_line(msg))

    def espera(self, tipo, timeout=2.0):
        """Devolve a primeira mensagem do tipo pedido (ignora PING)."""
        limite = time.monotonic() + timeout
        while True:
            for i, m in enumerate(self.pendentes):
                if m is not None and m["t"] == tipo:
                    return self.pendentes.pop(i)
            restante = limite - time.monotonic()
            if restante <= 0:
                raise AssertionError("não chegou %s; chegou %s" % (tipo, self.pendentes))
            self.sock.settimeout(restante)
            try:
                dados = self.sock.recv(4096)
            except socket.timeout:
                continue
            if not dados:
                raise ConnectionError("lobby fechou a conexão")
            self.pendentes.extend(m for m in self.buf.feed(dados) if m and m["t"] != "PING")

    def erro(self, code):
        m = self.espera("ERROR")
        assert m["code"] == code, m
        return m

    def fechada(self, timeout=2.0):
        self.sock.settimeout(timeout)
        try:
            while True:
                if not self.sock.recv(4096):
                    return True
        except (ConnectionResetError, socket.timeout):
            return False

    def registra(self, nome, udp):
        self.manda(p.register(nome, udp))
        return self.espera("REGISTER_OK")

    def close(self):
        self.sock.close()


class TestLobby(unittest.TestCase):
    def setUp(self):
        cfg = copy.deepcopy(DEFAULTS)
        cfg["timeouts"]["lobby_ping_ms"] = 100
        cfg["timeouts"]["lobby_dead_ms"] = 600
        self.srv = LobbyServer(cfg, bind_host="127.0.0.1", port=0)
        self.th = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.th.start()
        self.clis = []

    def tearDown(self):
        for c in self.clis:
            c.close()
        self.srv.parar()
        self.th.join(2)

    def cli(self, nome=None, udp=None):
        c = Cli(self.srv.porta)
        self.clis.append(c)
        if nome:
            c.registra(nome, udp)
        return c

    def sala_com(self, n):
        """Cria uma sala e coloca n jogadores. Devolve (criador, outros, match_id)."""
        a = self.cli("Ana", 6001)
        a.manda(p.create_match("sala", 4))
        mid = a.espera("MATCH_CREATED")["match_id"]
        outros = []
        for i in range(1, n):
            c = self.cli("J%d" % i, 6001 + i)
            c.manda(p.join_match(mid))
            c.espera("JOIN_OK")
            outros.append(c)
        return a, outros, mid

    # ---------- enquadramento ----------

    def test_duas_mensagens_no_mesmo_recv(self):
        c = self.cli()
        c.manda(p.encode_line(p.register("Ana", 6001)) + p.encode_line(p.list_matches()))
        c.espera("REGISTER_OK")
        self.assertEqual(c.espera("MATCH_LIST")["matches"], [])

    def test_mensagem_partida_em_dois_envios(self):
        c = self.cli()
        linha = p.encode_line(p.register("Ana", 6001))
        c.manda(linha[:10])
        time.sleep(0.1)
        c.manda(linha[10:])
        c.espera("REGISTER_OK")

    def test_linha_grande_demais_fecha(self):
        c = self.cli()
        c.manda(b"x" * 5000)
        self.assertTrue(c.fechada())

    # ---------- erros de protocolo ----------

    def test_bad_format_tres_vezes_fecha(self):
        c = self.cli()
        for _ in range(3):
            c.manda(b"isso nao e json\n")
        c.erro("BAD_FORMAT")
        self.assertTrue(c.fechada())

    def test_unknown_type_e_invalid_param(self):
        c = self.cli()
        c.manda(b'{"v":1,"t":"DANCAR"}\n')
        c.erro("UNKNOWN_TYPE")
        c.manda(b'{"v":1,"t":"REGISTER","name":"Ana"}\n')     # falta udp_port
        c.erro("INVALID_PARAM")

    def test_bad_state(self):
        c = self.cli()
        c.manda(p.list_matches())                  # ainda não registrou
        c.erro("BAD_STATE")
        c.registra("Ana", 6001)                    # e o estado não mudou por causa do erro

    # ---------- REGISTER ----------

    def test_register_validacoes(self):
        c = self.cli()
        for msg in (p.register("nome com espaco", 6001), p.register("x" * 17, 6001),
                    p.register("Ana", 80), p.register("Ana", 6001, "localhost"),
                    p.register("Ana", 6001, "0.0.0.0")):
            c.manda(msg)
            c.erro("INVALID_PARAM")
        c.registra("Ana", 6001)
        d = self.cli()
        d.manda(p.register("Ana", 6002))
        d.erro("NAME_TAKEN")

    # ---------- salas ----------

    def test_create_list_join_e_avisos(self):
        a = self.cli("Ana", 6001)
        a.manda(p.create_match("sala", 9))
        a.erro("INVALID_PARAM")
        a.manda(p.create_match("sala", 3))
        mid = a.espera("MATCH_CREATED")["match_id"]
        b = self.cli("Bob", 6002)
        b.manda(p.list_matches())
        self.assertEqual(b.espera("MATCH_LIST")["matches"][0]["host_name"], "Ana")
        b.manda(p.join_match(mid))
        ok = b.espera("JOIN_OK")
        self.assertEqual(ok["slot"], 1)
        self.assertEqual([q["name"] for q in ok["players"]], ["Ana", "Bob"])
        self.assertEqual(a.espera("PLAYER_JOINED")["name"], "Bob")
        b.manda(p.join_match("m999"))
        b.erro("BAD_STATE")                        # já está numa sala

    def test_erros_de_join(self):
        a = self.cli("Ana", 6001)
        a.manda(p.create_match("sala", 3))
        mid = a.espera("MATCH_CREATED")["match_id"]
        b = self.cli("Bob", 6001)                  # mesma máquina e mesma porta que a Ana
        b.manda(p.join_match(mid))
        b.erro("INVALID_PARAM")
        b.manda(p.join_match("m999"))
        b.erro("MATCH_NOT_FOUND")
        for i in (2, 3):
            c = self.cli("J%d" % i, 6000 + i)
            c.manda(p.join_match(mid))
            c.espera("JOIN_OK")
        d = self.cli("Dan", 6009)
        d.manda(p.join_match(mid))
        d.erro("MATCH_FULL")

    def test_leave_e_criador_saindo_cancela(self):
        a, (b, c), mid = self.sala_com(3)
        c.manda(p.leave_match())
        self.assertEqual(a.espera("PLAYER_LEFT")["name"], "J2")
        a.manda(p.leave_match())
        self.assertIn("criador", b.espera("MATCH_CANCELLED")["reason"])
        b.manda(p.list_matches())                  # voltou para REGISTERED
        self.assertEqual(b.espera("MATCH_LIST")["matches"], [])

    def test_desconexao_avisa_a_sala(self):
        a, (b,), mid = self.sala_com(2)
        b.close()
        self.clis.remove(b)
        self.assertEqual(a.espera("PLAYER_LEFT")["name"], "J1")

    # ---------- START_MATCH ----------

    def test_start_regras(self):
        a, (b,), mid = self.sala_com(2)
        b.manda(p.start_match())
        b.erro("NOT_CREATOR")
        a.manda(p.start_match())
        a.erro("NOT_ENOUGH_PLAYERS")

    def test_match_start_completo(self):
        a, outros, mid = self.sala_com(3)
        a.manda(p.start_match())
        msgs = [c.espera("MATCH_START") for c in [a] + outros]
        self.assertTrue(all(m == msgs[0] for m in msgs))
        m = msgs[0]
        self.assertEqual(m["host_slot"], 0)
        self.assertEqual(m["config"], {"width": 40, "height": 20, "tick_ms": 100})
        self.assertEqual([q["slot"] for q in m["players"]], [0, 1, 2])
        for q in m["players"]:
            ipaddress.IPv4Address(q["host"])       # IP numérico, nunca "localhost"
        # sala iniciada some da lista e não aceita mais ninguém
        d = self.cli("Dan", 6009)
        d.manda(p.list_matches())
        self.assertEqual(d.espera("MATCH_LIST")["matches"], [])
        d.manda(p.join_match(mid))
        d.erro("MATCH_STARTED")

    def test_volta_da_partida(self):
        a, (b, c), mid = self.sala_com(3)
        a.manda(p.start_match())
        for x in (a, b, c):
            x.espera("MATCH_START")
        a.manda(p.match_end(1))                    # host avisa o fim
        a.manda(p.list_matches())
        a.espera("MATCH_LIST")
        b.manda(p.create_match("revanche", 3))     # peer comum só volta ao menu
        b.espera("MATCH_CREATED")

    # ---------- PING ----------

    def test_ping_e_remocao_de_quem_nao_responde(self):
        a, (b,), mid = self.sala_com(2)
        saiu = None
        limite = time.monotonic() + 3
        while saiu is None and time.monotonic() < limite:
            a.manda(p.pong())                      # a responde, b fica mudo
            try:
                saiu = a.espera("PLAYER_LEFT", timeout=0.1)
            except AssertionError:
                pass
        self.assertEqual(saiu["name"], "J1")
        self.assertTrue(b.fechada())

    def test_conexao_muda_sem_register_e_fechada(self):
        c = self.cli()                             # conecta e não manda nada
        self.assertTrue(c.fechada(timeout=2))

    def test_em_partida_nao_recebe_ping(self):
        a, outros, mid = self.sala_com(3)
        a.manda(p.start_match())
        a.espera("MATCH_START")
        time.sleep(0.8)                            # mais que lobby_dead_ms
        a.sock.settimeout(0.3)
        with self.assertRaises(socket.timeout):    # nada chega e a conexão continua aberta
            a.sock.recv(4096)


if __name__ == "__main__":
    unittest.main()
