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

