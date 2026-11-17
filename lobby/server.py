# lobby/server.py
"""Servidor de lobby do DualNode (TCP).

O lobby só faz descoberta: registra jogadores, mantém as salas e, no
START_MATCH, entrega a todos o MATCH_START com os endereços UDP de cada um.
Depois disso o jogo corre direto entre os peers (UDP) e o lobby pode até cair.

Um único thread: o selectors avisa quais sockets têm dados para ler, e cada
conexão tem o seu próprio buffer de bytes. O TCP é um FLUXO de bytes, não de
mensagens: um recv() pode trazer meia linha, uma linha ou várias. Por isso as
mensagens são separadas pelo "\\n" e o que sobra fica guardado para o próximo recv.

Rodar (da raiz do projeto):
    python3 -m lobby.server --config config.json
    python3 -m lobby.server --host 0.0.0.0 --port 5000

Testar sem cliente pronto:
    nc 127.0.0.1 5000
    {"v":1,"t":"REGISTER","name":"Ana","udp_port":6001}
"""
import ipaddress
import logging
import os
import re
import selectors
import socket
import sys
import time

from common import protocol as p
from common.config import ConfigError, build_parser, load_config

log = logging.getLogger("lobby")

NOME_OK = re.compile(r"[A-Za-z0-9_-]{1,16}")
MAX_NOME_SALA = 24
MAX_FORMATO_SEGUIDOS = 3     # BAD_FORMAT seguidos antes de fechar a conexão
SEND_TIMEOUT_S = 2.0         # um cliente que não lê não pode travar o lobby inteiro

# Estados de cada conexão (README, seção 11)
CONNECTED = "CONNECTED"
REGISTERED = "REGISTERED"
IN_ROOM = "IN_ROOM"
IN_GAME = "IN_GAME"

# Mensagens aceitas em cada estado. Fora disso: ERROR BAD_STATE.
# (PING é respondido em qualquer estado, fora desta tabela.)
ACEITAS = {
    CONNECTED: {"REGISTER", "PONG"},
    REGISTERED: {"LIST_MATCHES", "CREATE_MATCH", "JOIN_MATCH", "PONG"},
    IN_ROOM: {"LEAVE_MATCH", "START_MATCH", "LIST_MATCHES", "PONG"},
    IN_GAME: {"MATCH_END"},
}

# Só o host manda MATCH_END. Os outros jogadores simplesmente voltam ao menu.
# Então, se alguém em IN_GAME manda um pedido do menu, a partida dele acabou:
# volta para REGISTERED e o pedido é atendido normalmente.
VOLTA_DO_JOGO = {"LIST_MATCHES", "CREATE_MATCH", "JOIN_MATCH"}


class Jogador:
    """Uma conexão TCP com o lobby."""

    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr                 # (ip, porta) de origem do TCP
        self.buf = b""                   # bytes recebidos que ainda não formam linha
        self.estado = CONNECTED
        self.ativo = True
        self.player_id = None
        self.nome = None
        self.udp_host = None
        self.udp_port = None
        self.sala = None                 # match_id
        self.slot = None
        self.formato_ruim = 0            # BAD_FORMAT seguidos
        self.visto = time.monotonic()    # último instante em que chegou qualquer dado

    def __str__(self):
        return self.nome or "%s:%d" % self.addr


class Sala:
    def __init__(self, match_id, nome, criador, max_players):
        self.match_id = match_id
        self.nome = nome
        self.criador = criador
        self.max_players = max_players
        self.slots = {}                  # slot -> Jogador

    def slot_livre(self):
        """Menor slot vago (o slot vira o pid na partida)."""
        for s in range(self.max_players):
            if s not in self.slots:
                return s
        return None

    def lista(self):
        return [{"slot": s, "name": j.nome} for s, j in sorted(self.slots.items())]

    def resumo(self):
        return {"match_id": self.match_id, "name": self.nome,
                "host_name": self.criador.nome, "players": len(self.slots),
                "max_players": self.max_players}


def descobrir_ip_lan():
    """IP desta máquina na rede local, ou None.

    connect() em UDP não envia nada: só faz o sistema escolher a interface de
    saída, e getsockname() mostra o IP dela.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()
    return None if ip.startswith("127.") or ip == "0.0.0.0" else ip


class LobbyServer:
    def __init__(self, cfg, bind_host="0.0.0.0", port=None):
        self.game = dict(cfg["lobby"]["game"])          # arena e velocidade vão no MATCH_START
        self.ping_s = cfg["timeouts"]["lobby_ping_ms"] / 1000.0
        self.dead_s = cfg["timeouts"]["lobby_dead_ms"] / 1000.0
        porta = cfg["lobby"]["port"] if port is None else port

        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind((bind_host, porta))
        self.srv.listen()
        self.srv.setblocking(False)

        self.sel = selectors.DefaultSelector()
        self.sel.register(self.srv, selectors.EVENT_READ, None)

        self.jogadores = {}          # socket -> Jogador
        self.salas = {}              # match_id -> Sala (só salas que ainda não começaram)
        self.iniciadas = set()       # match_id já iniciados (para responder MATCH_STARTED)
        self.para_remover = []       # quem falhou no envio; removido no fim da volta do laço
        self.prox_id = 1
        self.prox_sala = 1
        self.ultimo_ping = time.monotonic()
        self.rodando = False
        self.ip_lan = descobrir_ip_lan()

    @property
    def porta(self):
        return self.srv.getsockname()[1]

    # ---------- laço principal ----------

    def serve_forever(self):
        self.rodando = True
        log.info("lobby escutando em %s:%d (IP na rede: %s)",
                 *self.srv.getsockname(), self.ip_lan or "desconhecido")
        try:
            while self.rodando:
                for chave, _ in self.sel.select(timeout=0.2):
                    if chave.data is None:
                        self._aceitar()
                    else:
                        self._ler(chave.data)
                self._verificar_vida()
                self._limpar()
        finally:
            self.fechar()

    def parar(self):
        self.rodando = False

    def fechar(self):
        for j in list(self.jogadores.values()):
            self._remover(j, "lobby encerrado")
        try:
            self.sel.unregister(self.srv)
        except (KeyError, ValueError):
            pass
        self.srv.close()
        self.sel.close()

    # ---------- conexões ----------

    def _aceitar(self):
        try:
            sock, addr = self.srv.accept()
        except OSError:
            return
        sock.settimeout(SEND_TIMEOUT_S)
        j = Jogador(sock, addr)
        self.jogadores[sock] = j
        self.sel.register(sock, selectors.EVENT_READ, j)
        log.info("nova conexão de %s:%d", *addr)

    def _ler(self, j):
        try:
            dados = j.sock.recv(4096)
        except OSError as e:
            self._remover(j, "erro de leitura: %s" % e)
            return
        if not dados:                       # b"" = o outro lado fechou (FIN)
            self._remover(j, "fechou a conexão")
            return
        j.visto = time.monotonic()

        # Enquadramento: junta com o que sobrou e corta em cada "\n".
        j.buf += dados
        while b"\n" in j.buf:
            linha, j.buf = j.buf.split(b"\n", 1)
            if len(linha) > p.MAX_LINE_SIZE:
                self._remover(j, "linha maior que %d bytes" % p.MAX_LINE_SIZE)
                return
            if linha.strip():
                self._processar_linha(j, linha)
                if not j.ativo:
                    return
        if len(j.buf) > p.MAX_LINE_SIZE:    # muitos bytes e nenhum "\n"
            self._remover(j, "linha maior que %d bytes" % p.MAX_LINE_SIZE)

    def _remover(self, j, motivo):
        if not j.ativo:
            return
        j.ativo = False
        log.info("removendo %s: %s", j, motivo)
        if j.estado == IN_ROOM:
            self._sair_da_sala(j)
        try:
            self.sel.unregister(j.sock)
        except (KeyError, ValueError):
            pass
        j.sock.close()
        self.jogadores.pop(j.sock, None)

    def _limpar(self):
        while self.para_remover:
            self._remover(self.para_remover.pop(), "falha ao enviar")

    def _enviar(self, j, msg):
        if not j.ativo:
            return
        try:
            j.sock.sendall(p.encode_line(msg))
        except OSError as e:
            # Não remove aqui para não mexer nas salas no meio de um laço.
            log.warning("falha ao enviar %s para %s: %s", msg["t"], j, e)
            if j not in self.para_remover:
                self.para_remover.append(j)

    def _erro(self, j, code, texto):
        log.info("ERROR %s para %s: %s", code, j, texto)
        self._enviar(j, p.error(code, texto))

    def _verificar_vida(self):
        """PING periódico e remoção de quem ficou mudo.

        Quem está IN_GAME não recebe PING: durante a partida o jogador não lê o
        TCP. A remoção por silêncio vale em IN_ROOM, onde o cliente fica num
        select e responde PONG, e em CONNECTED, porque o cliente de verdade manda
        REGISTER assim que conecta (quem abre a conexão e fica mudo é lixo).
        No menu (REGISTERED) o jogador pode ficar parado digitando, então ali
        quem detecta a saída é o fechamento da conexão.
        """
        agora = time.monotonic()
        for j in list(self.jogadores.values()):
            if j.estado in (CONNECTED, IN_ROOM) and agora - j.visto > self.dead_s:
                self._remover(j, "sem resposta ao PING por %.0f s" % self.dead_s)
        if agora - self.ultimo_ping >= self.ping_s:
            self.ultimo_ping = agora
            for j in list(self.jogadores.values()):
                if j.estado != IN_GAME:
                    self._enviar(j, p.ping())

    # ---------- mensagens ----------

    def _processar_linha(self, j, linha):
        msg, codigo = p.classify_line(linha)
        if msg is None:
            if codigo == "BAD_FORMAT":
                j.formato_ruim += 1
                self._erro(j, "BAD_FORMAT", "a linha não é um JSON válido do protocolo")
                if j.formato_ruim >= MAX_FORMATO_SEGUIDOS:
                    self._remover(j, "%d linhas inválidas seguidas" % MAX_FORMATO_SEGUIDOS)
            elif codigo == "UNKNOWN_TYPE":
                self._erro(j, "UNKNOWN_TYPE", "tipo de mensagem desconhecido")
            else:
                self._erro(j, "INVALID_PARAM", "campo obrigatório faltando ou com tipo errado")
            return
        j.formato_ruim = 0
        t = msg["t"]

        if t == "PING":
            self._enviar(j, p.pong())
            return

        if j.estado == IN_GAME and t in VOLTA_DO_JOGO:
            log.info("%s voltou da partida %s", j, j.sala)
            self._voltar_ao_menu(j)

        if t not in ACEITAS[j.estado]:
            if j.estado == IN_GAME:
                log.debug("ignorando %s de %s (em partida)", t, j)
            else:
                self._erro(j, "BAD_STATE", "%s não é aceito no estado %s" % (t, j.estado))
            return
        if t == "PONG":
            return

        tratar = getattr(self, "_on_" + t.lower())
        try:
            tratar(j, msg)
        except Exception:                   # bug nosso não pode derrubar o lobby
            log.exception("erro tratando %s de %s", t, j)
            self._erro(j, "INVALID_PARAM", "erro interno ao tratar %s" % t)

    def _on_register(self, j, msg):
        nome, porta = msg["name"], msg["udp_port"]
        if not NOME_OK.fullmatch(nome):
            return self._erro(j, "INVALID_PARAM", "nome deve ter 1 a 16 caracteres [A-Za-z0-9_-]")
        if not 1024 <= porta <= 65535:
            return self._erro(j, "INVALID_PARAM", "udp_port deve estar entre 1024 e 65535")

        host = msg.get("udp_host")
        if host is None:
            host = j.addr[0]                # IP de origem da conexão TCP
        try:
            ip = ipaddress.ip_address(host)
        except (ValueError, TypeError):
            return self._erro(j, "INVALID_PARAM", "udp_host deve ser um IPv4 numérico")
        if ip.version != 4 or ip.is_unspecified:
            return self._erro(j, "INVALID_PARAM", "udp_host deve ser um IPv4 alcançável")
        if ip.is_loopback and self.ip_lan:
            # 127.0.0.1 só funciona na mesma máquina; para os outros jogadores
            # o endereço certo é o IP desta máquina na rede.
            log.info("%s veio de %s; anunciando %s no lugar", nome, host, self.ip_lan)
            host = self.ip_lan

        if any(o.nome == nome for o in self.jogadores.values() if o is not j):
            return self._erro(j, "NAME_TAKEN", "o nome %s já está em uso" % nome)

        j.nome, j.udp_host, j.udp_port = nome, str(host), porta
        j.player_id = self.prox_id
        self.prox_id += 1
        j.estado = REGISTERED
        log.info("REGISTER %s (id %d) UDP %s:%d", nome, j.player_id, j.udp_host, porta)
        self._enviar(j, p.register_ok(j.player_id))

    def _on_list_matches(self, j, msg):
        self._enviar(j, p.match_list([s.resumo() for s in self.salas.values()]))

    def _on_create_match(self, j, msg):
        nome, maximo = msg["name"].strip(), msg["max_players"]
        if not 1 <= len(nome) <= MAX_NOME_SALA:
            return self._erro(j, "INVALID_PARAM", "nome da sala deve ter 1 a %d caracteres" % MAX_NOME_SALA)
        if maximo not in (3, 4):
            return self._erro(j, "INVALID_PARAM", "max_players deve ser 3 ou 4")

        mid = "m%d" % self.prox_sala
        self.prox_sala += 1
        sala = Sala(mid, nome, j, maximo)
        sala.slots[0] = j                   # o criador é o host: slot 0
        self.salas[mid] = sala
        j.sala, j.slot, j.estado = mid, 0, IN_ROOM
        log.info("CREATE_MATCH %s '%s' por %s (máx %d)", mid, nome, j, maximo)
        self._enviar(j, p.match_created(mid, 0))

    def _on_join_match(self, j, msg):
        mid = msg["match_id"]
        if mid in self.iniciadas:
            return self._erro(j, "MATCH_STARTED", "a partida %s já começou" % mid)
        sala = self.salas.get(mid)
        if sala is None:
            return self._erro(j, "MATCH_NOT_FOUND", "não existe partida %s" % mid)
        slot = sala.slot_livre()
        if slot is None:
            return self._erro(j, "MATCH_FULL", "a partida %s está cheia" % mid)
        if any((o.udp_host, o.udp_port) == (j.udp_host, j.udp_port) for o in sala.slots.values()):
            return self._erro(j, "INVALID_PARAM",
                              "outro jogador da sala já usa %s:%d; use outra --udp-port"
                              % (j.udp_host, j.udp_port))

        sala.slots[slot] = j
        j.sala, j.slot, j.estado = mid, slot, IN_ROOM
        log.info("JOIN_MATCH %s entrou em %s no slot %d", j, mid, slot)
        self._enviar(j, p.join_ok(mid, slot, sala.lista()))
        self._avisar_sala(sala, p.player_joined(slot, j.nome), exceto=j)

    def _on_leave_match(self, j, msg):
        log.info("LEAVE_MATCH %s saiu de %s", j, j.sala)
        self._sair_da_sala(j)
        j.estado = REGISTERED

    def _on_start_match(self, j, msg):
        sala = self.salas[j.sala]
        if j is not sala.criador:
            return self._erro(j, "NOT_CREATOR", "só o criador pode iniciar a partida")
        if len(sala.slots) < 3:
            return self._erro(j, "NOT_ENOUGH_PLAYERS", "são necessários pelo menos 3 jogadores")

        players = [{"slot": s, "name": o.nome, "host": o.udp_host, "port": o.udp_port}
                   for s, o in sorted(sala.slots.items())]
        inicio = p.match_start(sala.match_id, 0, dict(self.game), players)
        del self.salas[sala.match_id]
        self.iniciadas.add(sala.match_id)
        for o in sala.slots.values():
            o.estado = IN_GAME
            self._enviar(o, inicio)
        log.info("MATCH_START %s: %s", sala.match_id,
                 ", ".join("%d=%s@%s:%d" % (q["slot"], q["name"], q["host"], q["port"]) for q in players))

    def _on_match_end(self, j, msg):
        log.info("MATCH_END %s informado por %s: vencedor %s", j.sala, j, msg["winner"])
        self._voltar_ao_menu(j)

    # ---------- salas ----------

    def _voltar_ao_menu(self, j):
        j.sala, j.slot, j.estado = None, None, REGISTERED

    def _avisar_sala(self, sala, msg, exceto=None):
        for o in list(sala.slots.values()):
            if o is not exceto:
                self._enviar(o, msg)

    def _sair_da_sala(self, j):
        """Tira j da sala. Se j é o criador, a sala é cancelada para todos."""
        sala = self.salas.get(j.sala)
        slot = j.slot
        j.sala, j.slot = None, None
        if sala is None:
            return
        sala.slots.pop(slot, None)
        if j is sala.criador:
            del self.salas[sala.match_id]
            log.info("sala %s cancelada: o criador saiu", sala.match_id)
            for o in list(sala.slots.values()):
                self._voltar_ao_menu(o)
                self._enviar(o, p.match_cancelled("o criador saiu da sala"))
        else:
            self._avisar_sala(sala, p.player_left(slot, j.nome))


def configurar_log(nivel="INFO"):
    """Log no terminal e em logs/lobby.log. nivel vem de debug.log_level."""
    os.makedirs("logs", exist_ok=True)
    formato = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    raiz = logging.getLogger()
    valor = getattr(logging, str(nivel).upper(), None)
    raiz.setLevel(valor if isinstance(valor, int) else logging.INFO)
    for h in (logging.FileHandler("logs/lobby.log", encoding="utf-8"), logging.StreamHandler()):
        h.setFormatter(formato)
        raiz.addHandler(h)


def main():
    try:
        cfg, args = load_config(parser=build_parser())
    except ConfigError as e:
        print("Erro de configuração: %s" % e)
        sys.exit(2)
    configurar_log(cfg["debug"]["log_level"])
    # --host define onde o lobby escuta; sem ele, todas as interfaces.
    bind = args.lobby_host or "0.0.0.0"
    try:
        servidor = LobbyServer(cfg, bind_host=bind)
    except OSError as e:
        log.error("não foi possível abrir %s:%d: %s", bind, cfg["lobby"]["port"], e)
        sys.exit(1)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        log.info("lobby encerrado (Ctrl+C)")


if __name__ == "__main__":
    main()
