# HOST de teste (passos 4 e 5): roda handshake + countdown e imprime o resultado.
# Mude o prazo abaixo se precisar (8000 = 8 s).
from peer.host import Host, configurar_log

PRAZO_HELLO_MS = 8000

configurar_log()
MS = {"match_id": "m1", "host_slot": 0,
      "config": {"width": 40, "height": 20, "tick_ms": 100},
      "players": [
          {"slot": 0, "name": "Alice", "host": "127.0.0.1", "port": 6001},
          {"slot": 1, "name": "Bob",   "host": "127.0.0.1", "port": 6002},
          {"slot": 2, "name": "Carol", "host": "127.0.0.1", "port": 6003},
      ]}
print("host: aguardando HELLOs...")
print("resultado:", Host({"timeouts": {"hello_deadline_ms": PRAZO_HELLO_MS}}, MS).run())