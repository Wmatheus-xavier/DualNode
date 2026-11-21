# Gera um match_start.json (o mesmo formato da mensagem MATCH_START do lobby) para testar o
# host e os peers SEM o lobby, inclusive entre máquinas diferentes.
# uso: python3 -m testes_manuais.gerar_match_start IP_DO_HOST IP_PEER1 IP_PEER2 [IP_PEER3]
#   ex.: python3 -m testes_manuais.gerar_match_start 192.168.0.21 192.168.0.22 192.168.0.23
# O host é sempre o slot 0. Cada jogador usa a porta UDP 6001 + slot.
import json
import sys

NOMES = ["Alice", "Bob", "Carol", "Dave"]

if not 3 <= len(sys.argv) - 1 <= 4:
    sys.exit(__doc__)
ips = sys.argv[1:]
match_start = {
    "v": 1, "t": "MATCH_START", "match_id": "m1", "host_slot": 0,
    "config": {"width": 40, "height": 20, "tick_ms": 100},
    "players": [{"slot": i, "name": NOMES[i], "host": ip, "port": 6001 + i}
                for i, ip in enumerate(ips)],
}
with open("match_start.json", "w", encoding="utf-8") as f:
    json.dump(match_start, f, indent=2)
print("match_start.json criado:")
for p in match_start["players"]:
    print("  [%d] %-6s %s:%d%s" % (p["slot"], p["name"], p["host"], p["port"], "  <- HOST" if p["slot"] == 0 else ""))
print("\nCopie o arquivo para todas as máquinas. Depois:")
print("  host : python3 -m testes_manuais.teste_host12 match_start.json")
for i in range(1, len(ips)):
    print("  peer%d: python3 -m testes_manuais.teste_peer12 match_start.json --pid %d" % (i, i))