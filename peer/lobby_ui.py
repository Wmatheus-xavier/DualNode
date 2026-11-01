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

