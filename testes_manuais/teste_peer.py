# PEER de teste (passo 4): reenvia o HELLO até receber o WELCOME.
# uso: python3 teste_peer.py <pid> <porta>      ex.: python3 teste_peer.py 1 6002
import json
import socket
import sys

pid, porta = int(sys.argv[1]), int(sys.argv[2])
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("127.0.0.1", porta))          # porta de origem fixa = a anunciada
s.settimeout(0.5)
hello = json.dumps({"v": 1, "t": "HELLO", "m": "m1", "pid": pid}).encode()

for tentativa in range(1, 121):       # ~60 s
    s.sendto(hello, ("127.0.0.1", 6001))
    try:
        dados, _ = s.recvfrom(2048)
        print("recebi:", dados.decode())
        break
    except socket.timeout:
        print("sem resposta, reenviando (tentativa %d)" % tentativa)