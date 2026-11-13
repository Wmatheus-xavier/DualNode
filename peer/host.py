"""Host (árbitro) da partida DualNode. Roteiro: docs/roteiro-host.md"""
import json
import logging
import os
import socket
import time
import math

log = logging.getLogger("host")
from peer.ui import GameView

# Os blocos try/except abaixo funcionam assim: tenta importar a versão "oficial"
# feita por outra pessoa do grupo. Se o arquivo ainda não existir, usa uma versão
# reserva definida aqui mesmo, só pra o host conseguir rodar e ser testado sozinho.

# step(): avança o jogo em um ciclo (um "tick") e devolve o registro do que aconteceu.
try:
    from common.game_logic import step
except ImportError:
    # Direção contrária de cada uma (ninguém pode dar meia-volta de uma vez)
    _OPOSTO = {"U": "D", "D": "U", "L": "R", "R": "L"}
    # Quanto cada direção mexe em (x, y). O y cresce pra baixo, por isso "U" é -1
    _DELTA = {"U": (0, -1), "D": (0, 1), "L": (-1, 0), "R": (1, 0)}

    def step(estado, desejadas, desconectados, n):
        # el = lista de eliminados neste ciclo, no formato [pid, motivo]
        el = []

        # 1) Quem caiu da rede é eliminado com o motivo "DISC"
        for p in sorted(estado["alive"]):
            if estado["alive"][p] and p in desconectados:
                estado["alive"][p] = False
                el.append([p, "DISC"])

        # 2) Calcula pra onde cada jogador vivo quer ir
        alvos = {}
        for p in sorted(estado["alive"]):
            if not estado["alive"][p]:
                continue
            d = desejadas.get(p)
            # Só troca de direção se não for a oposta à atual
            if d and d != _OPOSTO[estado["dirs"][p]]:
                estado["dirs"][p] = d
            dx, dy = _DELTA[estado["dirs"][p]]
            x, y = estado["heads"][p]
            alvos[p] = (x + dx, y + dy)

        # 3) Aplica os movimentos. Quem sair do tabuleiro morre ("WALL")
        # mv = lista de movimentos válidos, no formato [pid, x, y]
        mv = []
        for p, (x, y) in alvos.items():
            if not (0 <= x < estado["width"] and 0 <= y < estado["height"]):
                estado["alive"][p] = False
                el.append([p, "WALL"])
            else:
                estado["heads"][p] = (x, y)
                estado["cells"][(x, y)] = p
                mv.append([p, x, y])

        # 4) Vê se a partida acabou: ninguém vivo = empate, um só vivo = vitória
        vivos = [p for p in sorted(estado["alive"]) if estado["alive"][p]]
        fim = None
        if not vivos:
            fim = {"result": "DRAW"}
        elif len(vivos) == 1:
            fim = {"result": "WIN", "winner": vivos[0]}
        return {"n": n, "mv": mv, "el": sorted(el), "end": fim}


# encode/decode: transformam mensagem (dict) em bytes pra mandar pela rede e vice-versa
try:
    from common.protocol import decode, encode            # pessoa E
except ImportError:
    def decode(data):
        # Se não for JSON válido, devolve None em vez de quebrar o host
        try:
            msg = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        # Toda mensagem válida é um dict, tem versão 1 ("v") e um tipo ("t")
        if not isinstance(msg, dict) or msg.get("v") != 1 or "t" not in msg:
            return None
        return msg

    def encode(msg):
        # separators sem espaço deixa o JSON menor, e o datagrama tem limite de tamanho
        return json.dumps(msg, separators=(",", ":")).encode("utf-8")

# novo_estado(): monta o tabuleiro inicial. welcome_state(): resume esse estado
# no formato que vai dentro da mensagem WELCOME.
try:
    from common.game_logic import novo_estado, welcome_state   # pessoa C
except ImportError:
    # Posição e direção inicial de cada slot: pid -> (x, y, direção)
    _START = {0: (5, 5, "R"), 1: (34, 14, "L"), 2: (20, 1, "D"), 3: (20, 18, "U")}

    def novo_estado(width, height, pids):
        # heads = onde está a cabeça de cada um, dirs = pra onde olha,
        # alive = se está vivo, cells = quem já passou por cada casa
        heads, dirs, alive, cells = {}, {}, {}, {}
        for p in pids:
            x, y, d = _START[p]
            heads[p], dirs[p], alive[p], cells[(x, y)] = (x, y), d, True, p
        return {"width": width, "height": height, "heads": heads,
                "dirs": dirs, "alive": alive, "cells": cells}

    def welcome_state(estado, tick_ms):
        return {"width": estado["width"], "height": estado["height"], "tick_ms": tick_ms,
                "players": [{"pid": p, "x": estado["heads"][p][0], "y": estado["heads"][p][1],
                             "dir": estado["dirs"][p]} for p in sorted(estado["heads"])]}
# -----------------------------------------------------------------------------

# Tamanho máximo de um datagrama UDP, tanto pra enviar quanto pra aceitar
MAX_DATAGRAMA = 1200
# Quanto tempo de contagem regressiva antes da partida começar
COUNTDOWN_MS = 3000
# Se o host atrasar mais que isso (em número de ticks), em vez de correr pra
# recuperar ele simplesmente reajusta o relógio
TOLERANCIA_ATRASO = 5
# Quantos registros de ciclo no máximo vão dentro de cada TICK
JANELA = 8

# Tipos que um PEER pode mandar ao host, por estado do host.
# Qualquer coisa fora dessa tabela é descartada.
ACEITOS = {
    "COLLECTING": {"HELLO", "INPUT"},
    "COUNTDOWN": {"HELLO", "INPUT"},
    "RUNNING": {"INPUT"},
    "ENDING": {"INPUT"},
}

def configurar_log(caminho="logs/host.log"):
    # Cria a pasta do log se ainda não existir
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    # filemode="w" apaga o log da partida anterior a cada execução
    logging.basicConfig(
        filename=caminho,
        filemode="w",
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(message)s",
    )
def _proximo_instante(proximo, agora, tick_s):
    # Calcula quando deve acontecer o próximo ciclo.
    # Somar o tick ao horário que estava previsto (e não ao horário de agora)
    # evita que pequenos atrasos se acumulem e o jogo fique mais lento.

    proximo += tick_s
    # Mas se o atraso ficou grande demais (travou, PC ocupado...), desiste de
    # recuperar o tempo perdido e recomeça a contar a partir de agora.
    if agora - proximo > TOLERANCIA_ATRASO * tick_s:
        log.warning("atrasado %.0f ms; reajustando o relógio do ciclo",
                    (agora - proximo) * 1000)
        proximo = agora + tick_s
    return proximo


class Host:
    # O Host é o árbitro: só ele decide o que acontece no jogo. Os outros
    # jogadores (peers) mandam suas direções e recebem de volta o resultado de cada ciclo.
    #
    # Estados possíveis: COLLECTING -> COUNTDOWN -> RUNNING -> ENDING -> FINISHED
    # (ou ABORTED se algo der errado)

    def __init__(self, config, match_start, ui=None):
        self.config = config
        # match_start = dados da partida (id, jogadores, tamanho do mapa...)
        self.match_start = match_start
        # ui pode ser None, aí o host roda sem desenhar nada na tela
        self.ui = ui
        self.sock = None
        self.meu_pid = None
        # pid -> nome de todo mundo, inclusive do próprio host
        self.nomes = {}
        # pid -> dados de rede de cada peer (sem o host)
        self.jog = {}
        # Endereço (ip, porta) -> pid. Serve pra saber de quem veio um datagrama
        self.addr_para_pid = {}
        self._montar_jogadores()
        self.estado = "COLLECTING"
        cfg = match_start["config"]
        self.width, self.height, self.tick_ms = cfg["width"], cfg["height"], cfg["tick_ms"]
        # Tempos limite vêm da config, com valor padrão se não estiverem lá
        t = config.get("timeouts", {})
        # Quanto tempo esperar os peers mandarem HELLO
        self.hello_deadline_s = t.get("hello_deadline_ms", 10000) / 1000
        # Quanto tempo de silêncio até considerar um peer desconectado
        self.peer_timeout_s = t.get("peer_timeout_ms", 3000) / 1000


        # Estado real do jogo (posições, quem está vivo...)
        self.jogo = novo_estado(self.width, self.height, sorted(self.nomes))
        # Peers que nunca apareceram na fase inicial
        self.desconectados_iniciais = set()
        # Lista de todos os ciclos já executados. É daqui que saem os TICKs
        # enviados e também o que os peers pedem de volta se perderem algo.
        self.historico = []
        # Peers que serão eliminados por desconexão no próximo ciclo
        self.a_eliminar = set()
        self.resultado = None
        self.motivo_abort = None
        # Última direção apertada pelo teclado do host
        self.dir_host = None
        self.quer_sair = False
        # GameView é o que a interface desenha. O host também mantém a sua.
        self.view = GameView(self.meu_pid, self.nomes)
        self.view.load_welcome(welcome_state(self.jogo, self.tick_ms))
        log.info("Host criado (partida %s)", match_start.get("match_id"))

    def _enviar_tick_vazio(self, so_presentes=False):
        # TICK sem registros: serve só pra avisar "estou vivo" e manter a
        # conexão ativa antes do jogo começar. Com so_presentes=True, manda
        # apenas pra quem já mandou HELLO.
        for pid, j in self.jog.items():
            if j["conectado"] and (j["presente"] or not so_presentes):
                self._enviar(pid, {"v": 1, "t": "TICK", "m": self.match_start["match_id"],
                                   "pid": self.meu_pid, "recs": []})

    def _fase_countdown(self):
        # Contagem regressiva: manda TICKs vazios no ritmo normal do jogo.
        # Assim os peers já veem o intervalo certo entre ticks antes de valer.
        # Devolve o instante do próximo ciclo, ou None se o host quis sair.

        tick_s = self.tick_ms / 1000
        # Quantos ticks cabem dentro da contagem
        total = math.ceil(COUNTDOWN_MS / self.tick_ms)
        log.info("COUNTDOWN: %d TICKs vazios, um a cada %d ms", total, self.tick_ms)

        proximo = time.monotonic()
        # intervalos guarda o tempo real entre ticks, só pra registrar no log
        enviados, ultimo, intervalos = 0, None, []
        while enviados < total:

            self._ler_teclado()
            if self.quer_sair:
                return None

            # Continua atendendo a rede durante a contagem (HELLO atrasado, INPUT...)
            for dados, addr in self._receber_tudo():
                self._tratar_datagrama(dados, addr)

            # Ainda não chegou a hora do próximo tick: dorme um pouquinho e volta
            agora = time.monotonic()
            if agora < proximo:
                time.sleep(min(proximo - agora, 0.005))
                continue

            self._enviar_tick_vazio()
            enviados += 1
            restante = math.ceil((total - enviados) * tick_s)
            self._desenhar("Começa em %d s" % restante if restante else "VAI!")

            if ultimo is not None:
                intervalos.append((agora - ultimo) * 1000)
            ultimo = agora
            proximo = _proximo_instante(proximo, agora, tick_s)

        if intervalos:
            log.info("COUNTDOWN concluído: intervalo médio %.1f ms (mín %.1f, máx %.1f)",
                     sum(intervalos) / len(intervalos), min(intervalos), max(intervalos))

        self.estado = "RUNNING"
        # Zera o "visto por último" de todo mundo, senão o tempo que passou na
        # contagem poderia contar como silêncio e gerar timeout injusto
        agora = time.monotonic()
        for j in self.jog.values():
            if j["conectado"]:
                j["visto"] = agora
        return proximo

    def _descartar(self, addr, motivo):
        # Joga fora um datagrama inválido. Só anota no log o porquê.
        log.debug("descartado de %s: %s", addr, motivo)
        return None

    def _validar(self, dados, addr):
        # Porteiro de toda mensagem que chega. Se passar por todas as checagens,
        # devolve (pid, mensagem). Se falhar em qualquer uma, devolve None.

        # Grande demais: provavelmente lixo ou ataque
        if len(dados) > MAX_DATAGRAMA:
            return self._descartar(addr, "grande demais (%d bytes)" % len(dados))

        # Não é uma mensagem do protocolo
        msg = decode(dados)
        if msg is None:
            return self._descartar(addr, "mensagem inválida")

        # Mensagem de outra partida (por exemplo, sobra de uma partida antiga)
        if msg.get("m") != self.match_start.get("match_id"):
            return self._descartar(addr, "partida diferente")

        pid = msg.get("pid")
        if not isinstance(pid, int):
            return self._descartar(addr, "pid ausente ou inválido")

        # O endereço de origem precisa ser de um jogador conhecido, e o pid que
        # a mensagem diz ter tem que bater com o dono desse endereço.
        # Isso impede um peer de se passar por outro.
        dono = self._pid_da_origem(addr)
        if dono is None:
            return self._descartar(addr, "origem desconhecida")
        if dono != pid:
            return self._descartar(addr, "pid %s veio do endereço do pid %s" % (pid, dono))

        # Por fim, o tipo da mensagem tem que fazer sentido no estado atual
        if msg["t"] not in ACEITOS.get(self.estado, set()):
            return self._descartar(addr, "tipo %s fora de estado (%s)" % (msg["t"], self.estado))

        return pid, msg

    def _tratar_datagrama(self, dados, addr):
        # Valida e depois manda pro tratamento certo conforme o tipo
        r = self._validar(dados, addr)
        if r is None:
            return
        pid, msg = r
        if msg["t"] == "HELLO":
            self._tratar_hello(pid, msg, addr)
        elif msg["t"] == "INPUT":
            self._tratar_input(pid, msg)

    def _enviar(self, pid, msg):
        dados = encode(msg)
        # Só avisa no log se passar do limite. Quem monta a mensagem é que deve cuidar disso.
        if len(dados) > MAX_DATAGRAMA:
            log.error("mensagem %s para pid %s tem %d bytes (limite %d)",
                      msg.get("t"), pid, len(dados), MAX_DATAGRAMA)
        # UDP pode falhar sem ser grave, então só registra e segue o jogo
        try:
            self.sock.sendto(dados, self.jog[pid]["addr"])
        except OSError as e:
            log.warning("falha ao enviar %s para pid %s: %s", msg.get("t"), pid, e)

    def _tratar_hello(self, pid, msg, addr):
        # HELLO é o peer dizendo "cheguei". Respondemos com WELCOME.
        j = self.jog[pid]
        # Se o peer já foi dado como ausente (passou do prazo), não aceita mais
        if not j["conectado"]:
            log.info("HELLO tardio de pid %s ignorado (já dado como ausente)", pid)
            return
        j["presente"] = True
        j["visto"] = time.monotonic()
        log.info("HELLO de pid %s: respondendo WELCOME", pid)
        self._enviar_welcome(pid)

    def _enviar_welcome(self, pid):
        # WELCOME leva o estado inicial do jogo e o tempo da contagem, pra o peer
        # montar a tela dele igual à do host.
        # Se o peer mandar HELLO de novo (porque o WELCOME se perdeu), é só reenviar.
        self._enviar(pid, {
            "v": 1, "t": "WELCOME", "m": self.match_start["match_id"], "pid": self.meu_pid,
            "state": welcome_state(self.jogo, self.tick_ms),
            "countdown_ms": COUNTDOWN_MS,
        })

    def _abortar(self, motivo, tentativas=3, intervalo_s=0.05):
        # Encerra a partida avisando todo mundo com ABORT.
        # Manda algumas vezes seguidas porque UDP não garante que a mensagem chega.

        self.estado = "ABORTED"
        self.motivo_abort = motivo
        log.warning("partida abortada: %s", motivo)
        self._desenhar("Partida encerrada (%s). Pressione qualquer tecla." % motivo)
        for i in range(tentativas):
            for pid, j in self.jog.items():
                if j["conectado"]:
                    self._enviar(pid, {"v": 1, "t": "ABORT", "m": self.match_start["match_id"],
                                       "pid": self.meu_pid, "reason": motivo})
            # Não precisa esperar depois da última tentativa
            if i < tentativas - 1:
                time.sleep(intervalo_s)

    def _fase_collecting(self):
        # Primeira fase: espera os peers mandarem HELLO, até um prazo.
        # Devolve True pra seguir pra contagem, False se a partida não vai rolar.

        self._desenhar("Aguardando jogadores...")
        tick_s = self.tick_ms / 1000
        # Enquanto espera, manda TICK vazio de tempos em tempos pra quem já chegou
        proximo_vida = time.monotonic() + tick_s
        limite = time.monotonic() + self.hello_deadline_s
        while time.monotonic() < limite:
            for dados, addr in self._receber_tudo():
                self._tratar_datagrama(dados, addr)
            # Se todo mundo já chegou, não precisa esperar o prazo inteiro
            if all(j["presente"] for j in self.jog.values()):
                log.info("todos os peers se apresentaram")
                break
            agora = time.monotonic()
            if agora >= proximo_vida:
                self._enviar_tick_vazio(so_presentes=True)
                proximo_vida = agora + tick_s
            time.sleep(0.01)
            self._ler_teclado()
            if self.quer_sair:
                return False

        # Quem não apareceu até o prazo sai da partida. Ele vai ser eliminado
        # com motivo DISC logo no primeiro ciclo.
        ausentes = [pid for pid, j in self.jog.items() if not j["presente"]]
        for pid in ausentes:
            self.jog[pid]["conectado"] = False
            self.desconectados_iniciais.add(pid)
        if ausentes:
            log.warning("não se apresentaram (serão eliminados com DISC): %s", ausentes)

        # Sem ninguém pra jogar contra, não faz sentido continuar
        if len(ausentes) == len(self.jog):           # só o host sobrou
            self._abortar("jogadores insuficientes")
            return False
        self.estado = "COUNTDOWN"
        return True


    def _tratar_input(self, pid, msg):
        # INPUT é o peer dizendo qual direção quer seguir.
        # Campos: iseq = número de sequência do input, dir = direção,
        # ack = quantos ciclos do histórico o peer já recebeu.
        j = self.jog[pid]
        if not j["conectado"]:
            return
        if not j["presente"]:
            log.debug("INPUT de pid %s antes do HELLO", pid)
            return

        # Confere se os campos são do tipo certo. O isinstance(v, bool) é porque
        # em Python True/False também contam como int e não queremos isso.
        iseq, d, ack = msg.get("iseq"), msg.get("dir"), msg.get("ack")
        if any(isinstance(v, bool) or not isinstance(v, int) for v in (iseq, ack)) or ack < 0:
            log.debug("INPUT de pid %s com iseq/ack inválido: %s", pid, msg)
            return
        if d not in ("U", "D", "L", "R"):
            log.debug("INPUT de pid %s com direção inválida: %r", pid, d)
            return
        # UDP pode entregar fora de ordem ou duplicado. Só vale input mais novo
        # que o último que já aceitamos.
        if iseq <= j["iseq"]:
            log.debug("INPUT de pid %s repetido/atrasado (iseq %s <= %s)", pid, iseq, j["iseq"])
            return

        j["iseq"] = iseq
        j["dir"] = d
        j["visto"] = time.monotonic()
        # O ack só pode crescer, e nunca passar do que o host realmente já gerou.
        # Isso protege contra um peer mandando ack absurdo.
        j["ack"] = max(j["ack"], min(ack, len(self.historico)))

    def _enviar_ticks(self, so_pendentes=False):
        # Manda a cada peer os ciclos que ele ainda não confirmou (do ack em diante).
        # Como sempre reenvia o que não foi confirmado, perder um pacote não
        # faz o peer ficar sem informação.
        for pid, j in self.jog.items():
            if not j["conectado"]:
                continue
            # Com so_pendentes=True, pula quem já está com tudo em dia
            if so_pendentes and j["ack"] >= len(self.historico):
                    continue
            # No máximo JANELA registros por mensagem
            recs = self.historico[j["ack"]: j["ack"] + JANELA]
            msg = {"v": 1, "t": "TICK", "m": self.match_start["match_id"],
                   "pid": self.meu_pid, "recs": recs}
            # Se mesmo assim passar do tamanho máximo, vai tirando registros do
            # fim até caber (sempre deixa pelo menos um)
            while len(recs) > 1 and len(encode(msg)) > MAX_DATAGRAMA:
                recs = recs[:-1]
                msg["recs"] = recs
            self._enviar(pid, msg)

    def _fase_ending(self):
        # Depois que o jogo acaba, o host ainda espera os peers confirmarem que
        # receberam o último ciclo. Sem isso, um peer que perdeu o último TICK
        # nunca ficaria sabendo quem ganhou.

        n_final = len(self.historico)
        tick_s = self.tick_ms / 1000
        inicio = time.monotonic()
        # Não espera pra sempre: tem um tempo máximo
        limite = inicio + self.peer_timeout_s
        proximo = inicio + tick_s
        log.info("ENDING: aguardando confirmação do ciclo %d (até %.1f s)", n_final, self.peer_timeout_s)
        while True:
            for dados, addr in self._receber_tudo():
                self._tratar_datagrama(dados, addr)
            # Pendente = peer conectado que ainda não confirmou o ciclo final
            pendentes = [pid for pid, j in self.jog.items()
                         if j["conectado"] and j["ack"] < n_final]
            agora = time.monotonic()
            if not pendentes:
                log.info("ENDING: todos confirmaram o ciclo %d em %.0f ms",
                         n_final, (agora - inicio) * 1000)
                break
            if agora >= limite:
                log.warning("ENDING: sem confirmação de %s após %.1f s (desistindo)",
                            pendentes, agora - inicio)
                break

            self._ler_teclado()
            if self.quer_sair:
                log.warning("ENDING: host saiu antes de todos confirmarem (pendentes: %s)", pendentes)
                break

            # A cada tick, reenvia só pra quem ainda não confirmou
            if agora >= proximo:
                self._enviar_ticks(so_pendentes=True)
                proximo += tick_s
            else:
                time.sleep(min(proximo - agora, 0.005))
        self.estado = "FINISHED"

    def _verificar_timeouts(self, agora=None):
        # Quem ficou tempo demais sem mandar INPUT é considerado desconectado.
        # Não elimina na hora: marca em a_eliminar, e a eliminação (DISC)
        # acontece dentro do próximo ciclo, igual pra todos.
        # O parâmetro "agora" existe pra poder testar com um horário falso.

        agora = time.monotonic() if agora is None else agora
        for pid, j in self.jog.items():
            if not j["conectado"] or j["visto"] is None:
                continue
            silencio = agora - j["visto"]
            if silencio > self.peer_timeout_s:
                j["conectado"] = False
                self.a_eliminar.add(pid)
                log.warning("pid %s (%s) sem INPUT há %.1f s: DISC no ciclo %d",
                            pid, self.nomes.get(pid, pid), silencio, len(self.historico) + 1)

    def _desenhar(self, status=None):
        # Redesenha a tela. Se não tem interface (modo sem tela), não faz nada.
        if self.ui is None:
            return
        if status is not None:
            self.view.status = status
        self.ui.draw(self.view)

    def _ler_teclado(self):
        # Lê o teclado do host sem travar o loop.
        # "QUIT" pede pra sair, qualquer outra tecla vira a direção do host.

        if self.ui is None:
            return
        tecla = self.ui.poll_input()
        if tecla == "QUIT":
            self.quer_sair = True
        elif tecla is not None:
            self.dir_host = tecla

    def _executar_ciclo(self):
        # Um ciclo completo do jogo. Devolve o "end" do registro (None se a
        # partida continua, ou o resultado se acabou).

        # Número do ciclo (começa em 1)
        n = len(self.historico) + 1
        self._verificar_timeouts()
        # Junta a última direção de cada peer, mais a do próprio host
        desejadas = {pid: j["dir"] for pid, j in self.jog.items() if j["dir"] is not None}
        if self.dir_host is not None:
            desejadas[self.meu_pid] = self.dir_host
        # Aqui o jogo realmente anda um passo
        registro = step(self.jogo, desejadas, self.a_eliminar, n)
        # Os desconectados já foram tratados neste ciclo, então limpa a lista
        self.a_eliminar = set()
        self.historico.append(registro)
        self._enviar_ticks()
        # O host também aplica o registro na própria tela, igual aos peers
        self.view.apply_record(registro)
        self._desenhar()
        for pid, motivo in registro["el"]:
            log.info("ciclo %d: %s eliminado (%s)", n, self.nomes.get(pid, pid), motivo)
        if registro["end"] is not None:
            self.estado = "ENDING"
            log.info("ciclo %d: FIM %s", n, registro["end"])
        return registro["end"]

    def _fase_rodando(self, proximo):
        # Loop principal da partida. A cada volta: atende a rede, lê o teclado
        # e, se já chegou a hora, executa um ciclo.
        # Devolve o resultado do fim da partida, ou None se o host saiu antes.
        tick_s = self.tick_ms / 1000
        while True:
            for dados, addr in self._receber_tudo():
                self._tratar_datagrama(dados, addr)
            self._ler_teclado()
            if self.quer_sair:
                    return None
            # Ainda não é hora do próximo ciclo: dorme um pouco pra não gastar CPU à toa
            agora = time.monotonic()
            if agora < proximo:
                time.sleep(min(proximo - agora, 0.005))
                continue
            fim = self._executar_ciclo()
            if fim is not None:
                return fim
            proximo = _proximo_instante(proximo, agora, tick_s)

    def _montar_jogadores(self):
        # Lê a lista de jogadores da partida e prepara o que o host precisa
        # saber de cada um. O host em si fica de fora de self.jog.
        self.meu_pid = self.match_start.get("host_slot", 0)
        for p in self.match_start["players"]:
            pid = p["slot"]
            self.nomes[pid] = p["name"]
            if pid == self.meu_pid:
                continue
            addr = (p["host"], int(p["port"]))
            # Ficha de cada peer:
            #   presente  = já mandou HELLO
            #   conectado = ainda está na partida (vira False ao cair)
            #   iseq      = número do último INPUT aceito
            #   dir       = última direção pedida
            #   ack       = quantos ciclos ele já confirmou ter recebido
            #   visto     = horário da última mensagem dele (pra detectar timeout)
            self.jog[pid] = {
                "addr": addr,
                "presente": False,
                "conectado": True,
                "iseq": 0,
                "dir": None,
                "ack": 0,
                "visto": None,
            }
            self.addr_para_pid[addr] = pid
        log.info("Jogadores: %s", self.jog)

    def _pid_da_origem(self, addr):
        # Descobre de qual jogador é esse endereço. None se não conhecemos.

        return self.addr_para_pid.get(addr)

    def _abrir_socket(self):
        # Abre o socket UDP do host na porta dele (o host é sempre o slot 0)
        eu = next(p for p in self.match_start["players"] if p["slot"] == 0)
        bind_host = self.config.get("peer", {}).get("bind_host", "0.0.0.0")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind((bind_host, eu["port"]))
        except OSError as e:
            # Erro mais comum: já tem outro host rodando nessa porta
            log.error("não foi possível abrir %s:%s (%s). Já existe outro host nessa porta?",
                      bind_host, eu["port"], e)
            self.sock.close()
            raise
        # Não bloqueante: recvfrom volta na hora em vez de ficar esperando chegar algo
        self.sock.setblocking(False)
        # Se a config pedir, troca o socket por um que simula perda e atraso de
        # rede. Útil pra testar o jogo em condições ruins.
        sim = self.config.get("sim")
        if sim:
            from common.simnet import SimSocket
            self.sock = SimSocket(self.sock, **sim)
            log.warning("REDE SIMULADA ativa: %s", sim)
        log.info("Host escutando em %s:%s", bind_host, eu["port"])

    def _receber_tudo(self):
        # Esvazia a fila do socket: lê tudo que chegou até agora e devolve a lista
        # de (dados, endereço). Como o socket não bloqueia, quando não tem mais
        # nada ele levanta BlockingIOError e a gente para.

        recebidos = []
        while True:
            try:
                dados, addr = self.sock.recvfrom(2048)
            except BlockingIOError:
                break                    # acabou o que tinha
            except ConnectionResetError:
                # No Windows, mandar UDP pra alguém que caiu gera esse erro na
                # leitura seguinte. Não é nada grave, só ignora.
                continue
            recebidos.append((dados, addr))
        return recebidos

    def _abortado(self):
        # Atalho pra quando a partida termina sem resultado (alguém saiu, falta de jogadores...)
        # Só manda o ABORT se ainda não foi mandado.

        if self.estado != "ABORTED":
            self._abortar("host saiu")
        return {"result": "ABORT", "winner": None}

    def _rodar_partida(self):
        # Roteiro da partida inteira, fase por fase. Qualquer fase pode
        # interromper e cair no _abortado().
        if not self._fase_collecting():
            return self._abortado()
        proximo = self._fase_countdown()
        if proximo is None:
            return self._abortado()
        # Quem não apareceu no começo já entra na lista pra ser eliminado no primeiro ciclo
        self.a_eliminar = set(self.desconectados_iniciais)
        fim = self._fase_rodando(proximo)
        if fim is None:
            return self._abortado()
        self.resultado = {"result": fim["result"], "winner": fim.get("winner")}
        self._fase_ending()
        return self.resultado

    def _resumo(self):
        # Escreve no log um resumo do que aconteceu, pra facilitar a análise depois
        caidos = sorted(pid for pid, j in self.jog.items() if not j["conectado"])
        log.info("Resumo: estado=%s ciclos=%d desconectados=%s resultado=%s motivo_abort=%s",
                 self.estado, len(self.historico), caidos, self.resultado, self.motivo_abort)
        # Só o socket simulado tem "stats", por isso o getattr com padrão None
        stats = getattr(self.sock, "stats", None)
        if stats:
            log.info("Rede simulada: %s", stats)

    def run(self):
        # Ponto de entrada: abre o socket, roda a partida e devolve o resultado.
        self._abrir_socket()
        try:
            return self._rodar_partida()
        except KeyboardInterrupt:
            # Ctrl+C depois do fim normal: o resultado já existe, então devolve ele
            if self.resultado is not None:
                log.warning("host interrompido (Ctrl+C) depois do fim da partida")
                return self.resultado
            # Ctrl+C no meio do jogo: avisa os peers e encerra como abortada
            if self.estado != "ABORTED":
                self._abortar("host interrompido (Ctrl+C)")
            return {"result": "ABORT", "winner": None}
        finally:
            # Roda sempre, com erro ou sem: registra o resumo e fecha o socket
            self._resumo()
            self.sock.close()