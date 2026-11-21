# PEER de teste (passo 7): igual ao teste_peer6, mas pode "cair" sozinho.
# uso: python3 -m testes_manuais.teste_peer7 <pid> <porta> [morrer_apos_s] [direcao]
#   morrer_apos_s = 0 (padrão) nunca cai; ex.: 1.0 = some 1 s depois do WELCOME,
#   sem avisar ninguém (como um processo morto com kill -9 ou um cabo desligado).
import json
import socket
import sys
import time

pid, porta = int(sys.argv[1]), int(sys.argv[2])
morrer_apos = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
direcao = sys.argv[4] if len(sys.argv) > 4 else None
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
inicio = time.monotonic()

aplicados, iseq = 0, 0
eliminacoes, fim = [], None
proximo_input = ultimo_tick = time.monotonic()
while fim is None:
    agora = time.monotonic()
    if morrer_apos and agora - inicio >= morrer_apos:
        print("peer %d: caindo de propósito (sem avisar o host)" % pid)
        sys.exit(0)
    if agora >= proximo_input:
        iseq += 1
        enviar({"v": 1, "t": "INPUT", "m": "m1", "pid": pid,
                "iseq": iseq, "dir": direcao, "ack": aplicados})
        proximo_input += 0.1
    if agora - ultimo_tick > 3:
        print("host sumiu (3 s sem TICK)")
        break
    try:
        dados, _ = s.recvfrom(4096)
    except socket.timeout:
        continue
    msg = json.loads(dados)
    if msg["t"] != "TICK":
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

print("RESUMO eliminacoes=%s fim=%s" % (eliminacoes, fim))