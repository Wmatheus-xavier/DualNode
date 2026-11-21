# PASSO 1: socket UDP não bloqueante e leitura em lote.
# Deixe rodando e mande datagramas de outro terminal (veja os comandos no fim).
import time
from peer.host import Host, configurar_log

configurar_log()
MS = {"match_id": "m1", "host_slot": 0,
      "config": {"width": 40, "height": 20, "tick_ms": 100},
      "players": [{"slot": 0, "name": "Alice", "host": "127.0.0.1", "port": 6001}]}

h = Host({}, MS)
h._abrir_socket()
print("escutando na porta 6001 (Ctrl+C para sair)")
try:
    while True:
        lote = h._receber_tudo()
        for dados, addr in lote:
            print(addr, dados)
        if lote:
            print("--- lote de", len(lote), "datagrama(s)")
        time.sleep(1)               # de propósito: simula o ciclo, deixa os pacotes acumularem
except KeyboardInterrupt:
    pass

# Terminal 2:
#   for i in 1 2 3; do echo "msg$i" | nc -u -w1 127.0.0.1 6001 & done; wait
# Esperado: "--- lote de 3 datagrama(s)"