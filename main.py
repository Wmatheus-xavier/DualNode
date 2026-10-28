"""Ponto de entrada do jogador DualNode.

Uso: python main.py --name Alice
     python main.py --demo      (abre a interface local, sem rede)
"""
import argparse

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