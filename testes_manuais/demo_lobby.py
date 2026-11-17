# testes_manuais/demo_lobby.py
# Roda os cenários do lobby contra um lobby JÁ LIGADO e mostra o que foi
# enviado (->) e recebido (<-). Serve para os prints e logs do relatório.
#
# Terminal 1:  python3 -m lobby.server --port 5000
# Terminal 2:  python3 -m testes_manuais.demo_lobby            (ou --port 5000 --host 127.0.0.1)
import argparse
import json
import socket
import time

from common import protocol as p

ap = argparse.ArgumentParser()
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--port", type=int, default=5000)
args = ap.parse_args()


class Jogador:
    def __init__(self, nome):
        self.nome = nome
        self.sock = socket.create_connection((args.host, args.port), timeout=2)
        self.buf = p.LineBuffer()

    def manda(self, msg, rotulo=None):
        dados = msg if isinstance(msg, bytes) else p.encode_line(msg)
        texto = rotulo or dados.decode(errors="replace").strip()
        print("  %-5s -> %s" % (self.nome, texto))
        self.sock.sendall(dados)

    def recebe(self, espera=0.4):
        time.sleep(espera)
        self.sock.settimeout(0.3)
        try:
            dados = self.sock.recv(65536)
        except socket.timeout:
            print("  %-5s <- (nada)" % self.nome)
            return []
        except ConnectionError:
            dados = b""
        if not dados:
            print("  %-5s <- [conexão fechada pelo lobby]" % self.nome)
            return []
        msgs = [m for m in self.buf.feed(dados) if m and m["t"] != "PING"]
        for m in msgs:
            print("  %-5s <- %s" % (self.nome, json.dumps(m, ensure_ascii=False)))
        return msgs

    def match_id(self):
        """Recebe e devolve o match_id do MATCH_CREATED."""
        return next(m["match_id"] for m in self.recebe() if m["t"] == "MATCH_CREATED")

    def fecha(self):
        self.sock.close()


def titulo(texto):
    print("\n" + "=" * 70 + "\n" + texto + "\n" + "=" * 70)


titulo("1. Enquadramento: duas mensagens no mesmo envio")
a = Jogador("Ana")
a.manda(p.encode_line(p.register("Ana", 6001)) + p.encode_line(p.list_matches()),
        '{"t":"REGISTER",...}\\n{"t":"LIST_MATCHES"}\\n   (um único sendall)')
a.recebe()
a.fecha()

titulo("2. Enquadramento: uma mensagem partida em dois envios")
a = Jogador("Ana")
linha = p.encode_line(p.register("Ana", 6001))
a.manda(linha[:20], "primeira metade: %s" % linha[:20].decode())
a.recebe()
a.manda(linha[20:], "segunda metade:  %s" % linha[20:].decode().strip())
a.recebe()
a.fecha()

titulo("3. Mensagens inválidas (cenário 7, lado TCP)")
x = Jogador("X")
x.manda(b"isso nao e json\n")
x.recebe()
x.manda(b'{"v":1,"t":"DANCAR"}\n')
x.recebe()
x.manda(b'{"v":1,"t":"REGISTER","name":"Ana"}\n', '{"v":1,"t":"REGISTER","name":"Ana"}   (falta udp_port)')
x.recebe()
x.manda(p.list_matches(), '{"v":1,"t":"LIST_MATCHES"}   (antes de registrar)')
x.recebe()
x.manda(p.register("nome com espaco", 6001))
x.recebe()
x.manda(p.register("Ana", 80))
x.recebe()
x.manda(p.register("Ana", 6001, "localhost"))
x.recebe()
x.fecha()
x = Jogador("X")
for _ in range(3):
    x.manda(b"lixo\n")
x.recebe()
x = Jogador("X")
x.manda(b"A" * 5000, "5000 bytes sem \\n")
x.recebe()

titulo("4. Nome repetido (cenário 9)")
a = Jogador("Ana")
a.manda(p.register("Ana", 6001))
a.recebe()
b = Jogador("Ana2")
b.manda(p.register("Ana", 6002))
b.recebe()
a.fecha()
b.fecha()

titulo("5. Sala cheia (cenário 9)")
ana, bob, cid, dan = (Jogador(n) for n in ("Ana", "Bob", "Cid", "Dan"))
for j, porta in ((ana, 6001), (bob, 6002), (cid, 6003), (dan, 6004)):
    j.manda(p.register(j.nome, porta))
    j.recebe(0.2)
ana.manda(p.create_match("sala3", 3))
mid = ana.match_id()
bob.manda(p.list_matches())
bob.recebe()
bob.manda(p.join_match(mid))
bob.recebe()
ana.recebe(0.1)
cid.manda(p.join_match(mid))
cid.recebe()
ana.recebe(0.1)
bob.recebe(0.1)
dan.manda(p.join_match(mid))
dan.recebe()

titulo("6. Regras do início: NOT_CREATOR e início com MATCH_START")
bob.manda(p.start_match())
bob.recebe()
ana.manda(p.start_match())
for j in (ana, bob, cid):
    j.recebe(0.2)
dan.manda(p.join_match(mid), '{"t":"JOIN_MATCH","match_id":"%s"}   (sala já iniciada)' % mid)
dan.recebe()
ana.manda(p.match_end(1), '{"t":"MATCH_END","winner":1}   (host avisa o fim)')
ana.recebe()
bob.manda(p.list_matches(), '{"t":"LIST_MATCHES"}   (Bob volta ao menu depois da partida)')
bob.recebe()
for j in (ana, bob, cid, dan):
    j.fecha()

titulo("7. Sala cancelada: o criador sai (cenário 9)")
ana, bob, cid = (Jogador(n) for n in ("Ana", "Bob", "Cid"))
for j, porta in ((ana, 6001), (bob, 6002), (cid, 6003)):
    j.manda(p.register(j.nome, porta))
    j.recebe(0.2)
ana.manda(p.create_match("sala4", 4))
mid = ana.match_id()
bob.manda(p.join_match(mid))
bob.recebe()
ana.recebe(0.1)
cid.manda(p.join_match(mid))
cid.recebe()
ana.recebe(0.1)
bob.recebe(0.1)
cid.manda(p.leave_match())
ana.recebe()
bob.recebe(0.1)
ana.manda(p.leave_match(), '{"t":"LEAVE_MATCH"}   (o criador sai)')
bob.recebe()
cid.fecha()

titulo("8. Jogador cai sem avisar (desconexão TCP)")
cid = Jogador("Cid")
cid.manda(p.register("Cid", 6003))
cid.recebe(0.2)
bob.manda(p.create_match("sala5", 3))
mid = bob.match_id()
cid.manda(p.join_match(mid))
cid.recebe()
bob.recebe(0.1)
print("  Cid   -- fecha o programa (socket fechado)")
cid.fecha()
bob.recebe()
for j in (ana, bob):
    j.fecha()

print("\nFim. Veja também logs/lobby.log na pasta do lobby.")
