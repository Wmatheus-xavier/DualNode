# PASSO 10: saídas do host (Q, Ctrl+C, ABORT) em todas as fases. Sem rede e sem terminal.
# uso: python3 -m testes_manuais.teste_passo10
import json
import socket
import time

import peer.host as ph
from peer.host import Host, configurar_log

configurar_log()
MS = {"match_id": "m1", "host_slot": 0,
      "config": {"width": 40, "height": 20, "tick_ms": 20},
      "players": [{"slot": 0, "name": "Alice", "host": "127.0.0.1", "port": 6001},
                  {"slot": 1, "name": "Bob",   "host": "127.0.0.1", "port": 6002},
                  {"slot": 2, "name": "Carol", "host": "127.0.0.1", "port": 6003}]}


class SockFalso:
    def __init__(self):
        self.enviados, self.fechado = [], False

    def sendto(self, dados, addr):
        self.enviados.append((json.loads(dados), addr))

    def recvfrom(self, n):
        raise BlockingIOError

    def close(self):
        self.fechado = True

    def abortos(self):
        return [(m, a) for m, a in self.enviados if m["t"] == "ABORT"]


class UIFalsa:
    def __init__(self, teclas=()):
        self.teclas, self.status = list(teclas), []

    def poll_input(self):
        return self.teclas.pop(0) if self.teclas else None

    def draw(self, view):
        self.status.append(view.status)


def novo_host(teclas=(), presentes=True, timeout_ms=5000):
    h = Host({"timeouts": {"peer_timeout_ms": timeout_ms, "hello_deadline_ms": 10000}}, MS,
             ui=UIFalsa(teclas))
    h.sock = SockFalso()
    h._abrir_socket = lambda: None
    agora = time.monotonic()
    for j in h.jog.values():
        j["presente"], j["visto"] = presentes, agora
    return h


B, C = ("127.0.0.1", 6002), ("127.0.0.1", 6003)

# 1) _abortar: 3 ABORT para cada peer CONECTADO, nenhum para quem caiu; tela avisa
h = novo_host()
h.jog[2]["conectado"] = False
h._abortar("teste", intervalo_s=0.01)
ab = h.sock.abortos()
assert h.estado == "ABORTED" and h.motivo_abort == "teste"
assert [a for _, a in ab].count(B) == 3 and [a for _, a in ab].count(C) == 0, ab
assert all(m["reason"] == "teste" and m["m"] == "m1" and m["pid"] == 0 for m, _ in ab)
assert "teste" in h.ui.status[-1] and "tecla" in h.ui.status[-1]
print("1 ok: ABORT só para peers conectados, 3 vezes")

# 2) Q enquanto espera os HELLO: sai na hora e avisa quem já estava na sala
h = novo_host(teclas=[None, "QUIT"], presentes=False)
t0 = time.monotonic()
r = h.run()
assert r == {"result": "ABORT", "winner": None} and time.monotonic() - t0 < 1.0
assert len(h.sock.abortos()) == 6                        # 3 x 2 peers (ainda sem HELLO, mas conectados)
assert h.sock.fechado
print("2 ok: Q em COLLECTING")

# 3) Q durante a contagem regressiva
ph.COUNTDOWN_MS = 3000
h = novo_host(teclas=[None, None, "QUIT"])
t0 = time.monotonic()
r = h.run()
assert r["result"] == "ABORT" and time.monotonic() - t0 < 1.0 and len(h.sock.abortos()) == 6
assert h.estado == "ABORTED" and h.historico == []
print("3 ok: Q em COUNTDOWN")

# 4) Q durante o jogo
h = novo_host(teclas=["QUIT"])
h._fase_collecting = lambda: (setattr(h, "estado", "COUNTDOWN") or True)
h._fase_countdown = lambda: (setattr(h, "estado", "RUNNING") or time.monotonic() + 10)
r = h.run()
assert r["result"] == "ABORT" and len(h.sock.abortos()) == 6 and h.historico == []
print("4 ok: Q em RUNNING")

# 5) Q na fase ENDING: não é ABORT (o jogo acabou); só para de esperar as confirmações
h = novo_host(teclas=[None, "QUIT"])
h.estado = "ENDING"
h.historico = [{"n": 1, "mv": [], "el": [], "end": {"result": "WIN", "winner": 0}}]
t0 = time.monotonic()
h._fase_ending()
assert time.monotonic() - t0 < 1.0 and h.sock.abortos() == [] and h.estado == "FINISHED"
print("5 ok: Q em ENDING não vira ABORT")

# 6) Ctrl+C em cada fase antes do fim: vira ABORT e avisa os peers
def interrompe(*a, **k):
    raise KeyboardInterrupt


for fase in ("COLLECTING", "COUNTDOWN", "RUNNING"):
    h = novo_host()
    h.estado = fase
    h._fase_collecting = interrompe
    r = h.run()
    ab = h.sock.abortos()
    assert r == {"result": "ABORT", "winner": None}, (fase, r)
    assert len(ab) == 6 and "Ctrl+C" in ab[0][0]["reason"], (fase, len(ab))
    assert h.sock.fechado
print("6 ok: Ctrl+C vira ABORT")

# 7) Ctrl+C depois do fim da partida: devolve o resultado REAL, sem ABORT
h = novo_host()
h._fase_collecting = lambda: True
h._fase_countdown = lambda: 0.0
h._fase_rodando = lambda p: {"result": "WIN", "winner": 2}
h._fase_ending = interrompe
r = h.run()
assert r == {"result": "WIN", "winner": 2} and h.sock.abortos() == [], r
print("7 ok: Ctrl+C em ENDING preserva o resultado")

# 8) 'jogadores insuficientes' manda o ABORT uma vez só (não repete em run)
h = novo_host(presentes=False)
h.hello_deadline_s = 0.05
r = h.run()
assert r["result"] == "ABORT" and h.motivo_abort == "jogadores insuficientes"
assert h.sock.abortos() == []                            # ninguém se apresentou: não há quem avisar
print("8 ok: sem jogadores")

# 9) abort duplicado: se já está ABORTED, não reenvia
h = novo_host()
h._abortar("x", intervalo_s=0.0)
n = len(h.sock.abortos())
h._abortado()
assert len(h.sock.abortos()) == n
print("9 ok: ABORT enviado uma vez só")

# 10) porta ocupada: erro claro (e o socket não vaza)
ocupa = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
ocupa.bind(("127.0.0.1", 6001))
h = Host({"peer": {"bind_host": "127.0.0.1"}}, MS)
try:
    Host._abrir_socket(h)
    raise AssertionError("deveria ter falhado")
except OSError:
    pass
finally:
    ocupa.close()
print("10 ok: porta ocupada")

# 11) o resumo final não quebra em nenhum estado
h = novo_host()
h._resumo()
print("11 ok: resumo")
print("ok")