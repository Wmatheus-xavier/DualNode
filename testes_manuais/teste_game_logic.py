"""Testes de common/game_logic.py (sem rede).

Rodar da raiz do projeto:  python3 -m testes_manuais.teste_game_logic
"""
import copy

from common.game_logic import novo_estado, step


def criar(motos, width=10, height=10):
    """Monta um estado de teste. `motos` = lista de (pid, x, y, direção)."""
    e = novo_estado(width, height, [])  # estado vazio, sem motos
    for pid, x, y, d in motos:
        e["heads"][pid] = (x, y)
        e["dirs"][pid] = d
        e["alive"][pid] = True
        e["cells"][(x, y)] = pid
    return e


def teste_parede():
    e = criar([(0, 9, 5, "R"), (1, 2, 2, "R"), (2, 2, 8, "R")])
    r = step(e, {}, set(), 1)
    assert r["el"] == [[0, "WALL"]]
    assert r["mv"] == [[1, 3, 2], [2, 3, 8]]   # a eliminada não avança
    assert r["end"] is None


def teste_rastro():
    e = criar([(0, 5, 5, "R"), (1, 2, 2, "R"), (2, 2, 8, "R")])
    e["cells"][(6, 5)] = 9                     # rastro antigo no caminho da moto 0
    r = step(e, {}, set(), 1)
    assert r["el"] == [[0, "TRAIL"]]
    assert r["end"] is None


def teste_mesma_celula():
    # as motos 0 e 1 têm a mesma célula-alvo: (3, 5)
    e = criar([(0, 2, 5, "R"), (1, 4, 5, "L"), (2, 8, 1, "D")])
    r = step(e, {}, set(), 1)
    assert r["el"] == [[0, "HEAD"], [1, "HEAD"]]   # as duas morrem
    assert r["end"] == {"result": "WIN", "winner": 2}


def teste_troca_frente_a_frente():
    # lado a lado e em sentidos opostos: trocariam de lugar
    e = criar([(0, 4, 5, "R"), (1, 5, 5, "L"), (2, 8, 1, "D")])
    r = step(e, {}, set(), 1)
    assert r["el"] == [[0, "TRAIL"], [1, "TRAIL"]]


def teste_empate():
    e = criar([(0, 2, 5, "R"), (1, 4, 5, "L")])
    r = step(e, {}, set(), 1)
    assert r["el"] == [[0, "HEAD"], [1, "HEAD"]]
    assert r["mv"] == []
    assert r["end"] == {"result": "DRAW"}


def teste_vitoria():
    e = criar([(0, 9, 5, "R"), (1, 2, 2, "R")])
    r = step(e, {}, set(), 1)
    assert r["el"] == [[0, "WALL"]]
    assert r["end"] == {"result": "WIN", "winner": 1}


def teste_inversao_ignorada():
    e = criar([(0, 5, 5, "R"), (1, 1, 1, "D")])
    r = step(e, {0: "L"}, set(), 1)            # "L" é o oposto de "R"
    assert r["el"] == []
    assert r["mv"] == [[0, 6, 5], [1, 1, 2]]   # a moto 0 continua indo para a direita


def teste_desconectado():
    e = criar([(0, 5, 5, "R"), (1, 2, 2, "R"), (2, 2, 8, "R")])
    r = step(e, {}, {1}, 1)
    assert r["el"] == [[1, "DISC"]]
    assert [m[0] for m in r["mv"]] == [0, 2]   # a moto 1 não se move
    assert r["end"] is None


def teste_step_e_pura():
    e = criar([(0, 2, 5, "R"), (1, 4, 5, "L"), (2, 8, 1, "D")])
    antes = copy.deepcopy(e)
    step(e, {0: "U"}, {2}, 1)
    assert e == antes                          # o estado não foi alterado


if __name__ == "__main__":
    testes = [f for nome, f in sorted(globals().items()) if nome.startswith("teste_")]
    for t in testes:
        t()
        print("ok", t.__name__)
    print("todos passaram (%d testes)" % len(testes))