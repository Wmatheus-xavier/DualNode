import json
from peer.host import Host, configurar_log

configurar_log()
MS = {"match_id": "m1", "host_slot": 0,
      "config": {"width": 40, "height": 20, "tick_ms": 100},
      "players": [{"slot": 0, "name": "Alice", "host": "127.0.0.1", "port": 6001},
                  {"slot": 1, "name": "Bob",   "host": "127.0.0.1", "port": 6002},
                  {"slot": 2, "name": "Carol", "host": "127.0.0.1", "port": 6003}]}


class SockFalso:
    def __init__(self):
        self.enviados = []

    def sendto(self, dados, addr):
        self.enviados.append((json.loads(dados), addr, len(dados)))


def novo_host():
    h = Host({}, MS)
    h.sock = SockFalso()
    h.jog[1]["presente"] = True
    return h


def inp(**c):
    base = {"v": 1, "t": "INPUT", "m": "m1", "pid": 1, "iseq": 1, "dir": "U", "ack": 0}
    base.update(c)
    return base


# --- _tratar_input -----------------------------------------------------------
h = novo_host()
j = h.jog[1]
h._tratar_input(1, inp())
assert j["iseq"] == 1 and j["dir"] == "U"
h._tratar_input(1, inp(iseq=1, dir="D")); assert j["dir"] == "U"      # repetido
h._tratar_input(1, inp(iseq=0, dir="D")); assert j["dir"] == "U"      # atrasado
h._tratar_input(1, inp(iseq=2, dir="X")); assert j["iseq"] == 1       # direção inválida
h._tratar_input(1, inp(iseq="3"));        assert j["iseq"] == 1       # tipo errado
h._tratar_input(1, inp(iseq=True));       assert j["iseq"] == 1       # bool não vale
h._tratar_input(1, inp(iseq=3, dir="L", ack=5))
assert j["iseq"] == 3 and j["dir"] == "L" and j["ack"] == 0           # ack não passa do histórico
h.historico = [{"n": i} for i in range(1, 11)]
h._tratar_input(1, inp(iseq=4, ack=5)); assert j["ack"] == 5
h._tratar_input(1, inp(iseq=5, ack=2)); assert j["ack"] == 5          # ack não retrocede
j["conectado"] = False
h._tratar_input(1, inp(iseq=6, dir="R")); assert j["dir"] == "U"      # desconectado é ignorado

# --- _enviar_ticks: janela e tamanho -------------------------------------------
h = novo_host()
h.historico = [{"n": i, "mv": [[0, i, 5]], "el": [], "end": None} for i in range(1, 21)]
h.jog[1]["ack"] = 3
h.jog[2]["conectado"] = False
h._enviar_ticks()
assert len(h.sock.enviados) == 1                                       # pid 2 não recebe
msg, addr, tam = h.sock.enviados[0]
assert addr == ("127.0.0.1", 6002)
assert [r["n"] for r in msg["recs"]] == list(range(4, 12))             # ack+1 ... ack+8

h = novo_host()
h.historico = [{"n": i, "mv": [], "el": [], "end": "x" * 300} for i in range(1, 21)]
h._enviar_ticks()
msg, addr, tam = h.sock.enviados[0]
assert tam <= 1200 and msg["recs"][0]["n"] == 1                        # cortou o fim, não o começo
print("registros que couberam:", len(msg["recs"]), "em", tam, "bytes")

# --- _executar_ciclo com o step ----------------------------------------------
h = novo_host()
fim = None
while fim is None:
    fim = h._executar_ciclo()
print("ciclos:", len(h.historico), "fim:", fim)
print("ok")