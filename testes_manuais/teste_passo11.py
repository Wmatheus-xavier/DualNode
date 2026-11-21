# PASSO 11: o simulador de rede (common/simnet.py) e a ligação com o host. Sem terminal.
# uso: python3 -m testes_manuais.teste_passo11
import socket
import time

from common.simnet import SimSocket
from peer.host import Host, configurar_log

configurar_log()


def par():
    """Devolve (receptor não bloqueante, endereço dele, emissor comum)."""
    r = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    r.bind(("127.0.0.1", 0))
    r.setblocking(False)
    e = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return r, r.getsockname(), e


def coletar(sock, esperar_s=0.5, minimo=None):
    """Chama recvfrom até acabar o tempo (ou chegar 'minimo' datagramas). Devolve [(instante, dados)]."""
    recebidos, fim = [], time.monotonic() + esperar_s
    while time.monotonic() < fim:
        try:
            dados, _ = sock.recvfrom(2048)
            recebidos.append((time.monotonic(), dados))
            if minimo and len(recebidos) >= minimo:
                break
        except BlockingIOError:
            time.sleep(0.002)
    return recebidos


# 1) sem perda nem atraso, tudo passa
r, addr, e = par()
sim = SimSocket(r)
for i in range(20):
    e.sendto(b"%d" % i, addr)
got = coletar(sim, 0.5, minimo=20)
assert len(got) == 20 and sim.stats["rx_perdidos"] == 0
print("1 ok: sem perda")

# 2) perda total no recebimento
r, addr, e = par()
sim = SimSocket(r, loss=1.0)
for i in range(20):
    e.sendto(b"x", addr)
assert coletar(sim, 0.3) == []
assert sim.stats["rx"] == 20 and sim.stats["rx_perdidos"] == 20
print("2 ok: perda total (rx)")

# 3) perda de 50%: perto da metade (1000 datagramas, em lotes para o kernel não descartar)
r, addr, e = par()
sim = SimSocket(r, loss=0.5, seed=1)
entregues = 0
for _ in range(10):
    for i in range(100):
        e.sendto(b"x", addr)
    entregues += len(coletar(sim, 0.15))
frac = sim.stats["rx_perdidos"] / sim.stats["rx"]
assert sim.stats["rx"] == 1000 and 0.42 < frac < 0.58, (sim.stats, frac)
assert entregues == sim.stats["rx"] - sim.stats["rx_perdidos"]
print("3 ok: perda de ~50%% (%.1f%%)" % (frac * 100))

# 4) atraso no recebimento
r, addr, e = par()
sim = SimSocket(r, delay_ms=150)
t0 = time.monotonic()
e.sendto(b"x", addr)
got = coletar(sim, 1.0, minimo=1)
dt = got[0][0] - t0
assert 0.14 <= dt < 0.4, dt
print("4 ok: atraso no rx (%.0f ms)" % (dt * 1000))

# 5) atraso no envio
r, addr, _ = par()
emissor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
emissor.bind(("127.0.0.1", 0))
emissor.setblocking(False)
sim = SimSocket(emissor, delay_ms=150)
t0 = time.monotonic()
sim.sendto(b"x", addr)
chegou = None
while time.monotonic() - t0 < 1.0 and chegou is None:
    try:
        sim.recvfrom(2048)                      # é o que "despacha" a fila de saída
    except BlockingIOError:
        pass
    try:
        r.recvfrom(2048)
        chegou = time.monotonic() - t0
    except BlockingIOError:
        time.sleep(0.002)
assert chegou is not None and 0.14 <= chegou < 0.4, chegou
print("5 ok: atraso no tx (%.0f ms)" % (chegou * 1000))

# 6) jitter embaralha a ordem de chegada, mas nada se perde
r, addr, e = par()
sim = SimSocket(r, delay_ms=60, jitter_ms=50, seed=3)
for i in range(50):
    e.sendto(b"%03d" % i, addr)
    time.sleep(0.001)
ordem = [int(d) for _, d in coletar(sim, 0.6, minimo=50)]
assert sorted(ordem) == list(range(50)), len(ordem)
assert ordem != sorted(ordem), "esperava datagramas fora de ordem"
print("6 ok: jitter reordena (%d fora do lugar)" % sum(1 for a, b in zip(ordem, sorted(ordem)) if a != b))

# 7) perda no envio
r, addr, _ = par()
emissor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sim = SimSocket(emissor, loss=1.0)
for i in range(10):
    sim.sendto(b"x", addr)
assert coletar(r, 0.2) == [] and sim.stats["tx"] == 10 and sim.stats["tx_perdidos"] == 10
print("7 ok: perda total (tx)")

# 8) close() entrega o que ainda estava "na rede" (atrasado)
r, addr, _ = par()
emissor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sim = SimSocket(emissor, delay_ms=100)
sim.sendto(b"ultimo", addr)
sim.close()
got = coletar(r, 0.5, minimo=1)
assert got and got[0][1] == b"ultimo"
print("8 ok: close() não engole o último datagrama")

# 9) a mesma semente repete o mesmo padrão de perdas
def perdas(seed):
    s = SimSocket(socket.socket(socket.AF_INET, socket.SOCK_DGRAM), loss=0.5, seed=seed)
    for i in range(200):
        s.sendto(b"x", ("127.0.0.1", 9))
    return s.stats["tx_perdidos"]


assert perdas(5) == perdas(5)
print("9 ok: semente reproduz")

# 10) ligação com o host: config["sim"] embrulha o socket; sem "sim" é o socket normal
MS = {"match_id": "m1", "host_slot": 0,
      "config": {"width": 40, "height": 20, "tick_ms": 100},
      "players": [{"slot": 0, "name": "Alice", "host": "127.0.0.1", "port": 6001},
                  {"slot": 1, "name": "Bob",   "host": "127.0.0.1", "port": 6002},
                  {"slot": 2, "name": "Carol", "host": "127.0.0.1", "port": 6003}]}
h = Host({"peer": {"bind_host": "127.0.0.1"}, "sim": {"loss": 0.1, "seed": 1}}, MS)
h._abrir_socket()
assert isinstance(h.sock, SimSocket) and h.sock.loss == 0.1
h.sock.close()
h = Host({"peer": {"bind_host": "127.0.0.1"}}, MS)
h._abrir_socket()
assert isinstance(h.sock, socket.socket)
h.sock.close()
print("10 ok: ligação com o host")
print("ok")