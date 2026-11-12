# HOST de teste (passo 12): usa um match_start.json (formato do MATCH_START) e pode rodar
# em OUTRA máquina. Com tela e teclado por padrão (W/A/S/D, Q sai); --sem-tela roda direto.
# uso: python3 -m testes_manuais.teste_host12 match_start.json [opções]
import argparse
import json

from peer.host import Host, configurar_log
from peer.ui import TerminalUI

ap = argparse.ArgumentParser(description="Host de teste a partir de um match_start.json")
ap.add_argument("match_start")
ap.add_argument("--bind", default="0.0.0.0", help="interface em que o host escuta (padrão: todas)")
ap.add_argument("--sem-tela", action="store_true", help="roda sem curses (só imprime o resultado)")
ap.add_argument("--peer-timeout-ms", type=int, default=3000)
ap.add_argument("--hello-deadline-ms", type=int, default=60000, help="quanto esperar os peers (padrão 60 s)")
ap.add_argument("--sim-loss", type=float, default=0.0, help="perda simulada (0 a 1)")
ap.add_argument("--sim-delay-ms", type=float, default=0.0, help="atraso simulado em cada sentido")
args = ap.parse_args()

with open(args.match_start, encoding="utf-8") as f:
    ms = json.load(f)
config = {"peer": {"bind_host": args.bind},
          "timeouts": {"hello_deadline_ms": args.hello_deadline_ms, "peer_timeout_ms": args.peer_timeout_ms}}
if args.sim_loss or args.sim_delay_ms:
    config["sim"] = {"loss": args.sim_loss, "delay_ms": args.sim_delay_ms}

configurar_log()
host_info = next(p for p in ms["players"] if p["slot"] == ms.get("host_slot", 0))
print("host: escutando UDP em %s:%d; esperando %d peer(s)..."
      % (args.bind, host_info["port"], len(ms["players"]) - 1))
for p in ms["players"]:
    if p["slot"] != host_info["slot"]:
        print("  espera [%d] %s em %s:%d" % (p["slot"], p["name"], p["host"], p["port"]))

if args.sem_tela:
    resultado = Host(config, ms).run()
else:
    with TerminalUI() as ui:
        resultado = Host(config, ms, ui=ui).run()
        ui.wait_key()
print("resultado:", resultado)