"""Regras do jogo DualNode (ciclo determinístico).

Este módulo não usa rede, tela nem relógio: só recebe dados e devolve dados.
O estado do jogo é um dicionário com estas chaves (as mesmas que o host usa):
    width, height : tamanho da arena
    heads         : {pid: (x, y)}  posição atual da moto
    dirs          : {pid: "U"/"D"/"L"/"R"}  direção atual
    alive         : {pid: True/False}  se a moto ainda está viva
    cells         : {(x, y): pid}  células ocupadas por rastro
"""

# Direção contrária de cada uma (usada para ignorar a inversão)
OPOSTO = {"U": "D", "D": "U", "L": "R", "R": "L"}

# Quanto cada direção mexe em (x, y). O y cresce para baixo, por isso "U" é -1.
DELTA = {"U": (0, -1), "D": (0, 1), "L": (-1, 0), "R": (1, 0)}

# Posição e direção inicial de cada jogador: pid -> (x, y, direção)
START = {0: (5, 5, "R"), 1: (34, 14, "L"), 2: (20, 1, "D"), 3: (20, 18, "U")}


def novo_estado(width, height, pids):
    """Monta o estado inicial para os jogadores da lista `pids`."""
    heads, dirs, alive, cells = {}, {}, {}, {}
    for p in pids:
        x, y, d = START[p]
        heads[p] = (x, y)
        dirs[p] = d
        alive[p] = True
        cells[(x, y)] = p  # a célula inicial já conta como rastro
    return {"width": width, "height": height, "heads": heads,
            "dirs": dirs, "alive": alive, "cells": cells}


def welcome_state(estado, tick_ms):
    """Resume o estado no formato que vai dentro da mensagem WELCOME."""
    return {"width": estado["width"], "height": estado["height"], "tick_ms": tick_ms,
            "players": [{"pid": p, "x": estado["heads"][p][0],
                         "y": estado["heads"][p][1], "dir": estado["dirs"][p]}
                        for p in sorted(estado["heads"])]}


def step(estado, direcoes, desconectados, n):
    """Calcula um ciclo do jogo e devolve o registro {n, mv, el, end}.

    É uma função pura: lê `estado`, mas NÃO altera nada dele. Quem quiser o
    estado novo usa `aplicar_registro` (próximo passo).
    """
    eliminados = {}  # pid -> motivo da eliminação neste ciclo

    # 1) Desconectados morrem primeiro e não se mexem neste ciclo
    for p in sorted(estado["alive"]):
        if estado["alive"][p] and p in desconectados:
            eliminados[p] = "DISC"

    # 2) Direção efetiva e célula-alvo de cada moto viva
    alvos = {}
    for p in sorted(estado["alive"]):
        if not estado["alive"][p] or p in eliminados:
            continue
        direcao = estado["dirs"][p]
        pedida = direcoes.get(p)
        # Só vale se for uma direção válida e não for a inversa da atual
        if pedida in DELTA and pedida != OPOSTO[direcao]:
            direcao = pedida
        dx, dy = DELTA[direcao]
        x, y = estado["heads"][p]
        alvos[p] = (x + dx, y + dy)

    # 3) Parede e rastro (olham só o estado do INÍCIO do ciclo)
    for p, (x, y) in alvos.items():
        if not (0 <= x < estado["width"] and 0 <= y < estado["height"]):
            eliminados[p] = "WALL"
        elif (x, y) in estado["cells"]:
            eliminados[p] = "TRAIL"

    # 4) Mesma célula: agrupa as motos que sobraram por célula-alvo
    por_alvo = {}
    for p, alvo in alvos.items():
        if p not in eliminados:
            por_alvo.setdefault(alvo, []).append(p)
    for pids in por_alvo.values():
        if len(pids) >= 2:  # duas ou mais na mesma célula: todas morrem
            for p in pids:
                eliminados[p] = "HEAD"

    # 5) Monta o registro
    mv = [[p, x, y] for p, (x, y) in sorted(alvos.items()) if p not in eliminados]
    el = [[p, motivo] for p, motivo in sorted(eliminados.items())]

    # 6) Fim da partida: quem sobrou vivo depois deste ciclo
    vivos = [p for p in sorted(alvos) if p not in eliminados]
    fim = None
    if not vivos:
        fim = {"result": "DRAW"}
    elif len(vivos) == 1:
        fim = {"result": "WIN", "winner": vivos[0]}
    return {"n": n, "mv": mv, "el": el, "end": fim}



def aplicar_registro(estado, registro):
    """Devolve um estado NOVO com o registro aplicado. Não altera o original."""
    heads = dict(estado["heads"])
    dirs = dict(estado["dirs"])
    alive = dict(estado["alive"])
    cells = dict(estado["cells"])

    # Quem se moveu: atualiza posição, rastro e direção
    for p, x, y in registro["mv"]:
        antigo_x, antigo_y = heads[p]
        # A direção é deduzida de quanto a moto andou (ex.: +1 em x = "R")
        for nome, delta in DELTA.items():
            if delta == (x - antigo_x, y - antigo_y):
                dirs[p] = nome
        heads[p] = (x, y)
        cells[(x, y)] = p

    # Quem foi eliminado: marca como morto (o rastro permanece)
    for p, motivo in registro["el"]:
        alive[p] = False

    return {"width": estado["width"], "height": estado["height"],
            "heads": heads, "dirs": dirs, "alive": alive, "cells": cells}