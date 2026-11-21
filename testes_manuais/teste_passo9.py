# PASSO 9: o host também joga (teclado, GameView e tela). Sem rede e sem terminal:
# usa uma interface falsa que "aperta" as teclas combinadas.
# uso: python3 -m testes_manuais.teste_passo9
import json
import time

import peer.host as ph
from peer.host import Host, configurar_log

configurar_log()
MS = {"match_id": "m1", "host_slot": 0,
      "config": {"width": 40, "height": 20, "tick_ms": 100},
      "players": [{"slot": 0, "name": "Alice", "host": "127.0.0.1", "port": 6001},
                  {"slot": 1, "name": "Bob",   "host": "127.0.0.1", "port": 6002},
                  {"slot": 2, "name": "Carol", "host": "127.0.0.1", "port": 6003}]}


class SockFalso:
    def __init__(self):
        self.enviados = []

    def sendto(self, dados, addr):
        self.enviados.append((json.loads(dados), addr))

    def recvfrom(self, n):
        raise BlockingIOError

    def close(self):
        pass


class UIFalsa:
    def __init__(self, teclas=()):
        self.teclas = list(teclas)
        self.desenhos = 0
        self.status = []

    def poll_input(self):
        return self.teclas.pop(0) if self.teclas else None

    def draw(self, view):
        self.desenhos += 1
        self.status.append(view.status)


def novo_host(teclas=(), com_ui=True):
    h = Host({"timeouts": {"peer_timeout_ms": 500}}, MS, ui=UIFalsa(teclas) if com_ui else None)
    h.sock = SockFalso()
    agora = time.monotonic()
    for j in h.jog.values():
        j["presente"], j["visto"] = True, agora
    h.estado = "RUNNING"
    return h


# 1) a view nasce pronta: nomes, meu pid e as 3 motos no lugar
h = novo_host()
assert h.view.my_pid == 0 and h.view.names == {0: "Alice", 1: "Bob", 2: "Carol"}
assert h.view.heads == {0: (5, 5), 1: (34, 14), 2: (20, 1)}
assert h.view.width == 40 and h.view.height == 20
print("1 ok: GameView inicial")

# 2) leitura do teclado: direção é "desejada" e persiste; Q pede saída
h = novo_host(teclas=["D", None, "QUIT"])
h._ler_teclado(); assert h.dir_host == "D" and not h.quer_sair
h._ler_teclado(); assert h.dir_host == "D"                      # sem tecla: mantém
h._ler_teclado(); assert h.quer_sair and h.dir_host == "D"
print("2 ok: teclado")

# 3) a direção do teclado move a moto do host e a tela é atualizada
h = novo_host(teclas=["D"])
h._ler_teclado()
h._executar_ciclo()
assert [0, 5, 6] in h.historico[0]["mv"]
assert h.view.heads[0] == (5, 6) and h.view.tick == 1
assert h.ui.desenhos == 1
print("3 ok: direção do host e tela")

# 4) inversão de sentido é ignorada (o host começa indo para a direita)
h = novo_host(teclas=["L"])
h._ler_teclado()
h._executar_ciclo()
assert [0, 6, 5] in h.historico[0]["mv"]
print("4 ok: inversão ignorada")

# 5) sem tecla nenhuma, a moto do host segue reta
h = novo_host()
h._executar_ciclo(); h._executar_ciclo()
assert h.view.heads[0] == (7, 5)
print("5 ok: segue reta")

# 6) o host bate na parede: a view mostra a eliminação
h = novo_host(teclas=["U"])
h._ler_teclado()
for _ in range(6):
    h._executar_ciclo()
assert h.view.alive[0] is False
assert any("Alice" in e for e in h.view.events), h.view.events
print("6 ok: eliminação do host aparece na view")

# 7) sem interface (headless) tudo continua funcionando
h = novo_host(com_ui=False)
h._ler_teclado(); h._desenhar("x")
h._executar_ciclo()
assert h.view.tick == 1
print("7 ok: sem interface")

# 8) Q durante o jogo interrompe o laço sem rodar ciclo
h = novo_host(teclas=["QUIT"])
assert h._fase_rodando(time.monotonic() + 10) is None
assert h.historico == []
print("8 ok: Q interrompe")

# 9) run() com Q: manda ABORT 3x a cada peer e devolve ABORT
h = novo_host(teclas=["QUIT"])
h._abrir_socket = lambda: None
h._fase_collecting = lambda: True
h._fase_countdown = lambda: 0.0
sock = h.sock
r = h.run()
abortos = [m for m, _ in sock.enviados if m["t"] == "ABORT"]
assert r == {"result": "ABORT", "winner": None}, r
assert len(abortos) == 6 and h.estado == "ABORTED", (len(abortos), h.estado)
print("9 ok: Q vira ABORT")

# 10) a tela mostra o countdown até "VAI!"
ph.COUNTDOWN_MS = 100
try:
    h = novo_host()
    h.tick_ms = 20
    h.estado = "COUNTDOWN"
    h._fase_countdown()
finally:
    ph.COUNTDOWN_MS = 3000
assert h.ui.desenhos == 5 and h.ui.status[-1] == "VAI!" and h.ui.status[0] == "Começa em 1 s", h.ui.status
assert h.estado == "RUNNING"
print("10 ok: countdown na tela")

# 11) a espera pelos jogadores também desenha
h = novo_host()
h.estado = "COLLECTING"
h._fase_collecting()
assert h.ui.status[0] == "Aguardando jogadores..."
print("11 ok: tela de espera")
print("ok")