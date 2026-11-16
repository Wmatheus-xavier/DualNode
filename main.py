"""Ponto de entrada do jogador DualNode.

Uso: python3 main.py --name Alice --udp-port 6001
     python3 main.py --demo      (abre a interface local, sem rede)
"""
import logging
import os
import select
import sys
import time

from common.config import ConfigError, build_parser, load_config
from peer.host import Host, configurar_log
from peer.lobby_client import LobbyClient, LobbyDown, LobbyError
from peer.lobby_ui import (choose_match, create_match_form, screen_connecting,
                           screen_notice, screen_room, screen_starting)
from peer.ui import TerminalUI, ask_choice, demo

log = logging.getLogger("main")


def parse_args():
    ap = build_parser()
    ap.add_argument("--demo", action="store_true",
                    help="abre a demo da interface, sem rede")
    return load_config(parser=ap)


def conectar(cfg, nome):
    host, porta = cfg["lobby"]["host"], cfg["lobby"]["port"]
    screen_connecting(host, porta)
    lobby = LobbyClient(host, porta, nome, cfg["peer"]["udp_port"],
                        udp_host=cfg["peer"]["advertise_host"],
                        dead_ms=cfg["timeouts"]["lobby_dead_ms"])
    lobby.connect()
    return lobby


def sala_de_espera(lobby, sala, players, max_players, i_am_host):
    """Teclado + socket do lobby com select. Devolve MATCH_START ou None."""
    aviso = ""
    desenhar = True
    while True:
        if desenhar:
            screen_room(sala, players, max_players, i_am_host, aviso)
            aviso = ""
            desenhar = False

        eventos = lobby.poll_events(0)
        for ev in eventos:
            tipo = ev["t"]
            if tipo == "PLAYER_JOINED":
                players = [p for p in players if p["slot"] != ev["slot"]]
                players.append({"slot": ev["slot"], "name": ev["name"]})
                aviso = f"{ev['name']} entrou na sala."
            elif tipo == "PLAYER_LEFT":
                players = [p for p in players if p["slot"] != ev["slot"]]
                aviso = f"{ev['name']} saiu da sala."
            elif tipo == "MATCH_CANCELLED":
                screen_notice("PARTIDA CANCELADA", ev["reason"])
                return None
            elif tipo == "ERROR":
                aviso = f"{ev['code']}: {ev['msg']}"
            elif tipo == "MATCH_START":
                return ev
        if eventos:
            desenhar = True
            continue

        pronto, _, _ = select.select([sys.stdin, lobby.fileno()], [], [], 1.0)
        if sys.stdin in pronto:
            linha = sys.stdin.readline()
            texto = linha.strip().lower()
            if linha == "" or texto == "q":
                lobby.leave_match()
                return None
            if texto == "" and i_am_host:
                if len(players) < 3:
                    aviso = "Minimo de 3 jogadores para iniciar."
                else:
                    lobby.start_match()
                    aviso = "Iniciando..."
            desenhar = True


def jogar(lobby, cfg, match_start):
    """Host (pid 0) ou Client, com a tela do jogo aberta."""
    meu_pid = lobby.slot
    players = match_start["players"]
    screen_starting(players)
    time.sleep(1)

    if meu_pid == 0:
        with TerminalUI() as ui:
            resultado = Host(cfg, match_start, ui=ui).run()
            ui.wait_key()
    else:
        try:
            from peer.client import Client
        except ImportError as e:
            screen_notice("MODULO AUSENTE", f"client.py ainda nao esta pronto:\n{e}")
            return
        resultado = Client(cfg, match_start, meu_pid).run()
    log.info("partida terminou: %s", resultado)

    nomes = {p["slot"]: p["name"] for p in players}
    tipo = resultado.get("result")
    if tipo == "WIN":
        v = resultado.get("winner")
        texto = "Voce venceu!" if v == meu_pid else f"{nomes.get(v, v)} venceu."
    elif tipo == "DRAW":
        texto = "Empate."
    elif tipo == "HOST_LOST":
        texto = "O host caiu. Partida encerrada."
    else:
        texto = "Partida encerrada."
    screen_notice("FIM DA PARTIDA", texto)

    if meu_pid == 0:
        lobby.match_end(resultado.get("winner"))   # melhor esforco
    lobby.match_id = None
    lobby.slot = None


def main():
    try:
        cfg, args = parse_args()
    except ConfigError as e:
        print(f"Erro de configuracao: {e}")
        sys.exit(2)

    if args.demo:
        demo()
        return

    nome = cfg["peer"]["name"] or "Jogador"
    os.makedirs("logs", exist_ok=True)
    configurar_log("logs/%s.log" % nome)

    print(f"DualNode - jogador {nome}")
    lobby = None
    while True:
        op = ask_choice("Menu", [
            "Criar partida",
            "Listar partidas / entrar",
            "Testar interface (demo local)",
            "Sair",
        ])
        if op == 2:
            demo()
            continue
        if op == 3:
            break

        try:
            if lobby is None or lobby.fileno() < 0:
                lobby = conectar(cfg, nome)

            if op == 0:
                sala, maximo = create_match_form()
                lobby.create_match(sala, maximo)
                inicio = sala_de_espera(lobby, sala, [{"slot": 0, "name": nome}], maximo, True)
            else:
                abertas = lobby.list_matches()
                escolhida = choose_match(abertas)
                if escolhida is None:
                    continue
                players = lobby.join_match(escolhida)
                info = next((m for m in abertas if m["match_id"] == escolhida), None)
                inicio = sala_de_espera(lobby, info["name"] if info else escolhida,
                                        players, info["max_players"] if info else 4, False)
            if inicio:
                jogar(lobby, cfg, inicio)
        except LobbyError as e:
            screen_notice("O LOBBY RECUSOU", f"{e.code}: {e.msg}")
        except LobbyDown as e:
            log.error("lobby caiu: %s", e)
            if lobby:
                lobby.close()
            screen_notice("LOBBY INDISPONIVEL", str(e))

    if lobby:
        lobby.close()


if __name__ == "__main__":
    main()