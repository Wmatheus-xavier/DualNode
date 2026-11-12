"""Ponto de entrada do jogador DualNode.

Uso: python main.py --name Alice
     python main.py --demo      (abre a interface local, sem rede)
"""
import argparse
import json
from peer.host import Host, configurar_log
from peer.ui import TerminalUI, ask_choice
from peer.ui import ask_choice, demo


def parse_args():
    p = argparse.ArgumentParser(description="DualNode - jogador")
    p.add_argument("--config", default="config.json")
    p.add_argument("--name", default="Jogador")
    p.add_argument("--udp-port", type=int)
    p.add_argument("--lobby-host")
    p.add_argument("--lobby-port", type=int)
    p.add_argument("--demo", action="store_true",
                   help="abre a demo da interface, sem rede")
    return p.parse_args()

def jogar_como_host(match_start, nome):
    config = {
        "peer": {"bind_host": "0.0.0.0"},
        "timeouts": {"hello_deadline_ms": 10000, "peer_timeout_ms": 3000},
    }
    configurar_log("logs/host_%s.log" % nome)
    with TerminalUI() as ui:
        resultado = Host(config, match_start, ui=ui).run()   # bloqueia até a partida acabar
        ui.wait_key()
    print("resultado:", resultado)
    return resultado

def main():
    args = parse_args()

    if args.demo:
        demo()
        return

    print(f"DualNode - jogador {args.name}")
    while True:
        op = ask_choice("Menu", [
            "Criar partida",
            "Listar partidas / entrar",
            "Testar interface (demo local)",
            "Sair",
        ])
        if op == 0:
            pass  # TODO: conectar ao lobby, REGISTER, CREATE_MATCH
        elif op == 1:
            pass  # TODO: LIST_MATCHES, JOIN_MATCH
        elif op == 2:
            demo()
        else:
            break


if __name__ == "__main__":
    main()