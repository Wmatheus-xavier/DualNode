# PASSO 12: sinal de vida durante a espera dos HELLO (sem rede). Corrige o caso de um peer
# lento: quem já se apresentou não pode desistir (3 s sem TICK) enquanto o host espera os outros.
# uso: python3 -m testes_manuais.teste_passo12
import json
import time

from peer.host import Host, configurar_log

configurar_log()
MS = {"match_id": "m1", "host_slot": 0,
      "config": {"width": 40, "height": 20, "tick_ms": 50},
      "players": [{"slot": 0, "name": "Alice", "host": "127.0.0.1", "port": 6001},
                  {"slot": 1, "name": "Bob",   "host": "127.0.0.1", "port": 6002},
                  {"slot": 2, "name": "Carol", "host": "127.0.0.1", "port": 6003}]}
B, C = ("127.0.0.1", 6002), ("127.0.0.1", 6003)


class SockFalso:
    def __init__(self):
        self.enviados = []

    def sendto(self, dados, addr):
        self.enviados.append((json.loads(dados), addr))

    def recvfrom(self, n):
        raise BlockingIOError

    def close(self):
        pass

    def ticks(self, addr):
        return [m for m, a in self.enviados if a == addr and m["t"] == "TICK"]


def novo_host(deadline_ms):
    h = Host({"timeouts": {"hello_deadline_ms": deadline_ms}}, MS)
    h.sock = SockFalso()
    return h


# 1) Bob se apresentou, Carol não: durante a espera, Bob recebe TICK vazio a cada tick_ms; Carol, nenhum
h = novo_host(deadline_ms=500)
h.jog[1]["presente"] = True
h._fase_collecting()
tb = h.sock.ticks(B)
assert 7 <= len(tb) <= 11, len(tb)                       # ~500 ms / 50 ms
assert all(m["recs"] == [] and m["pid"] == 0 and m["m"] == "m1" for m in tb)
assert h.sock.ticks(C) == []
print("1 ok: %d sinais de vida para quem já entrou, nenhum para quem não entrou" % len(tb))

# 2) o intervalo é ~tick_ms (não uma rajada)
h = novo_host(deadline_ms=400)
h.jog[1]["presente"] = True
instantes = []
orig = h.sock.sendto
h.sock.sendto = lambda d, a: (instantes.append(time.monotonic()), orig(d, a))
h._fase_collecting()
gaps = [(b - a) * 1000 for a, b in zip(instantes, instantes[1:])]
assert gaps and 35 <= sum(gaps) / len(gaps) <= 70, gaps
print("2 ok: intervalo médio %.0f ms" % (sum(gaps) / len(gaps)))

# 3) todos já se apresentaram: sai na hora, sem esperar o prazo
h = novo_host(deadline_ms=5000)
h.jog[1]["presente"] = h.jog[2]["presente"] = True
t0 = time.monotonic()
assert h._fase_collecting() is True and time.monotonic() - t0 < 0.3
print("3 ok: não espera quando todos entraram")

# 4) quem não apareceu até o prazo vira DISC e não recebe sinal de vida depois
h = novo_host(deadline_ms=200)
h.jog[1]["presente"] = True
h._fase_collecting()
assert h.jog[2]["conectado"] is False and 2 in h.desconectados_iniciais
h.sock.enviados.clear()
h._enviar_tick_vazio()                                    # comportamento da contagem regressiva
assert h.sock.ticks(B) and h.sock.ticks(C) == []
print("4 ok: ausente não recebe nada")

# 5) _enviar_tick_vazio() sem argumento continua mandando para todos os conectados (countdown)
h = novo_host(deadline_ms=100)
h._enviar_tick_vazio()
assert len(h.sock.ticks(B)) == 1 and len(h.sock.ticks(C)) == 1
print("5 ok: countdown inalterado")
print("ok")