# PEER de teste (passo 5): faz o handshake e mede os TICKs do countdown.
# uso: python3 teste_peer5.py <pid> <porta>      ex.: python3 teste_peer5.py 1 6002
import json
import socket
import sys
import time

pid, porta = int(sys.argv[1]), int(sys.argv[2])
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("127.0.0.1", porta))
s.settimeout(0.5)
hello = json.dumps({"v": 1, "t": "HELLO", "m": "m1", "pid": pid}).encode()

for tentativa in range(120):                       # handshake
    s.sendto(hello, ("127.0.0.1", 6001))
    try:
        dados, _ = s.recvfrom(2048)
        if json.loads(dados)["t"] == "WELCOME":
            break
    except socket.timeout:
        print("sem resposta, reenviando (tentativa %d)" % (tentativa + 1))
print("WELCOME recebido; aguardando TICKs")

n, ultimo, gaps = 0, None, []
s.settimeout(1.0)                                  # 1 s sem TICK = fim do teste
while True:
    try:
        dados, _ = s.recvfrom(2048)
    except socket.timeout:
        break
    msg = json.loads(dados)
    if msg["t"] != "TICK":
        continue
    agora = time.monotonic()
    if ultimo is not None:
        gaps.append((agora - ultimo) * 1000)
    ultimo, n = agora, n + 1
    if msg["recs"]:
        print("recs inesperados no countdown:", msg)

if gaps:
    print("%d TICKs; intervalo médio %.1f ms (mín %.1f, máx %.1f)"
          % (n, sum(gaps) / len(gaps), min(gaps), max(gaps)))
else:
    print("TICKs recebidos:", n)