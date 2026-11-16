"""peer/client.py - jogador comum (peer != host).

NOTA (estado atual): este arquivo contem as PARTES 1 e 2:
  1) preparacao (ler o MATCH_START) e socket UDP unico;
  2) enviar e receber mensagens, com filtro e validacao dos datagramas.
O metodo Client.run() ainda esta VAZIO: apenas levanta NotImplementedError.
Se alguem iniciar uma partida como peer com esta versao, o main.py vai falhar
nessa chamada. As proximas partes (handshake, INPUT, TICK, falhas) serao
adicionadas aqui, uma de cada vez.

Como o main.py usa esta classe (main.py, funcao jogar):
    resultado = Client(cfg, match_start, meu_pid).run()
    - meu_pid e o slot do jogador (lobby.slot).
    - run() deve devolver um dict com "result" ("WIN", "DRAW", "HOST_LOST" ou
      outro valor, que o main trata como partida encerrada) e, se houver,
      "winner".
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

    def run(self):
        """VAZIO por enquanto (Partes 1 e 2). Sera preenchido nas proximas."""
        raise NotImplementedError("Client.run() ainda nao foi implementado")
