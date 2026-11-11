# PASSO 3: validação de datagramas (sem rede). Rode e confira logs/host.log.
import json
from peer.host import Host, configurar_log

configurar_log()
MS = {"match_id": "m1", "host_slot": 0,
      "config": {"width": 40, "height": 20, "tick_ms": 100},
      "players": [
          {"slot": 0, "name": "Alice", "host": "127.0.0.1", "port": 6001},
          {"slot": 1, "name": "Bob",   "host": "127.0.0.1", "port": 6002},
          {"slot": 2, "name": "Carol", "host": "127.0.0.1", "port": 6003},
      ]}
h = Host({}, MS)
BOB = ("127.0.0.1", 6002)


def m(**campos):
    base = {"v": 1, "t": "HELLO", "m": "m1", "pid": 1}
    base.update(campos)
    return json.dumps(base).encode()


assert h._validar(m(), BOB)[0] == 1                          # válido
assert h._validar(b"lixo", BOB) is None                      # JSON inválido
assert h._validar(m(v=2), BOB) is None                       # versão errada
assert h._validar(m(m="outra"), BOB) is None                 # outra partida
assert h._validar(m(pid=2), BOB) is None                     # Bob se passando pela Carol
assert h._validar(m(pid=0), BOB) is None                     # tentando ser o host
assert h._validar(m(), ("127.0.0.1", 9999)) is None          # origem desconhecida
assert h._validar(m(), ("10.0.0.5", 6002)) is None           # IP errado, porta certa
assert h._validar(m(t="TICK"), BOB) is None                  # peer não manda TICK
assert h._validar(b"x" * 1300, BOB) is None                  # grande demais
h.estado = "RUNNING"
assert h._validar(m(), BOB) is None                          # HELLO fora de estado
assert h._validar(m(t="INPUT"), BOB)[0] == 1                 # INPUT em RUNNING pode
print("ok")