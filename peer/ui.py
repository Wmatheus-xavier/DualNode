"""
Interface em terminal do DualNode.
Este arquivo cuida SOMENTE da parte visual. Nao ha nenhum codigo de rede aqui.

Como usar na parte de rede:
    view = GameView(my_pid=1, names={0: "Alice", 1: "Bob", 2: "Carol"})
    view.load_welcome(welcome["state"])          # ao receber WELCOME
    ...
    view.apply_record(rec)                       # para cada registro de ciclo do TICK
    ...
    with TerminalUI() as ui:
        while view.result is None:
            key = ui.poll_input()                # 'U','D','L','R','QUIT' ou None
            ...                                  # (rede: enviar INPUT, receber TICK)
            ui.draw(view)
        ui.wait_key()

Menus do lobby (antes da partida) usam input()/print() simples: veja as
funcoes ask_choice, ask_text, ask_int e print_matches no final do arquivo.

Para ver a tela funcionando sem rede:  python -m peer.ui
"""

import curses
import time

# ---------------------------------------------------------------- constantes

KEYMAP = {
    curses.KEY_UP: "U", ord("w"): "U", ord("W"): "U",
    curses.KEY_DOWN: "D", ord("s"): "D", ord("S"): "D",
    curses.KEY_LEFT: "L", ord("a"): "L", ord("A"): "L",
    curses.KEY_RIGHT: "R", ord("d"): "R", ord("D"): "R",
}
QUIT_KEYS = (ord("q"), ord("Q"))

REASON_TEXT = {
    "WALL": "bateu na parede",
    "TRAIL": "bateu em um rastro",
    "HEAD": "colisao frontal",
    "DISC": "desconectou",
}

PANEL_WIDTH = 28  # largura da coluna lateral com placar


# ------------------------------------------------------------ estado visual

class GameView:
    """Copia local do estado da partida, so para desenhar na tela.

    Nao decide nada: apenas aplica o que o host publicou (WELCOME e TICK).
    """

    def __init__(self, my_pid, names):
        self.my_pid = my_pid
        self.names = dict(names)   # {pid: nome}
        self.width = 0
        self.height = 0
        self.cells = {}            # (x, y) -> pid  (rastros)
        self.heads = {}            # pid -> (x, y)  (posicao atual da moto)
        self.alive = {}            # pid -> bool
        self.tick = 0
        self.result = None         # None | {"result":"WIN","winner":pid} | {"result":"DRAW"}
        self.events = []           # textos dos ultimos acontecimentos
        self.status = ""           # mensagem livre mostrada na ultima linha

    def load_welcome(self, state):
        """state = campo 'state' da mensagem WELCOME."""
        self.width = state["width"]
        self.height = state["height"]
        for p in state["players"]:
            pos = (p["x"], p["y"])
            self.heads[p["pid"]] = pos
            self.cells[pos] = p["pid"]
            self.alive[p["pid"]] = True

    def apply_record(self, rec):
        """rec = um registro de ciclo: {"n", "mv", "el", "end"}.

        Deve ser chamado uma vez por ciclo, em ordem (a camada de rede garante).
        """
        self.tick = rec["n"]
        for pid, x, y in rec["mv"]:
            self.heads[pid] = (x, y)
            self.cells[(x, y)] = pid
        for pid, reason in rec["el"]:
            self.alive[pid] = False
            texto = f"ciclo {rec['n']}: {self.name(pid)} {REASON_TEXT.get(reason, reason)}"
            self.events.append(texto)
        self.events = self.events[-4:]
        if rec["end"]:
            self.result = rec["end"]

    def name(self, pid):
        return self.names.get(pid, f"J{pid}")

    def result_text(self):
        if not self.result:
            return ""
        if self.result.get("result") == "DRAW":
            return "FIM: EMPATE!  (pressione qualquer tecla)"
        winner = self.result.get("winner")
        if winner == self.my_pid:
            return "FIM: VOCE VENCEU!  (pressione qualquer tecla)"
        return f"FIM: {self.name(winner)} venceu.  (pressione qualquer tecla)"


# ----------------------------------------------------------- tela do jogo

class TerminalUI:
    """Tela do jogo usando curses. Use com 'with TerminalUI() as ui:'."""

    def __enter__(self):
        self.scr = curses.initscr()
        curses.noecho()
        curses.cbreak()
        self.scr.keypad(True)
        self.scr.nodelay(True)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self.colors = curses.has_colors()
        if self.colors:
            curses.start_color()
            curses.use_default_colors()
            cores = [curses.COLOR_CYAN, curses.COLOR_YELLOW,
                     curses.COLOR_GREEN, curses.COLOR_MAGENTA]
            for i, cor in enumerate(cores):
                curses.init_pair(i + 1, cor, -1)
        return self

    def __exit__(self, *exc):
        self.scr.keypad(False)
        curses.nocbreak()
        curses.echo()
        curses.endwin()
        return False

    # -- entrada --

    def poll_input(self):
        """Le o teclado SEM bloquear.

        Retorna 'U', 'D', 'L', 'R', 'QUIT' ou None (nenhuma tecla relevante).
        Se varias teclas foram apertadas desde a ultima chamada, vale a ultima.
        """
        direcao = None
        while True:
            k = self.scr.getch()
            if k == -1:
                break
            if k in QUIT_KEYS:
                return "QUIT"
            if k in KEYMAP:
                direcao = KEYMAP[k]
        return direcao

    def wait_key(self):
        """Espera o jogador apertar qualquer tecla (usado na tela final)."""
        self.scr.nodelay(False)
        self.scr.getch()
        self.scr.nodelay(True)

    # -- saida --

    def _attr(self, pid):
        if not self.colors:
            return 0
        return curses.color_pair((pid % 4) + 1)

    def _put(self, y, x, text, attr=0):
        try:
            self.scr.addstr(y, x, text, attr)
        except curses.error:
            pass  # escrever no canto inferior direito da erro no curses; ignorar

    def draw(self, view):
        """Desenha o estado atual (arena + placar). Chame a cada ciclo."""
        self.scr.erase()
        h, w = view.height, view.width
        need_rows, need_cols = h + 3, w + 2 + 2 + PANEL_WIDTH
        rows, cols = self.scr.getmaxyx()
        if rows < need_rows or cols < need_cols:
            self._put(0, 0, f"Terminal pequeno: precisa de {need_cols}x{need_rows},"
                            f" tem {cols}x{rows}.")
            self.scr.refresh()
            return

        # moldura da arena
        borda = "+" + "-" * w + "+"
        self._put(0, 0, borda)
        self._put(h + 1, 0, borda)
        for y in range(h):
            self._put(y + 1, 0, "|")
            self._put(y + 1, w + 1, "|")

        # rastros: o digito e o numero do jogador
        for (x, y), pid in view.cells.items():
            self._put(y + 1, x + 1, str(pid), self._attr(pid))

        # motos: '@' viva, 'X' eliminada
        for pid, (x, y) in view.heads.items():
            if view.alive.get(pid):
                self._put(y + 1, x + 1, "@", self._attr(pid) | curses.A_BOLD)
            else:
                self._put(y + 1, x + 1, "X", curses.A_DIM)

        # placar
        px = w + 4
        self._put(0, px, "DualNode", curses.A_BOLD)
        self._put(1, px, f"Ciclo: {view.tick}")
        linha = 3
        for pid in sorted(view.alive):
            voce = " (voce)" if pid == view.my_pid else ""
            estado = "vivo" if view.alive[pid] else "eliminado"
            self._put(linha, px, f"{pid} {view.name(pid)}{voce}: {estado}",
                      self._attr(pid))
            linha += 1
        linha += 1
        self._put(linha, px, "W/A/S/D ou setas: virar")
        self._put(linha + 1, px, "Q: sair")
        linha += 3
        for ev in view.events:
            self._put(linha, px, ev[:PANEL_WIDTH])
            linha += 1

        # ultima linha: resultado ou mensagem
        self._put(h + 2, 0, view.result_text() or view.status)
        self.scr.refresh()


# ---------------------------------------------------- menus (sem curses)

def ask_choice(titulo, opcoes):
    """Mostra opcoes numeradas e retorna o indice (0..n-1) escolhido."""
    print(f"\n== {titulo} ==")
    for i, op in enumerate(opcoes, 1):
        print(f"  {i}) {op}")
    while True:
        txt = input("> ").strip()
        if txt.isdigit() and 1 <= int(txt) <= len(opcoes):
            return int(txt) - 1
        print("Opcao invalida.")


def ask_text(pergunta, padrao=None):
    sufixo = f" [{padrao}]" if padrao else ""
    txt = input(f"{pergunta}{sufixo}: ").strip()
    return txt or padrao


def ask_int(pergunta, minimo, maximo):
    while True:
        txt = input(f"{pergunta} ({minimo}-{maximo}): ").strip()
        if txt.isdigit() and minimo <= int(txt) <= maximo:
            return int(txt)
        print("Valor invalido.")


def print_matches(matches):
    """matches = campo 'matches' da mensagem MATCH_LIST."""
    if not matches:
        print("  (nenhuma partida aberta)")
        return
    print(f"  {'ID':<6}{'Sala':<18}{'Host':<14}Jogadores")
    for m in matches:
        print(f"  {m['match_id']:<6}{m['name']:<18}{m['host_name']:<14}"
              f"{m['players']}/{m['max_players']}")


def print_room(players):
    """players = lista de {'slot', 'name'} da sala de espera."""
    print("\nJogadores na sala:")
    for p in players:
        print(f"  [{p['slot']}] {p['name']}")


# ------------------------------------------------------------------- demo

def demo():
    """Demonstracao LOCAL, sem rede, so para testar a tela.

    A 'simulacao' abaixo e apenas um enfeite para gerar registros de ciclo;
    NAO e a logica oficial do jogo (essa fica em common/game_logic.py).
    """
    import random
    from collections import Counter

    W, H = 40, 20
    inicio = {0: (5, 5, "R")}
    """, 1: (34, 14, "L"), 2: (20, 1, "D") os testes"""

    delta = {"U": (0, -1), "D": (0, 1), "L": (-1, 0), "R": (1, 0)}
    oposto = {"U": "D", "D": "U", "L": "R", "R": "L"}

    view = GameView(0, {0: "Voce"})
    """, 1: "Bot1", 2: "Bot2" os teste"""

    view.load_welcome({"width": W, "height": H, "players": [
        {"pid": p, "x": x, "y": y, "dir": d} for p, (x, y, d) in inicio.items()]})
    direcao = {p: d for p, (_, _, d) in inicio.items()}

    def livre(pid, d):
        x, y = view.heads[pid]
        nx, ny = x + delta[d][0], y + delta[d][1]
        return 0 <= nx < W and 0 <= ny < H and (nx, ny) not in view.cells

    with TerminalUI() as ui:
        n = 0
        ui.draw(view)
        while view.result is None:
            tecla = ui.poll_input()
            if tecla == "QUIT":
                return
            if tecla and tecla != oposto[direcao[0]]:
                direcao[0] = tecla
            """ for bot in (1, 2):
                if view.alive[bot] and (not livre(bot, direcao[bot]) or random.random() < 0.08):
                    opcoes = [d for d in "UDLR" if d != oposto[direcao[bot]] and livre(bot, d)]
                    if opcoes:
                        direcao[bot] = random.choice(opcoes)  teste"""
            n += 1
            alvos = {}
            for p in view.alive:
                if view.alive[p]:
                    x, y = view.heads[p]
                    alvos[p] = (x + delta[direcao[p]][0], y + delta[direcao[p]][1])
            cont = Counter(alvos.values())
            mv, el = [], []
            for p, (x, y) in alvos.items():
                if not (0 <= x < W and 0 <= y < H):
                    el.append([p, "WALL"])
                elif (x, y) in view.cells:
                    el.append([p, "TRAIL"])
                elif cont[(x, y)] > 1:
                    el.append([p, "HEAD"])
                else:
                    mv.append([p, x, y])
            vivas = sum(view.alive.values()) - len(el)
            fim = None
            if vivas == 0:
                fim = {"result": "DRAW"}
            """ elif vivas == 1:
                vencedor = [p for p in alvos if p not in [e[0] for e in el]][0]
                fim = {"result": "WIN", "winner": vencedor} teste"""
            view.apply_record({"n": n, "mv": mv, "el": el, "end": fim})
            ui.draw(view)
            time.sleep(0.1)
        ui.wait_key()


if __name__ == "__main__":
    demo()
