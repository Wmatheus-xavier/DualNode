# PASSO 7: timeout de peer (sem rede). Rode da raiz:  python3 -m testes_manuais.teste_passo7
import json
import time

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
        self.enviados.append((json.loads(dados), addr))


def novo_host(timeout_ms=500):
    h = Host({"timeouts": {"peer_timeout_ms": timeout_ms}}, MS)
    h.sock = SockFalso()
    agora = time.monotonic()
    for j in h.jog.values():
        j["presente"], j["visto"] = True, agora
    return h


def inp(pid, iseq, d="R"):
    return {"v": 1, "t": "INPUT", "m": "m1", "pid": pid, "iseq": iseq, "dir": d, "ack": 0}


# 1) peer com sinal de vida recente NÃO é eliminado
h = novo_host()
h._verificar_timeouts()
assert h.a_eliminar == set()
assert all(j["conectado"] for j in h.jog.values())

# 2) peer em silêncio por mais que o timeout vira DISC, UMA vez só
h = novo_host()
h.jog[1]["visto"] = time.monotonic() - 2
h._verificar_timeouts()
h._verificar_timeouts()
h._verificar_timeouts()
assert h.a_eliminar == {1}
assert h.jog[1]["conectado"] is False and h.jog[2]["conectado"] is True

# 3) o ciclo aplica o DISC e a moto some do jogo, mas o rastro fica
cells_antes = dict(h.jogo["cells"])
fim = h._executar_ciclo()
reg = h.historico[0]
assert [1, "DISC"] in reg["el"], reg
assert h.jogo["alive"][1] is False
assert all(c in h.jogo["cells"] for c in cells_antes)          # rastro permanece
assert all(m[0] != 1 for m in reg["mv"])                        # eliminada não avança
assert h.a_eliminar == set()
assert fim is None                                              # 0 e 2 seguem vivos

# 4) depois do DISC o host para de mandar TICK para ele; o outro peer continua recebendo
h.sock.enviados.clear()
h._executar_ciclo()
destinos = [addr for _, addr in h.sock.enviados]
assert ("127.0.0.1", 6002) not in destinos
assert ("127.0.0.1", 6003) in destinos
assert len([r for r in h.historico if [1, "DISC"] in r["el"]]) == 1   # DISC aparece uma vez

# 5) INPUT que chega depois do DISC é ignorado (não ressuscita)
h._tratar_input(1, inp(1, 99, "U"))
assert h.jog[1]["iseq"] == 0 and h.jog[1]["dir"] is None and h.jog[1]["conectado"] is False

# 6) peer que já morreu NO JOGO e depois some: não gera um DISC "fantasma"
h = novo_host()
h.jogo["alive"][2] = False
h.jog[2]["visto"] = time.monotonic() - 2
h._executar_ciclo()
assert [2, "DISC"] not in h.historico[0]["el"]
assert h.jog[2]["conectado"] is False

# 7) sobrando só o host: ele vence
h = novo_host()
h.jog[1]["visto"] = h.jog[2]["visto"] = time.monotonic() - 2
fim = h._executar_ciclo()
assert sorted(h.historico[0]["el"]) == [[1, "DISC"], [2, "DISC"]]
assert fim == {"result": "WIN", "winner": 0}, fim

# 8) peer ausente desde o início (nunca mandou HELLO) não é tratado pelo timeout
h = novo_host()
h.jog[2]["presente"] = False
h.jog[2]["conectado"] = False
h.jog[2]["visto"] = None
h.a_eliminar = {2}                       # run() faz isso com os ausentes
h._verificar_timeouts()
h._executar_ciclo()
assert [2, "DISC"] in h.historico[0]["el"]
print("ok")