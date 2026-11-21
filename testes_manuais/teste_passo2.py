# PASSO 2: tabela de jogadores e validação por endereço (sem rede).
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

print("nomes:", h.nomes)
print("peers:", sorted(h.jog))
assert sorted(h.jog) == [1, 2]                         # o host (0) não está
assert h.nomes == {0: "Alice", 1: "Bob", 2: "Carol"}
assert h._pid_da_origem(("127.0.0.1", 6002)) == 1
assert h._pid_da_origem(("127.0.0.1", 6003)) == 2
assert h._pid_da_origem(("127.0.0.1", 9999)) is None   # desconhecido
assert h._pid_da_origem(("10.0.0.5", 6002)) is None    # IP errado, porta certa
print("ok")