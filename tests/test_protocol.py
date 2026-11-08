import unittest

from common import protocol as p


class TestUDP(unittest.TestCase):
    def test_roundtrip_validos(self):
        msgs = [
            p.hello("m1", 1),
            p.welcome("m1", {"width": 40}, 3000),
            p.input_msg("m1", 1, 5, "U", 0),
            p.tick("m1", []),
            p.abort("m1", "HOST_QUIT"),
        ]
        for msg in msgs:
            self.assertEqual(p.decode(p.encode(msg)), msg)

    def test_bytes_invalidos(self):
        self.assertIsNone(p.decode(b"\xff\xfe"))

    def test_json_invalido(self):
        self.assertIsNone(p.decode(b"lixo"))

    def test_nao_e_dict(self):
        self.assertIsNone(p.decode(b"[1,2]"))
        self.assertIsNone(p.decode(b"42"))

    def test_versao_errada(self):
        msg = p.hello("m1", 1)
        msg["v"] = 2
        self.assertIsNone(p.decode(p.encode(msg)))

    def test_tipo_desconhecido(self):
        self.assertIsNone(p.decode(b'{"v":1,"t":"XYZ"}'))

    def test_campo_faltando(self):
        msg = p.input_msg("m1", 1, 5, "U", 0)
        del msg["ack"]
        self.assertIsNone(p.decode(p.encode(msg)))

    def test_tipo_errado(self):
        msg = p.hello("m1", "1")
        self.assertIsNone(p.decode(p.encode(msg)))

    def test_bool_nao_vale_como_int(self):
        msg = p.hello("m1", True)
        self.assertIsNone(p.decode(p.encode(msg)))

    def test_dir_invalida(self):
        msg = p.input_msg("m1", 1, 5, "X", 0)
        self.assertIsNone(p.decode(p.encode(msg)))

    def test_datagrama_grande(self):
        self.assertIsNone(p.decode(b"x" * 2000))

    def test_tipo_tcp_nao_vale_no_udp(self):
        self.assertIsNone(p.decode(p.encode(p.ping())))


class TestTCP(unittest.TestCase):
    def test_roundtrip_validos(self):
        msgs = [
            p.register("Ana", 6001),
            p.register("Ana", 6001, "10.0.0.1"),
            p.create_match("sala", 3),
            p.list_matches(),
            p.join_match("m1"),
            p.match_end(None),
            p.match_end(2),
            p.match_start("m1", 0, {"width": 40}, []),
            p.error("BAD_STATE", "x"),
        ]
        for msg in msgs:
            self.assertEqual(p.decode_line(p.encode_line(msg).strip()), msg)

    def test_linha_invalida(self):
        self.assertIsNone(p.decode_line(b"lixo"))
        self.assertIsNone(p.decode_line(b'{"v":1,"t":"HELLO"}'))


class TestLineBuffer(unittest.TestCase):
    def test_mensagem_partida(self):
        lb = p.LineBuffer()
        a = p.encode_line(p.ping())
        self.assertEqual(lb.feed(a[:5]), [])
        self.assertEqual(lb.feed(a[5:]), [p.ping()])

    def test_duas_mensagens_no_mesmo_chunk(self):
        lb = p.LineBuffer()
        a = p.encode_line(p.ping())
        self.assertEqual(lb.feed(a + a), [p.ping(), p.ping()])

    def test_linha_invalida_vira_none(self):
        lb = p.LineBuffer()
        self.assertEqual(lb.feed(b"lixo\n"), [None])

    def test_linha_vazia_ignorada(self):
        lb = p.LineBuffer()
        self.assertEqual(lb.feed(b"\n\n"), [])

    def test_linha_gigante_sem_quebra(self):
        lb = p.LineBuffer()
        with self.assertRaises(p.LineTooLong):
            lb.feed(b"x" * 5000)

    def test_linha_gigante_com_quebra(self):
        lb = p.LineBuffer()
        with self.assertRaises(p.LineTooLong):
            lb.feed(b"x" * 5000 + b"\n")


if __name__ == "__main__":
    unittest.main()