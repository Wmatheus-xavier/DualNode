# PASSO 8: fim confiável (sem rede, com um socket falso que "responde" como peers).
# uso: python3 -m testes_manuais.teste_passo8
import json
import time

from peer.host import Host, configurar_log

configurar_log()
MS = {"match_id": "m1", "host_slot": 0,
      "config": {"width": 40, "height": 20, "tick_ms": 20},          # 20 ms: teste rápido
      "players": [{"slot": 0, "name": "Alice", "host": "127.0.0.1", "port": 6001},
                  {"slot": 1, "name": "Bob",   "host": "127.0.0.1", "port": 6002},
                  {"slot": 2, "name": "Carol", "host": "127.0.0.1", "port": 6003}]}
B, C = ("127.0.0.1", 6002), ("127.0.0.1", 6003)
PID = {B: 1, C: 2}
N_FINAL = 10


class SockFalso:
    """Registra o que o host envia e, depois de cada TICK, 'responde' com um INPUT
    cujo ack vem de uma lista (regras[addr][i] = ack enviado após o (i+1)-ésimo TICK)."""

    def __init__(self, regras=None):
        self.enviados, self.entrada, self.contagem = [], [], {}
        self.iseq = {1: 0, 2: 0}
        self.regras = regras or {}

    def sendto(self, dados, addr):
        msg = json.loads(dados)
        self.enviados.append((msg, addr))
        if msg["t"] != "TICK":
            return
        i = self.contagem[addr] = self.contagem.get(addr, 0) + 1
        acks = self.regras.get(addr, [])
        if i <= len(acks):
            pid = PID[addr]
            self.iseq[pid] += 1
            inp = {"v": 1, "t": "INPUT", "m": "m1", "pid": pid,
                   "iseq": self.iseq[pid], "dir": "R", "ack": acks[i - 1]}
            self.entrada.append((json.dumps(inp).encode(), addr))

    def recvfrom(self, n):
        if self.entrada:
            return self.entrada.pop(0)
        raise BlockingIOError

    def ticks(self, addr):
        return [m for m, a in self.enviados if a == addr and m["t"] == "TICK"]


def novo_host(regras=None, timeout_ms=300, ack_inicial=0):
    h = Host({"timeouts": {"peer_timeout_ms": timeout_ms}}, MS)
    h.sock = SockFalso(regras)
    agora = time.monotonic()
    for j in h.jog.values():
        j["presente"], j["visto"], j["ack"] = True, agora, ack_inicial
    h.historico = [{"n": i, "mv": [], "el": [], "end": None} for i in range(1, N_FINAL + 1)]
    h.historico[-1]["end"] = {"result": "WIN", "winner": 0}
    h.estado = "ENDING"
    return h


# A) todos confirmam; peer atrasado recebe a janela certa; confirmado deixa de receber TICK
h = novo_host(regras={B: [10], C: [5, 8, 10]})
t0 = time.monotonic()
h._fase_ending()
assert h.estado == "FINISHED"
assert time.monotonic() - t0 < 0.25                           # saiu quando confirmaram, sem esperar o timeout
assert len(h.sock.ticks(B)) == 1                              # confirmou no 1º TICK: nada mais é enviado a ele
tc = h.sock.ticks(C)
assert len(tc) == 3
assert [r["n"] for r in tc[0]["recs"]] == list(range(1, 9))   # ack 0 -> ciclos 1..8
assert [r["n"] for r in tc[1]["recs"]] == [6, 7, 8, 9, 10]    # ack 5 -> 6..10 (inclui o fim)
assert tc[1]["recs"][-1]["end"] is not None
assert [r["n"] for r in tc[2]["recs"]] == [9, 10]             # ack 8 -> 9..10
print("A ok: janela e confirmação")

# B) um peer nunca confirma: o host desiste no timeout (não trava)
h = novo_host(regras={B: [10]}, timeout_ms=200)
t0 = time.monotonic()
h._fase_ending()
dur = time.monotonic() - t0
assert 0.19 <= dur < 0.5, dur
assert h.estado == "FINISHED"
assert len(h.sock.ticks(C)) >= 5                              # insistiu até o fim do prazo
print("B ok: desistiu após %.0f ms" % (dur * 1000))

# C) peer já dado como caído (DISC) não é esperado
h = novo_host(regras={C: [10]})
h.jog[1]["conectado"] = False
h._fase_ending()
assert h.sock.ticks(B) == []                                  # nada enviado a quem caiu
assert len(h.sock.ticks(C)) == 1
print("C ok: DISC não é aguardado")

# D) todos já tinham confirmado: sai na hora, sem enviar nada
h = novo_host(ack_inicial=N_FINAL)
t0 = time.monotonic()
h._fase_ending()
assert time.monotonic() - t0 < 0.05 and h.sock.enviados == []
print("D ok: sem pendências")

# E) nenhum peer conectado: sai na hora
h = novo_host()
h.jog[1]["conectado"] = h.jog[2]["conectado"] = False
h._fase_ending()
assert h.sock.enviados == [] and h.estado == "FINISHED"
print("E ok: ninguém para esperar")

# F) INPUT de peer eliminado no jogo (mas conectado) também conta como confirmação
h = novo_host(regras={B: [10], C: [10]})
h.jogo["alive"][2] = False                                    # Carol morreu no jogo, segue assistindo
h._fase_ending()
assert len(h.sock.ticks(C)) == 1
print("F ok: espectador também confirma")
print("ok")