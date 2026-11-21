"""peer/client.py - jogador comum (peer != host).

Como o main.py usa esta classe (main.py, funcao jogar):
    resultado = Client(cfg, match_start, meu_pid).run()
    - meu_pid e o slot do jogador (lobby.slot).
    - run() devolve um dict {"result": ..., "winner": ...}:
        "WIN" / "DRAW"   a partida terminou (winner = pid do vencedor ou None)
        "HOST_LOST"      o host parou de mandar TICK
        "ABORT"          o host abortou, ou nao respondeu ao HELLO (ha "reason")
        "QUIT"           o jogador saiu com Q

Construido em partes, cada uma com teste proprio (tests/test_client_parteN.py):
  1) preparacao: ler o MATCH_START e abrir o socket UDP unico;
  2) enviar e receber mensagens, com filtro e validacao dos datagramas;
  3) handshake: HELLO com reenvio ate chegar o WELCOME;
  4) estado inicial e tela: GameView, TerminalUI e espera pelo inicio;
  5) INPUT a cada ciclo: iseq crescente (a partir de 1), direcao e ack;
  6) aplicar o TICK em ordem (registro n = ultimo + 1) e redesenhar;
  7) fim confiavel (INPUT com o ack final) e o run() que junta tudo.
"""

import ipaddress
import logging
import socket
import time

from common import protocol as proto

log = logging.getLogger("client")

JANELA = 8                                   # max. de registros por TICK (README, secao 10)
DIRECOES = ("U", "D", "L", "R")
MOTIVOS = ("WALL", "TRAIL", "HEAD", "DISC")  # motivos de eliminacao validos
TIPOS_DO_HOST = ("WELCOME", "TICK", "ABORT")  # unicos tipos que um peer aceita
PASSO_ESPERA = 0.05                          # s entre leituras de teclado/rede nas esperas
TOLERANCIA_ATRASO = 5                        # ciclos de atraso a partir dos quais o relogio e reajustado
FIM_DURACAO_S = 2.0                          # quanto tempo seguir mandando o ack final depois do fim


class ErroPreparacao(Exception):
    """MATCH_START invalido ou impossivel de usar neste peer."""


# ===================================================================
# PARTE 1: preparacao e socket
# ===================================================================

def _ip_numerico(valor):
    """True se for um IPv4 numerico utilizavel (nao 'localhost', nem 0.0.0.0)."""
    try:
        ip = ipaddress.IPv4Address(valor)
    except (ipaddress.AddressValueError, ValueError):
        return False
    return not ip.is_unspecified


def ler_match_start(match_start, meu_slot):
    """Extrai do MATCH_START o que o cliente precisa.

    match_start: dict da mensagem MATCH_START (README, secao 9).
    meu_slot: slot (pid) deste jogador, atribuido pelo lobby.

    Devolve um dict com: match_id, meu_pid, host_pid, host_addr (ip, porta),
    meu_addr (ip, porta), players (slot -> {name, addr}) e config
    ({width, height, tick_ms}). Levanta ErroPreparacao se algo estiver errado.
    """
    try:
        match_id = match_start["match_id"]
        host_pid = match_start["host_slot"]
        config = match_start["config"]
        lista = match_start["players"]
    except (KeyError, TypeError):
        raise ErroPreparacao("MATCH_START sem campos obrigatorios")

    if not isinstance(lista, list) or not lista:
        raise ErroPreparacao("MATCH_START sem lista de jogadores")

    players = {}
    for jogador in lista:
        try:
            slot, nome, ip, porta = (jogador["slot"], jogador["name"],
                                     jogador["host"], jogador["port"])
        except (KeyError, TypeError):
            raise ErroPreparacao("jogador mal formado no MATCH_START")
        if not isinstance(slot, int) or isinstance(slot, bool):
            raise ErroPreparacao("slot invalido: %r" % (slot,))
        if not _ip_numerico(ip):
            raise ErroPreparacao(
                "IP nao numerico para o slot %s: %r (o lobby deve enviar IPs numericos)"
                % (slot, ip)
            )
        if not isinstance(porta, int) or isinstance(porta, bool) or not 1024 <= porta <= 65535:
            raise ErroPreparacao("porta invalida para o slot %s: %r" % (slot, porta))
        if slot in players:
            raise ErroPreparacao("slot repetido: %s" % slot)
        players[slot] = {"name": nome, "addr": (ip, porta)}

    if host_pid not in players:
        raise ErroPreparacao("host_slot %r nao esta na lista de jogadores" % (host_pid,))
    if meu_slot not in players:
        raise ErroPreparacao("meu slot %r nao esta no MATCH_START" % (meu_slot,))
    if meu_slot == host_pid:
        raise ErroPreparacao("este processo e o host; deveria usar peer/host.py")

    return {
        "match_id": match_id,
        "meu_pid": meu_slot,
        "host_pid": host_pid,
        "host_addr": players[host_pid]["addr"],
        "meu_addr": players[meu_slot]["addr"],
        "players": players,
        "config": config,
    }


def abrir_socket(bind_host, porta):
    """Cria o UNICO socket UDP do peer, com bind na porta registrada no lobby.

    Todo envio (HELLO, INPUT) deve sair deste mesmo socket: o host valida a
    origem pelo endereco (IP e porta) informado no MATCH_START.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((bind_host, porta))
    except OSError as e:
        sock.close()
        raise ErroPreparacao("nao foi possivel abrir a porta UDP %s: %s" % (porta, e))
    return sock


# ===================================================================
# PARTE 2: validacao do conteudo das mensagens do host
# (o decode() do protocol.py so confere os campos de nivel superior;
#  o que vem DENTRO de state e recs e conferido aqui, antes de chegar
#  a tela, para um datagrama mal formado nao derrubar o cliente)
# ===================================================================

def _inteiro(v):
    """int de verdade (bool nao vale)."""
    return isinstance(v, int) and not isinstance(v, bool)


def validar_state(state, meu_pid):
    """Confere o campo 'state' do WELCOME (README, secao 10).

    Exige: width/height inteiros positivos; players = lista de
    {pid, x, y, dir} com pids unicos, dentro da arena, dir em U/D/L/R; e o
    meu pid precisa estar na lista.
    """
    if not isinstance(state, dict):
        return False
    w, h = state.get("width"), state.get("height")
    if not (_inteiro(w) and _inteiro(h) and w > 0 and h > 0):
        return False
    lista = state.get("players")
    if not isinstance(lista, list) or not lista:
        return False
    pids = set()
    for jogador in lista:
        if not isinstance(jogador, dict):
            return False
        pid, x, y = jogador.get("pid"), jogador.get("x"), jogador.get("y")
        if not (_inteiro(pid) and _inteiro(x) and _inteiro(y)):
            return False
        if not (0 <= x < w and 0 <= y < h):
            return False
        if jogador.get("dir") not in DIRECOES:
            return False
        if pid in pids:
            return False
        pids.add(pid)
    return meu_pid in pids


def validar_registro(rec):
    """Confere um registro de ciclo {n, mv, el, end} (README, secao 10)."""
    if not isinstance(rec, dict):
        return False
    n = rec.get("n")
    if not (_inteiro(n) and n >= 1):
        return False

    mv = rec.get("mv")
    if not isinstance(mv, list):
        return False
    for item in mv:
        if not (isinstance(item, (list, tuple)) and len(item) == 3
                and all(_inteiro(v) for v in item)):
            return False

    el = rec.get("el")
    if not isinstance(el, list):
        return False
    for item in el:
        if not (isinstance(item, (list, tuple)) and len(item) == 2
                and _inteiro(item[0]) and item[1] in MOTIVOS):
            return False

    if "end" not in rec:
        return False
    fim = rec["end"]
    if fim is not None:
        if not isinstance(fim, dict):
            return False
        resultado = fim.get("result")
        if resultado == "DRAW":
            pass
        elif resultado == "WIN":
            if not _inteiro(fim.get("winner")):
                return False
        else:
            return False
    return True


def validar_recs(recs):
    """Confere a lista 'recs' de um TICK: ate JANELA registros validos e
    com 'n' estritamente consecutivos. Lista vazia vale (sinal de vida)."""
    if not isinstance(recs, list) or len(recs) > JANELA:
        return False
    anterior = None
    for rec in recs:
        if not validar_registro(rec):
            return False
        if anterior is not None and rec["n"] != anterior + 1:
            return False
        anterior = rec["n"]
    return True


# ===================================================================
# PARTE 5: ritmo do INPUT
# ===================================================================

def proximo_instante(proximo, agora, tick_s):
    """Quando enviar o proximo INPUT.

    Soma o tick ao instante que estava PREVISTO (nao ao de agora), para que
    pequenos atrasos nao se acumulem. Se o atraso passar de TOLERANCIA_ATRASO
    ciclos, desiste de recuperar e recomeca a contar de agora (nao ha rajada
    de INPUTs). Mesma regra do host (peer/host.py, _proximo_instante).
    """
    proximo += tick_s
    if agora - proximo > TOLERANCIA_ATRASO * tick_s:
        proximo = agora + tick_s
    return proximo


# ===================================================================
# PARTE 4: tela
# ===================================================================

def _criar_tela():
    """Cria a TerminalUI (curses). Import tardio: so quem joga precisa de
    curses, e os testes podem trocar esta funcao por uma tela falsa."""
    from peer.ui import TerminalUI
    return TerminalUI()


# ===================================================================
# Classe Client
# ===================================================================

class Client:
    """Jogador comum. Assinatura esperada pelo main.py:

        Client(cfg, match_start, meu_pid).run()

    ui: opcional. Se vier None, as proximas partes abrirao a propria
    TerminalUI (e farao o wait_key no fim). Se vier uma TerminalUI do main,
    o main e quem faz o wait_key.
    """

    def __init__(self, cfg, match_start, meu_pid, ui=None):
        self.cfg = cfg
        self.ui = ui
        # Levanta ErroPreparacao se o MATCH_START nao servir para este peer.
        info = ler_match_start(match_start, meu_pid)
        self.match_id = info["match_id"]
        self.meu_pid = info["meu_pid"]
        self.host_pid = info["host_pid"]
        self.host_addr = info["host_addr"]
        self.meu_addr = info["meu_addr"]
        self.players = info["players"]
        self.config = info["config"]
        self.sock = None
        self.descartados = {}   # motivo -> quantidade (so para diagnostico/testes)
        # preenchidos pelo handshake (Parte 3)
        self.welcome = None            # mensagem WELCOME completa
        self.state = None              # campo 'state' do WELCOME
        self.countdown_ms = None
        self.t_welcome = None          # time.monotonic() do momento do WELCOME
        self.tick_ms = self.config.get("tick_ms", 100) if isinstance(self.config, dict) else 100
        self.dir_desejada = None       # direcao inicial da minha moto
        self.tentativas_hello = 0
        # Parte 4
        self.view = None               # GameView (copia local do estado, so p/ desenhar)
        self._tela_propria = None      # TerminalUI aberta por este Client (se o main nao passou ui)
        # Parte 5
        self.iseq = 0                  # numero do ultimo INPUT enviado (o 1o sera 1; o host rejeita iseq <= 0)
        self.ack = 0                   # ultimo ciclo (n) aplicado; a Parte 6 atualiza. 0 = nenhum
        self._prox_input = None        # instante previsto do proximo INPUT (time.monotonic)
        # Parte 6
        self._ultimo_tick = None       # time.monotonic() do ultimo TICK valido (qualquer um)
        # Parte 7
        self.fim_duracao_s = FIM_DURACAO_S

    # ---------- Parte 1: socket ----------

    def abrir(self):
        """Abre o socket UDP unico (bind na porta registrada no lobby)."""
        bind_host = (self.cfg.get("peer") or {}).get("bind_host") or "0.0.0.0"
        self.sock = abrir_socket(bind_host, self.meu_addr[1])
        return self.sock

    def fechar(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    # ---------- Parte 2: enviar e receber ----------

    def enviar(self, msg):
        """Codifica e envia msg ao host, pelo socket unico.

        Devolve True se enviou. Nunca levanta excecao de rede: um envio que
        falha e so registrado em log e o jogo continua (o proximo INPUT
        compensa, ja que o INPUT e estado).
        """
        if self.sock is None:
            log.warning("enviar() sem socket aberto")
            return False
        dados = proto.encode(msg)
        if len(dados) > proto.MAX_UDP_SIZE:
            log.warning("mensagem %s maior que %d bytes; nao enviada",
                        msg.get("t"), proto.MAX_UDP_SIZE)
            return False
        try:
            self.sock.sendto(dados, self.host_addr)
        except OSError as e:
            log.warning("falha ao enviar %s: %s", msg.get("t"), e)
            return False
        return True

    def receber(self, timeout):
        """Espera ate 'timeout' segundos por UMA mensagem valida do host.

        Datagramas ruins sao descartados em silencio (so vao para o log de
        depuracao) e a espera continua com o tempo que sobrou. Devolve o dict
        da mensagem (WELCOME, TICK ou ABORT) ou None se o tempo acabou.
        Com timeout=0, esvazia o que ja chegou e devolve a primeira valida.
        """
        if self.sock is None:
            return None
        fim = time.monotonic() + timeout
        while True:
            restante = max(fim - time.monotonic(), 0.0)
            self.sock.settimeout(restante)
            try:
                dados, origem = self.sock.recvfrom(4096)
            except (socket.timeout, BlockingIOError):
                return None
            except ConnectionResetError:
                # Windows: ICMP "porta inalcancavel" de um envio anterior.
                # Nao e um datagrama; so ignora e continua esperando.
                continue
            except OSError as e:
                log.warning("erro ao receber: %s", e)
                return None
            msg = self._filtrar(dados, origem)
            if msg is not None:
                return msg

    def _descartar(self, motivo, detalhe=""):
        self.descartados[motivo] = self.descartados.get(motivo, 0) + 1
        log.debug("datagrama descartado (%s) %s", motivo, detalhe)

    def _filtrar(self, dados, origem):
        """Aplica as checagens do README (secao 12) do lado do peer.
        Devolve a mensagem valida ou None (descartada)."""
        # 1) origem: so o host pode mandar WELCOME/TICK/ABORT
        if origem != self.host_addr:
            self._descartar("origem", "de %s:%s" % origem)
            return None
        # 2) tamanho e decodificacao (protocol.decode nunca levanta excecao)
        msg = proto.decode(dados)
        if msg is None:
            self._descartar("invalido")
            return None
        # 3) tipo: um peer so recebe WELCOME, TICK e ABORT
        tipo = msg["t"]
        if tipo not in TIPOS_DO_HOST:
            self._descartar("tipo", tipo)
            return None
        # 4) partida
        if msg["m"] != self.match_id:
            self._descartar("partida", msg["m"])
            return None
        # 5) conteudo interno
        if tipo == "WELCOME" and not validar_state(msg["state"], self.meu_pid):
            self._descartar("welcome")
            return None
        if tipo == "TICK" and not validar_recs(msg["recs"]):
            self._descartar("tick")
            return None
        return msg

    # ---------- Parte 3: handshake ----------

    def prazos(self):
        """(intervalo_do_reenvio, prazo_total) do HELLO, em segundos.
        Le timeouts.hello_retry_ms e timeouts.hello_deadline_ms da config
        (padroes do README: 500 ms e 10000 ms)."""
        t = self.cfg.get("timeouts") or {}
        retry = t.get("hello_retry_ms", 500) / 1000.0
        deadline = t.get("hello_deadline_ms", 10000) / 1000.0
        return max(retry, 0.001), max(deadline, 0.001)

    def handshake(self):
        """Envia HELLO a cada hello_retry_ms ate chegar o WELCOME.

        O host responde WELCOME a todo HELLO (inclusive repetido), entao o
        reenvio resolve tanto um HELLO perdido quanto um WELCOME perdido.

        Devolve um dict:
          {"ok": True,  "welcome": <mensagem>}                  deu certo
          {"ok": False, "motivo": "DEADLINE"}                   10 s sem WELCOME
          {"ok": False, "motivo": "ABORT", "reason": <texto>}   host mandou ABORT
        No sucesso, preenche self.welcome, self.state, self.countdown_ms,
        self.t_welcome, self.tick_ms e self.dir_desejada.

        Dentro desta espera, TICK (que o host pode mandar antes de um WELCOME
        perdido) e WELCOME invalido sao ignorados: o proximo HELLO pede outro
        WELCOME.
        """
        if self.sock is None:
            self.abrir()
        retry, deadline = self.prazos()
        inicio = time.monotonic()
        fim = inicio + deadline
        proximo_envio = inicio
        self.tentativas_hello = 0
        while True:
            agora = time.monotonic()
            if agora >= fim:
                log.warning("sem WELCOME apos %d HELLO em %.1f s",
                            self.tentativas_hello, deadline)
                return {"ok": False, "motivo": "DEADLINE"}
            if agora >= proximo_envio:
                self.enviar(proto.hello(self.match_id, self.meu_pid))
                self.tentativas_hello += 1
                proximo_envio = agora + retry
            espera = max(min(proximo_envio, fim) - time.monotonic(), 0.0)
            msg = self.receber(espera)
            if msg is None:
                continue
            if msg["t"] == "WELCOME":
                self._guardar_welcome(msg)
                log.info("WELCOME recebido apos %d HELLO", self.tentativas_hello)
                return {"ok": True, "welcome": msg}
            if msg["t"] == "ABORT":
                log.warning("ABORT do host no handshake: %s", msg["reason"])
                return {"ok": False, "motivo": "ABORT", "reason": msg["reason"]}
            # TICK antes do WELCOME: ignorar (nao ha estado para aplicar)

    def _guardar_welcome(self, msg):
        self.welcome = msg
        self.state = msg["state"]
        self.countdown_ms = msg["countdown_ms"]
        self.t_welcome = time.monotonic()
        tick = self.state.get("tick_ms")
        if isinstance(tick, int) and not isinstance(tick, bool) and tick > 0:
            self.tick_ms = tick
        for jogador in self.state["players"]:
            if jogador["pid"] == self.meu_pid:
                self.dir_desejada = jogador["dir"]

    # ---------- Parte 6: aplicar o TICK em ordem ----------

    def aplicar_tick(self, msg):
        """Aplica na tela os registros novos de um TICK, SEMPRE em ordem.

        Regra (README, secao 11): so vale o registro n = ack + 1.
          - n <= ack  : ja aplicado (o host reenvia a janela inteira); pula;
          - n == ack+1: aplica no GameView e sobe o ack;
          - n >  ack+1: falta um registro no meio; nao aplica nada daqui em
            diante. O proximo INPUT leva o ack atual e o host reenvia o que falta.
        Depois do registro com 'end', nada mais e aplicado.
        Devolve quantos registros foram aplicados.
        """
        if self.view is None:
            self.montar_view()
        if self.view.result is not None:
            return 0
        recs = msg["recs"]
        aplicados = 0
        for rec in recs:
            n = rec["n"]
            if n <= self.ack:
                continue
            if n != self.ack + 1:
                break
            self.view.apply_record(rec)
            self.ack = n
            aplicados += 1
            if self.view.result is not None:
                break
        if recs and aplicados == 0:
            if recs[-1]["n"] <= self.ack:
                self._descartar("tick_repetido")
            else:
                self._descartar("tick_com_buraco", "(ack=%d, recebi n=%d..%d)"
                                % (self.ack, recs[0]["n"], recs[-1]["n"]))
        return aplicados

    def _processar(self, msg):
        """Trata UMA mensagem valida do host durante a partida.
        Devolve um dict de saida (ABORT) ou None para continuar."""
        if msg["t"] == "ABORT":
            log.warning("ABORT do host: %s", msg["reason"])
            return {"ok": False, "motivo": "ABORT", "reason": msg["reason"]}
        if msg["t"] == "TICK":
            self._ultimo_tick = time.monotonic()     # qualquer TICK e sinal de vida
            self.aplicar_tick(msg)
        # WELCOME repetido (resposta a um HELLO reenviado): ignorar
        return None

    def _atualizar_status(self):
        """Texto da ultima linha da tela durante a partida."""
        if self.view.alive.get(self.meu_pid, True):
            self.view.status = ""
        else:
            self.view.status = "Voce foi eliminado. Assistindo ate o fim...  (Q: sair)"

    def rodar_partida(self, tick_inicial=None):
        """Laco principal da partida (estado PLAYING / SPECTATING).

        A cada volta: desenha, le o teclado, envia o INPUT se for a hora e
        aplica os TICKs que chegaram (todos os que ja estao na fila, para
        recuperar rapido depois de uma pausa).

        tick_inicial: o TICK devolvido por aguardar_inicio(), ainda nao
        aplicado. Quem foi eliminado continua no laco (assistindo): segue
        aplicando TICK e mandando INPUT ate o fim.

        Devolve:
          {"ok": True,  "fim": {"result": "WIN"/"DRAW", ["winner": pid]}}
          {"ok": False, "motivo": "ABORT", "reason": <texto>}
          {"ok": False, "motivo": "QUIT"}        (jogador apertou Q)
          {"ok": False, "motivo": "HOST_LOST"}   (sem TICK por host_timeout_ms)
        """
        if self.ui is None:
            raise RuntimeError("rodar_partida() exige a tela aberta (abrir_tela())")
        view = self.view or self.montar_view()
        limite = self.host_timeout_s()
        self._ultimo_tick = time.monotonic()
        if tick_inicial is not None:
            self.aplicar_tick(tick_inicial)
        while True:
            self._atualizar_status()
            self.ui.draw(view)
            if view.result is not None:
                return {"ok": True, "fim": view.result}
            if self.ler_teclado() == "QUIT":
                return {"ok": False, "motivo": "QUIT"}
            self.enviar_input_se_for_hora()
            espera = PASSO_ESPERA
            if self._prox_input is not None:
                espera = max(min(PASSO_ESPERA, self._prox_input - time.monotonic()), 0.0)
            msg = self.receber(espera)
            while msg is not None:
                saida = self._processar(msg)
                if saida is not None:
                    return saida
                msg = self.receber(0)
            if time.monotonic() - self._ultimo_tick > limite:
                log.warning("sem TICK do host por %.1f s durante a partida", limite)
                return {"ok": False, "motivo": "HOST_LOST"}

    # ---------- Parte 5: INPUT a cada ciclo ----------

    def ler_teclado(self):
        """Le o teclado sem bloquear (ui.poll_input) e guarda a direcao pedida.

        Devolve "QUIT" se o jogador apertou Q, senao None. Uma direcao so
        troca dir_desejada; quem a envia e enviar_input(). Direcao oposta a que a moto
        segue tambem e guardada: o host a ignora (README, secao 8).
        """
        tecla = self.ui.poll_input()
        if tecla == "QUIT":
            return "QUIT"
        if tecla in DIRECOES:
            self.dir_desejada = tecla
        return None

    def enviar_input(self):
        """Envia UM INPUT com a direcao desejada e o ack atual.

        O INPUT e estado ("a direcao desejada e X"), por isso e enviado todo
        ciclo mesmo sem tecla nova: a perda de um e compensada pelo seguinte.
        O iseq cresce a cada envio (o host descarta iseq repetido ou antigo).
        Devolve True se enviou; False se ainda nao ha direcao desejada ou o
        envio falhou.
        """
        if self.dir_desejada is None:
            log.debug("INPUT nao enviado: ainda sem direcao desejada")
            return False
        self.iseq += 1
        return self.enviar(proto.input_msg(self.match_id, self.meu_pid, self.iseq,
                                           self.dir_desejada, self.ack))

    def enviar_input_se_for_hora(self, agora=None):
        """Chame a cada volta do laco: envia um INPUT a cada tick_ms.

        O primeiro sai na hora; os seguintes a cada tick_ms, sem acumular
        atraso (ver proximo_instante). 'agora' existe para testar com um
        relogio falso. Devolve True se um INPUT foi enviado nesta chamada.
        """
        agora = time.monotonic() if agora is None else agora
        if self._prox_input is None:
            self._prox_input = agora
        if agora < self._prox_input:
            return False
        enviado = self.enviar_input()
        self._prox_input = proximo_instante(self._prox_input, agora, self.tick_ms / 1000.0)
        return enviado

    # ---------- Parte 4: estado inicial e tela ----------

    def host_timeout_s(self):
        """Tempo sem TICK do host que o torna 'perdido' (timeouts.host_timeout_ms,
        padrao 3000 ms)."""
        t = self.cfg.get("timeouts") or {}
        return max(t.get("host_timeout_ms", 3000) / 1000.0, 0.001)

    def montar_view(self):
        """Cria o GameView a partir do WELCOME (exige o handshake feito)."""
        if self.state is None:
            raise RuntimeError("montar_view() exige o handshake feito (sem WELCOME)")
        from peer.ui import GameView
        nomes = {pid: jogador["name"] for pid, jogador in self.players.items()}
        self.view = GameView(self.meu_pid, nomes)
        self.view.load_welcome(self.state)
        return self.view

    def abrir_tela(self):
        """Devolve a ui a usar. Se o main passou uma, usa essa (e o main cuida
        de fecha-la e do wait_key). Se nao, abre a propria TerminalUI, que
        deve ser fechada com fechar_tela()."""
        if self.ui is None:
            tela = _criar_tela()
            self.ui = tela.__enter__()
            self._tela_propria = tela
        return self.ui

    def fechar_tela(self):
        """Fecha so a tela que este Client abriu (nunca a que veio do main)."""
        if self._tela_propria is not None:
            tela, self._tela_propria = self._tela_propria, None
            self.ui = None
            tela.__exit__(None, None, None)

    def aguardar_inicio(self):
        """Mostra a arena e espera a partida comecar (READY -> PLAYING).

        A partida comeca no primeiro TICK que traz registros. Antes disso o
        host manda TICK vazio (sinal de vida) enquanto espera os outros
        jogadores e durante a contagem; nao da para distinguir uma coisa da
        outra, entao a tela mostra apenas uma mensagem de espera.

        Durante a espera, as teclas de direcao ja atualizam dir_desejada e o
        INPUT ja e enviado a cada tick_ms (sinal de vida, README secao 10).
        O primeiro TICK com registros NAO e aplicado aqui: vai no retorno,
        para a Parte 6 aplicar em ordem.

        Devolve:
          {"ok": True,  "tick": <mensagem TICK com recs>}
          {"ok": False, "motivo": "ABORT", "reason": <texto>}
          {"ok": False, "motivo": "QUIT"}          (jogador apertou Q)
          {"ok": False, "motivo": "HOST_LOST"}     (sem TICK por host_timeout_ms)
        """
        if self.ui is None:
            raise RuntimeError("aguardar_inicio() exige a tela aberta (abrir_tela())")
        view = self.view or self.montar_view()
        view.status = "Conectado! Aguardando o inicio da partida...  (Q: sair)"
        limite = self.host_timeout_s()
        ultimo_tick = self.t_welcome if self.t_welcome is not None else time.monotonic()
        while True:
            self.ui.draw(view)
            if self.ler_teclado() == "QUIT":
                return {"ok": False, "motivo": "QUIT"}
            self.enviar_input_se_for_hora()      # sinal de vida desde o WELCOME (Parte 5)
            msg = self.receber(PASSO_ESPERA)
            agora = time.monotonic()
            if msg is not None:
                if msg["t"] == "ABORT":
                    return {"ok": False, "motivo": "ABORT", "reason": msg["reason"]}
                if msg["t"] == "TICK":
                    ultimo_tick = agora
                    if msg["recs"]:
                        return {"ok": True, "tick": msg}
                # WELCOME repetido (resposta a um HELLO reenviado): ignorar
            if agora - ultimo_tick > limite:
                log.warning("sem TICK do host por %.1f s antes do inicio", limite)
                return {"ok": False, "motivo": "HOST_LOST"}

    # ---------- Parte 7: fim confiavel e run() ----------

    def confirmar_fim(self, duracao_s=None):
        """Depois de ver o fim, segue mandando INPUT com o ack FINAL por
        duracao_s (padrao fim_duracao_s, ~2 s; README, secao 11).

        Por que: o host so encerra (estado ENDING) quando todos os peers
        confirmam o ultimo ciclo, e nao existe resposta do host a esse ack. Um
        unico INPUT pode se perder; varios, um por ciclo, garantem que chega.
        Durante a espera, o que o host reenviar (TICK, WELCOME) e ignorado e a
        tela continua desenhada com o resultado.
        """
        duracao = self.fim_duracao_s if duracao_s is None else duracao_s
        limite = time.monotonic() + duracao
        self._prox_input = None                  # o primeiro INPUT sai na hora
        while time.monotonic() < limite:
            if self.ui is not None and self.view is not None:
                self.ui.draw(self.view)
            self.enviar_input_se_for_hora()
            espera = PASSO_ESPERA
            if self._prox_input is not None:
                espera = max(min(PASSO_ESPERA, self._prox_input - time.monotonic()), 0.0)
            espera = min(espera, max(limite - time.monotonic(), 0.0))
            while self.receber(espera) is not None:
                espera = 0.0                     # esvazia a fila e descarta

    def _resultado(self, r):
        """Converte o retorno de aguardar_inicio/rodar_partida/handshake no
        dict que o main.py espera: {"result": ..., "winner": ...}."""
        if r.get("ok"):
            fim = r["fim"]
            return {"result": fim["result"], "winner": fim.get("winner")}
        motivo = r.get("motivo")
        if motivo == "HOST_LOST":
            return {"result": "HOST_LOST", "winner": None}
        if motivo == "QUIT":
            return {"result": "QUIT", "winner": None}
        if motivo == "DEADLINE":
            razao = "o host nao respondeu ao HELLO"
        else:
            razao = r.get("reason") or "partida abortada"
        return {"result": "ABORT", "winner": None, "reason": razao}

    def _mostrar_final(self, r):
        """Deixa na ultima linha da tela o motivo do fim (se nao foi uma vitoria/empate)."""
        if self.ui is None or self.view is None or r.get("ok"):
            return
        motivo = r.get("motivo")
        if motivo == "HOST_LOST":
            self.view.status = "O host parou de responder. Partida encerrada.  (pressione qualquer tecla)"
        elif motivo == "ABORT":
            self.view.status = "Partida encerrada pelo host (%s).  (pressione qualquer tecla)" % r.get("reason")
        else:
            return
        self.ui.draw(self.view)

    def run(self):
        """Joga a partida inteira como peer e devolve {"result", "winner"}.

        Ordem: abrir socket -> handshake -> tela -> esperar inicio -> jogar ->
        confirmar o fim. Sempre fecha o socket e (so se foi este Client que a
        abriu) a tela, mesmo com erro ou Ctrl+C: o terminal volta ao normal.
        Se a ui veio do main, o main cuida do wait_key; se o Client abriu a
        propria tela, ele espera uma tecla no fim (menos quando o jogador saiu com Q).
        """
        try:
            self.abrir()
        except ErroPreparacao as e:
            log.error("nao foi possivel preparar o peer: %s", e)
            return {"result": "ABORT", "winner": None, "reason": str(e)}
        try:
            hs = self.handshake()
            if not hs["ok"]:
                return self._resultado(hs)
            self.abrir_tela()
            self.montar_view()
            r = self.aguardar_inicio()
            if r["ok"]:
                r = self.rodar_partida(tick_inicial=r["tick"])
            if r["ok"]:
                self.confirmar_fim()
            self._mostrar_final(r)
            if self._tela_propria is not None and r.get("motivo") != "QUIT":
                self.ui.wait_key()
            resultado = self._resultado(r)
            log.info("partida terminou para o peer %s: %s", self.meu_pid, resultado)
            return resultado
        except KeyboardInterrupt:
            log.warning("peer interrompido (Ctrl+C)")
            return {"result": "ABORT", "winner": None, "reason": "interrompido (Ctrl+C)"}
        finally:
            self.fechar_tela()
            self.fechar()
