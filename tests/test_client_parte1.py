"""Testes da Parte 1 do peer/client.py. Rodar da raiz do projeto:

    python3 -m unittest tests.test_client_parte1 -v
"""

import copy
import socket
import unittest

from peer.client import Client, ErroPreparacao, abrir_socket, ler_match_start

MATCH_START = {
    "v": 1, "t": "MATCH_START", "match_id": "m7", "host_slot": 0,
    "config": {"width": 40, "height": 20, "tick_ms": 100},
    "players": [
        {"slot": 0, "name": "Alice", "host": "192.168.0.21", "port": 6001},
        {"slot": 1, "name": "Bob", "host": "192.168.0.22", "port": 6002},
        {"slot": 2, "name": "Carol", "host": "192.168.0.23", "port": 6003},
    ],
}


def com(alteracao):
    ms = copy.deepcopy(MATCH_START)
    alteracao(ms)
    return ms


def porta_livre():
    tmp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tmp.bind(("127.0.0.1", 0))
    porta = tmp.getsockname()[1]
    tmp.close()
    return porta


class TestLerMatchStart(unittest.TestCase):
    def test_peer_valido(self):
        info = ler_match_start(MATCH_START, 1)
        self.assertEqual(info["match_id"], "m7")
        self.assertEqual(info["meu_pid"], 1)
        self.assertEqual(info["host_pid"], 0)
        self.assertEqual(info["host_addr"], ("192.168.0.21", 6001))
        self.assertEqual(info["meu_addr"], ("192.168.0.22", 6002))
        self.assertEqual(info["config"]["tick_ms"], 100)
        self.assertEqual(sorted(info["players"]), [0, 1, 2])

    def test_slot_inexistente(self):
        with self.assertRaises(ErroPreparacao):
            ler_match_start(MATCH_START, 3)

    def test_host_nao_pode_ser_cliente(self):
        with self.assertRaises(ErroPreparacao):
            ler_match_start(MATCH_START, 0)

    def test_ip_localhost_rejeitado(self):
        ms = com(lambda m: m["players"][0].update(host="localhost"))
        with self.assertRaises(ErroPreparacao):
            ler_match_start(ms, 1)

    def test_ip_zero_rejeitado(self):
        ms = com(lambda m: m["players"][0].update(host="0.0.0.0"))
        with self.assertRaises(ErroPreparacao):
            ler_match_start(ms, 1)

    def test_porta_invalida(self):
        ms = com(lambda m: m["players"][1].update(port=80))
        with self.assertRaises(ErroPreparacao):
            ler_match_start(ms, 1)

    def test_slot_repetido(self):
        ms = com(lambda m: m["players"][2].update(slot=1))
        with self.assertRaises(ErroPreparacao):
            ler_match_start(ms, 1)

    def test_host_slot_fora_da_lista(self):
        ms = com(lambda m: m.update(host_slot=9))
        with self.assertRaises(ErroPreparacao):
            ler_match_start(ms, 1)

    def test_campo_faltando(self):
        ms = com(lambda m: m.pop("config"))
        with self.assertRaises(ErroPreparacao):
            ler_match_start(ms, 1)

    def test_lista_vazia(self):
        ms = com(lambda m: m.update(players=[]))
        with self.assertRaises(ErroPreparacao):
            ler_match_start(ms, 1)


class TestSocket(unittest.TestCase):
    def test_bind_na_porta_pedida(self):
        porta = porta_livre()
        sock = abrir_socket("127.0.0.1", porta)
        try:
            self.assertEqual(sock.getsockname(), ("127.0.0.1", porta))
            self.assertEqual(sock.type, socket.SOCK_DGRAM)
        finally:
            sock.close()

    def test_porta_ocupada_da_erro_claro(self):
        ocupada = abrir_socket("127.0.0.1", 0)
        porta = ocupada.getsockname()[1]
        try:
            with self.assertRaises(ErroPreparacao):
                abrir_socket("127.0.0.1", porta)
        finally:
            ocupada.close()

    def test_pacote_sai_com_a_porta_registrada(self):
        """O host so aceita pacotes vindos da porta registrada no lobby."""
        recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        recv.bind(("127.0.0.1", 0))
        recv.settimeout(2)
        sock = abrir_socket("127.0.0.1", 0)
        try:
            sock.sendto(b"x", recv.getsockname())
            _, origem = recv.recvfrom(10)
            self.assertEqual(origem, sock.getsockname())
        finally:
            sock.close()
            recv.close()


class TestClasseClient(unittest.TestCase):
    CFG = {"peer": {"bind_host": "127.0.0.1"}}

    def test_assinatura_do_main(self):
        """O main chama Client(cfg, match_start, meu_pid)."""
        c = Client(self.CFG, MATCH_START, 1)
        self.assertEqual(c.match_id, "m7")
        self.assertEqual(c.meu_pid, 1)
        self.assertEqual(c.host_addr, ("192.168.0.21", 6001))
        self.assertIsNone(c.ui)
        self.assertIsNone(c.sock)

    def test_aceita_ui_opcional(self):
        ui = object()
        c = Client(self.CFG, MATCH_START, 1, ui=ui)
        self.assertIs(c.ui, ui)

    def test_match_start_ruim_falha_na_criacao(self):
        with self.assertRaises(ErroPreparacao):
            Client(self.CFG, MATCH_START, 0)   # slot 0 e o host

    def test_abrir_usa_a_porta_registrada_e_bind_host_da_config(self):
        porta = porta_livre()
        ms = com(lambda m: m["players"][1].update(host="127.0.0.1", port=porta))
        c = Client(self.CFG, ms, 1)
        try:
            c.abrir()
            self.assertEqual(c.sock.getsockname(), ("127.0.0.1", porta))
        finally:
            c.fechar()
        self.assertIsNone(c.sock)

    def test_run_existe_e_o_main_pode_chama_lo(self):
        """O main faz Client(cfg, match_start, meu_pid).run(); o run() completo
        e testado a fundo em test_client_parte7."""
        self.assertTrue(callable(Client(self.CFG, MATCH_START, 1).run))


if __name__ == "__main__":
    unittest.main()
