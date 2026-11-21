# HOST de teste (passo 8): igual ao teste_host7, mas mede quanto tempo o host levou.
# uso: python3 -m testes_manuais.teste_host8
import time

from peer.host import Host, configurar_log

configurar_log()
MS = {"match_id": "m1", "host_slot": 0,
      "config": {"width": 40, "height": 20, "tick_ms": 100},
      "players": [{"slot": 0, "name": "Alice", "host": "127.0.0.1", "port": 6001},
                  {"slot": 1, "name": "Bob",   "host": "127.0.0.1", "port": 6002},
                  {"slot": 2, "name": "Carol", "host": "127.0.0.1", "port": 6003}]}
CONFIG = {"timeouts": {"hello_deadline_ms": 8000, "peer_timeout_ms": 800}}
print("host: aguardando HELLOs (peer_timeout = 800 ms)...")
t0 = time.monotonic()
resultado = Host(CONFIG, MS).run()
print("resultado:", resultado)
print("host terminou %.1f s depois de ser iniciado" % (time.monotonic() - t0))