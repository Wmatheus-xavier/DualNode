"""Ponto de entrada do jogador DualNode.  Uso: python main.py --name Alice"""
import argparse

from peer.ui import ask_choice


def parse_args():
    p = argparse.ArgumentParser(description="DualNode - jogador")
    p.add_argument("--config", default="config.json")
    p.add_argument("--name", required=True)
    p.add_argument("--udp-port", type=int)
    p.add_argument("--lobby-host")
    p.add_argument("--lobby-port", type=int)
    return p.parse_args()


def main():
    args = parse_args()
    print(f"DualNode - jogador {args.name}")

    while True:
        op = ask_choice("Menu", ["Criar partida", "Listar partidas / entrar", "Sair"])
        if op == 0:
            pass  # TODO: conectar ao lobby, REGISTER, CREATE_MATCH
        elif op == 1:
            pass  # TODO: LIST_MATCHES, JOIN_MATCH
        else:
            break


if __name__ == "__main__":
    main()