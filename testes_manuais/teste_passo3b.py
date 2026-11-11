# PASSO 3 com socket de verdade. Deixe rodando e mande mensagens de outro terminal.
import time
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
h._abrir_socket()
print("escutando na porta 6001 (Ctrl+C para sair)")
try:
    while True:
        for dados, addr in h._receber_tudo():
            h._tratar_datagrama(dados, addr)
        time.sleep(0.05)
except KeyboardInterrupt:
    pass

# Terminal 2: tail -f logs/host.log
# Terminal 3 (um de cada vez):
#   echo '{"v":1,"t":"HELLO","m":"m1","pid":1}' | nc -u -p 6002 -w1 127.0.0.1 6001
#       -> "HELLO de pid 1: respondendo WELCOME" (e o nc imprime o WELCOME)
#   echo '{"v":1,"t":"HELLO","m":"m1","pid":1}' | nc -u -w1 127.0.0.1 6001
#       -> "origem desconhecida"
#   echo 'isso nao e json' | nc -u -p 6002 -w1 127.0.0.1 6001
#       -> "mensagem inválida"
#   echo '{"v":1,"t":"HELLO","m":"m1","pid":2}' | nc -u -p 6002 -w1 127.0.0.1 6001
#       -> "pid 2 veio do endereço do pid 1"