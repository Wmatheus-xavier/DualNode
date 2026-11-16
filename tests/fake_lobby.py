# Servidor de lobby de mentira: aceita 1 cliente e responde o básico.
import socket
import sys

from common import protocol as p

porta = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", porta))
srv.listen(1)
print("fake lobby em", porta)
conn, addr = srv.accept()
buf = p.LineBuffer()
while True:
    dados = conn.recv(4096)
    if not dados:
        break
    for msg in buf.feed(dados):
        print("recebi:", msg)
        if msg is None:
            continue
        t = msg["t"]
        if t == "REGISTER":
            conn.sendall(p.encode_line(p.register_ok(1)))
        elif t == "CREATE_MATCH":
            conn.sendall(p.encode_line(p.match_created("m1", 0)))
        elif t == "LIST_MATCHES":
            lista = [{"match_id": "m1", "name": "sala", "host_name": "Ana",
                      "players": 1, "max_players": 3}]
            conn.sendall(p.encode_line(p.match_list(lista)))
        elif t == "JOIN_MATCH":
            conn.sendall(p.encode_line(p.join_ok("m1", 1, [{"slot": 0, "name": "Ana"}])))
            conn.sendall(p.encode_line(p.player_joined(2, "Bob")))
        elif t == "START_MATCH":
            conn.sendall(p.encode_line(p.match_start(
                "m1", 0, {"width": 40, "height": 20, "tick_ms": 100},
                [{"slot": 0, "name": "Ana", "host": "127.0.0.1", "port": 6001}])))