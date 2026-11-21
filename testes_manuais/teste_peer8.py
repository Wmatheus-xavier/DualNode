# PEER de teste (passo 8): confirma o fim da partida e pode "perder" o TICK final de propósito.
# uso: python3 -m testes_manuais.teste_peer8 <pid> <porta> [perde_fim] [direcao]
#   perde_fim = quantos TICKs que carregam o fim da partida este peer descarta (padrão 0).
#               Simula a perda do último datagrama, o caso que o passo 8 resolve.
import json
import socket
import sys
import time

pid, porta = int(sys.argv[1]), int(sys.argv[2])
perde_fim = int(sys.argv[3]) if len(sys.argv) > 3 else 0
direcao = sys.argv[4] if len(sys.argv) > 4 else None
LINGER_S = 1.0          # depois do fim, continua mandando INPUT com o ack final (README: ~2 s)
HOST = ("127.0.0.1", 6001)

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("127.0.0.1", porta))
s.settimeout(0.05)


def enviar(msg):
    s.sendto(json.dumps(msg).encode(), HOST)


welcome = None
while welcome is None:
    enviar({"v": 1, "t": "HELLO", "m": "m1", "pid": pid})
    limite = time.monotonic() + 0.5
    while time.monotonic() < limite and welcome is None:
        try:
            dados, _ = s.recvfrom(4096)
        except socket.timeout:
            continue
        msg = json.loads(dados)
        if msg["t"] == "WELCOME":
            welcome = msg

if direcao is None:
    direcao = next(p["dir"] for p in welcome["state"]["players"] if p["pid"] == pid)
print("WELCOME ok; direção usada nos INPUT:", direcao)

aplicados, iseq, descartados = 0, 0, 0
eliminacoes, fim = [], None
proximo_input = ultimo_tick = time.monotonic()


def mandar_input():
    global iseq
    iseq += 1
    enviar({"v": 1, "t": "INPUT", "m": "m1", "pid": pid,
            "iseq": iseq, "dir": direcao, "ack": aplicados})


while fim is None:
    agora = time.monotonic()
    if agora >= proximo_input:
        mandar_input()
        proximo_input += 0.1
    if agora - ultimo_tick > 3:
        print("host sumiu (3 s sem TICK): este peer NÃO soube o resultado")
        break
    try:
        dados, _ = s.recvfrom(4096)
    except socket.timeout:
        continue
    msg = json.loads(dados)
    if msg["t"] != "TICK":
        continue
    if any(r["end"] for r in msg["recs"]) and descartados < perde_fim:
        descartados += 1                       # perda simulada do TICK com o fim
        print("   (descartei o TICK com o fim, %d/%d)" % (descartados, perde_fim))
        continue
    ultimo_tick = agora
    for rec in msg["recs"]:
        if rec["n"] != aplicados + 1:
            continue
        aplicados = rec["n"]
        for pid_el, motivo in rec["el"]:
            eliminacoes.append((rec["n"], pid_el, motivo))
            print("ciclo %d: pid %d eliminado (%s)" % (rec["n"], pid_el, motivo))
        if rec["end"]:
            fim = rec["end"]

if fim is not None:                             # confirma o fim para o host (linger)
    fim_linger = time.monotonic() + LINGER_S
    while time.monotonic() < fim_linger:
        mandar_input()
        time.sleep(0.1)
print("RESUMO eliminacoes=%s fim=%s" % (eliminacoes, fim))