# PEER de teste (passo 12): lê o mesmo match_start.json e fala com o host, em outra máquina.
# uso: python3 -m testes_manuais.teste_peer12 match_start.json --pid 1 [--bind IP] [--dir U/D/L/R]
# Se o handshake falhar, mostra o que conferir (IP do match_start, firewall UDP, host rodando).
import argparse
import json
import socket
import sys
import time

ap = argparse.ArgumentParser(description="Peer de teste a partir de um match_start.json")
ap.add_argument("match_start")
ap.add_argument("--pid", type=int, required=True)
ap.add_argument("--bind", default="0.0.0.0", help="IP local em que escuta (padrão: todos)")
ap.add_argument("--dir", help="direção usada nos INPUT (padrão: a inicial da moto)")
ap.add_argument("--espera-max", type=float, default=30.0, help="segundos tentando o handshake")
args = ap.parse_args()

with open(args.match_start, encoding="utf-8") as f:
    ms = json.load(f)
eu = next(p for p in ms["players"] if p["slot"] == args.pid)
hostinfo = next(p for p in ms["players"] if p["slot"] == ms.get("host_slot", 0))
HOST = (hostinfo["host"], hostinfo["port"])
MID, LINGER_S = ms["match_id"], 1.0

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind((args.bind, eu["port"]))
s.settimeout(0.05)
print("peer %d (%s): escutando em %s:%d; host em %s:%d" % (args.pid, eu["name"], args.bind, eu["port"], *HOST))
estranhos = set()


def enviar(msg):
    s.sendto(json.dumps(msg).encode(), HOST)


def receber():
    """Devolve a mensagem do host ou None. Avisa (uma vez) se vier de outro endereço."""
    try:
        dados, addr = s.recvfrom(4096)
    except socket.timeout:
        return None
    if addr != HOST:
        if addr not in estranhos:
            estranhos.add(addr)
            print("   aviso: datagrama de %s:%d ignorado (o host deveria ser %s:%d)" % (*addr, *HOST))
        return None
    return json.loads(dados)


inicio = time.monotonic()
welcome, ultimo_aviso = None, 0.0
while welcome is None:
    enviar({"v": 1, "t": "HELLO", "m": MID, "pid": args.pid})
    limite = time.monotonic() + 0.5
    while time.monotonic() < limite and welcome is None:
        msg = receber()
        if msg and msg["t"] == "WELCOME":
            welcome = msg
        elif msg and msg["t"] == "ABORT":
            print("ABORT recebido do host (motivo: %s)" % msg.get("reason"))
            sys.exit(0)
    espera = time.monotonic() - inicio
    if welcome is None and espera - ultimo_aviso >= 5:
        ultimo_aviso = espera
        print("   sem WELCOME há %.0f s: o host está rodando? o IP/porta de %s:%d estão certos? "
              "o firewall libera UDP %d?" % (espera, *HOST, hostinfo["port"]))
    if welcome is None and espera > args.espera_max:
        print("FALHA: handshake não completou em %.0f s" % args.espera_max)
        sys.exit(1)

direcao = args.dir or next(p["dir"] for p in welcome["state"]["players"] if p["pid"] == args.pid)
print("WELCOME ok (após %.1f s); direção usada nos INPUT: %s" % (time.monotonic() - inicio, direcao))

aplicados, iseq, fim, eliminacoes = 0, 0, None, []
proximo_input = ultimo_tick = time.monotonic()


def mandar_input():
    global iseq
    iseq += 1
    enviar({"v": 1, "t": "INPUT", "m": MID, "pid": args.pid, "iseq": iseq, "dir": direcao, "ack": aplicados})


while fim is None:
    agora = time.monotonic()
    if agora >= proximo_input:
        mandar_input()
        proximo_input += 0.1
    if agora - ultimo_tick > 3:
        print("host sumiu (3 s sem TICK): este peer NÃO soube o resultado")
        break
    msg = receber()
    if msg is None:
        continue
    if msg["t"] == "ABORT":
        print("ABORT recebido do host (motivo: %s)" % msg.get("reason"))
        sys.exit(0)
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

if fim is not None:
    fim_linger = time.monotonic() + LINGER_S
    while time.monotonic() < fim_linger:
        mandar_input()
        time.sleep(0.1)
print("RESUMO eliminacoes=%s fim=%s" % (eliminacoes, fim))