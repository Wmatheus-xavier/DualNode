# HOST de teste (passo 11): partida com REDE RUIM simulada no lado do host (nos dois sentidos).
# uso: python3 -m testes_manuais.teste_host11 [perda 0-1] [atraso_ms] [jitter_ms] [peer_timeout_ms]
#   ex.: python3 -m testes_manuais.teste_host11 0.2            -> 20% de perda
#        python3 -m testes_manuais.teste_host11 0.2 80 40      -> 20% de perda, 80 ms +/- 40 ms
# Suba os peers antes (teste_peer9 1 6002 e teste_peer9 2 6003).
import sys
import time

from peer.host import Host, configurar_log

perda = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
atraso = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
jitter = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
timeout = int(sys.argv[4]) if len(sys.argv) > 4 else 3000

configurar_log()
MS = {"match_id": "m1", "host_slot": 0,
      "config": {"width": 40, "height": 20, "tick_ms": 100},
      "players": [{"slot": 0, "name": "Alice", "host": "127.0.0.1", "port": 6001},
                  {"slot": 1, "name": "Bob",   "host": "127.0.0.1", "port": 6002},
                  {"slot": 2, "name": "Carol", "host": "127.0.0.1", "port": 6003}]}
CONFIG = {"timeouts": {"hello_deadline_ms": 10000, "peer_timeout_ms": timeout},
          "sim": {"loss": perda, "delay_ms": atraso, "jitter_ms": jitter, "seed": 7}}
print("host: perda=%.0f%% atraso=%.0f ms jitter=%.0f ms peer_timeout=%d ms"
      % (perda * 100, atraso, jitter, timeout))
t0 = time.monotonic()
print("resultado:", Host(CONFIG, MS).run())
print("duração: %.1f s" % (time.monotonic() - t0))