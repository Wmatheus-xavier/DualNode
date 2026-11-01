import sys

from peer.ui import ask_choice, ask_int, ask_text

WIDTH = 58


def clear():
    """Limpa o terminal (so se for um terminal de verdade)."""
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")


def box(titulo, linhas, largura=WIDTH):
    """Monta uma caixa ASCII e devolve o texto pronto."""
    interno = largura - 2
    saida = ["+" + "-" * interno + "+"]
    if titulo:
        saida.append("|" + titulo.center(interno) + "|")
        saida.append("+" + "-" * interno + "+")
    for linha in linhas:
        saida.append("| " + linha[:interno - 2].ljust(interno - 2) + " |")
    saida.append("+" + "-" * interno + "+")
    return "\n".join(saida)


def _cabecalho():
    clear()
    print(box("D U A L N O D E", ["Motos de luz em rede (TCP + UDP)"]))
    print()


def main_menu(nome, lobby_host, lobby_port):
    """Menu principal. Retorna 0 (criar), 1 (listar/entrar) ou 2 (sair)."""
    _cabecalho()
    print(box("LOBBY", [f"Jogador: {nome}",
                        f"Lobby:   {lobby_host}:{lobby_port}"]))
    return ask_choice("Menu", ["Criar partida",
                               "Listar partidas / entrar",
                               "Sair"])


def create_match_form():
    """Pergunta os dados da sala. Retorna (nome_da_sala, max_players)."""
    _cabecalho()
    print(box("CRIAR PARTIDA", ["Voce sera o host da partida."]))
    nome = ask_text("Nome da sala", "sala1")
    maximo = ask_int("Maximo de jogadores", 3, 4)
    return nome, maximo


def choose_match(matches):
    """Mostra as partidas abertas. Retorna o match_id escolhido ou None."""
    _cabecalho()
    if not matches:
        print(box("PARTIDAS ABERTAS", ["(nenhuma partida aberta no momento)"]))
        input("\nENTER para voltar... ")
        return None

    linhas = [f"{'#':<3}{'Sala':<14}{'Host':<12}{'Jogadores'}"]
    for i, m in enumerate(matches, 1):
        linhas.append(f"{i:<3}{m['name']:<14}{m['host_name']:<12}"
                      f"{m['players']}/{m['max_players']}")
    print(box("PARTIDAS ABERTAS", linhas))

    while True:
        txt = input("\nNumero da partida (ENTER volta): ").strip()
        if txt == "":
            return None
        if txt.isdigit() and 1 <= int(txt) <= len(matches):
            return matches[int(txt) - 1]["match_id"]
        print("Numero invalido.")


def screen_connecting(host, port):
    _cabecalho()
    print(box("CONECTANDO", [f"Conectando ao lobby {host}:{port} ..."]))


def screen_room(sala, players, max_players, i_am_host, notice=""):
    """Sala de espera. Redesenhe sempre que chegar PLAYER_JOINED/PLAYER_LEFT."""
    _cabecalho()
    por_slot = {p["slot"]: p["name"] for p in players}
    linhas = []
    for slot in range(max_players):
        if slot in por_slot:
            marca = "  (host)" if slot == 0 else ""
            linhas.append(f"[{slot}] {por_slot[slot]}{marca}")
        else:
            linhas.append(f"[{slot}] ... aguardando jogador ...")
    print(box(f"SALA: {sala}  ({len(players)}/{max_players})", linhas))
    print()

    if i_am_host:
        if len(players) >= 3:
            print("  ENTER = iniciar a partida     q + ENTER = cancelar")
        else:
            print("  Minimo de 3 jogadores para iniciar.   q + ENTER = cancelar")
    else:
        print("  Aguardando o host iniciar...          q + ENTER = sair da sala")
    if notice:
        print(f"\n  >> {notice}")


def screen_starting(players):
    _cabecalho()
    nomes = [f"[{p['slot']}] {p['name']}" for p in sorted(players, key=lambda p: p["slot"])]
    print(box("PARTIDA INICIANDO!", nomes + ["", "Preparando a arena..."]))


def screen_notice(titulo, texto):
    """Aviso generico: erro do lobby, partida cancelada, lobby indisponivel etc."""
    _cabecalho()
    print(box(titulo, texto.split("\n")))
    input("\nENTER para continuar... ")


def demo():
    """Passeia por todas as telas com dados falsos, sem rede."""
    abertas = [
        {"match_id": "m1", "name": "sala-do-gui", "host_name": "Gui",
         "players": 2, "max_players": 4},
        {"match_id": "m2", "name": "teste", "host_name": "Bia",
         "players": 1, "max_players": 3},
    ]
    nome = "Alice"
    while True:
        op = main_menu(nome, "192.168.0.10", 5000)
        if op == 0:
            sala, maximo = create_match_form()
            jogadores = [{"slot": 0, "name": nome}]
            screen_room(sala, jogadores, maximo, True)
            input("\n[demo] ENTER: simular entrada de jogadores... ")
            jogadores += [{"slot": 1, "name": "Bob"}, {"slot": 2, "name": "Carol"}]
            screen_room(sala, jogadores, maximo, True, notice="Carol entrou na sala.")
            input("\n[demo] ENTER: simular inicio... ")
            screen_starting(jogadores)
            input("\n[demo] ENTER para voltar ao menu... ")
        elif op == 1:
            escolhida = choose_match(abertas)
            if escolhida:
                jogadores = [{"slot": 0, "name": "Gui"}, {"slot": 1, "name": "Bia"},
                             {"slot": 2, "name": nome}]
                screen_room("sala-do-gui", jogadores, 4, False)
                input("\n[demo] ENTER: simular host cancelando... ")
                screen_notice("PARTIDA CANCELADA", "O host saiu antes do inicio.")
        else:
            break


if __name__ == "__main__":
    demo()

