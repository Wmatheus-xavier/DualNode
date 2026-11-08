# peer/lobby_client.py
import logging
import select
import socket
import time

from common import protocol as p

log = logging.getLogger("lobby_client")


class LobbyError(Exception):
    """O lobby respondeu ERROR. Tem .code e .msg."""

    def __init__(self, code, msg):
        super().__init__(f"{code}: {msg}")
        self.code = code
        self.msg = msg


class LobbyDown(Exception):
    """A conexão TCP com o lobby caiu ou o lobby ficou mudo."""


class LobbyClient:
    # eventos que chegam sem o jogador ter pedido nada
    EVENTOS = ("PLAYER_JOINED", "PLAYER_LEFT", "MATCH_START", "MATCH_CANCELLED", "ERROR")

    def __init__(self, host, port, name, udp_port, udp_host=None,
                 request_timeout=5.0, dead_ms=15000):
        self.host = host
        self.port = port
        self.name = name
        self.udp_port = udp_port
        self.udp_host = udp_host
        self.request_timeout = request_timeout
        self.dead_s = dead_ms / 1000.0
        self.sock = None
        self.buf = p.LineBuffer()
        self.eventos = []          # eventos assíncronos ainda não entregues
        self.player_id = None
        self.match_id = None
        self.slot = None
        self.ultimo_dado = time.monotonic()

    # ---------- conexão ----------

    def connect(self):
        try:
            self.sock = socket.create_connection((self.host, self.port),
                                                 timeout=self.request_timeout)
        except OSError as e:
            raise LobbyDown(f"não foi possível conectar ao lobby {self.host}:{self.port}: {e}")
        self.sock.settimeout(None)
        self.ultimo_dado = time.monotonic()
        resp = self._pedir(p.register(self.name, self.udp_port, self.udp_host), "REGISTER_OK")
        self.player_id = resp["player_id"]
        log.info("registrado no lobby como %s (id=%s)", self.name, self.player_id)

    def fileno(self):
        return self.sock.fileno() if self.sock else -1

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    # ---------- chamadas ----------

    def create_match(self, name, max_players):
        resp = self._pedir(p.create_match(name, max_players), "MATCH_CREATED")
        self.match_id = resp["match_id"]
        self.slot = resp["slot"]
        return self.match_id

    def list_matches(self):
        return self._pedir(p.list_matches(), "MATCH_LIST")["matches"]

    def join_match(self, match_id):
        resp = self._pedir(p.join_match(match_id), "JOIN_OK")
        self.match_id = resp["match_id"]
        self.slot = resp["slot"]
        return resp["players"]

    def leave_match(self):
        # LEAVE_MATCH não tem resposta no protocolo: só envia
        self._enviar(p.leave_match())
        self.match_id = None
        self.slot = None

    def start_match(self):
        # a resposta é o MATCH_START (ou ERROR), que chega por poll_events
        self._enviar(p.start_match())

    def match_end(self, winner):
        """Melhor esforço: se o lobby caiu, só registra em log."""
        try:
            self._enviar(p.match_end(winner))
        except LobbyDown:
            log.warning("lobby indisponível; MATCH_END não enviado")

    # ---------- eventos ----------

    def poll_events(self, timeout=0):
        """Devolve lista de eventos (dicts). Levanta LobbyDown se a conexão caiu."""
        saida = list(self.eventos)
        self.eventos.clear()
        if not self.sock:
            raise LobbyDown("sem conexão com o lobby")
        pronto, _, _ = select.select([self.sock], [], [], timeout)
        if pronto:
            for msg in self._ler():
                if msg is None:
                    continue
                if msg["t"] == "PING":
                    self._enviar(p.pong())
                else:
                    saida.append(msg)
        elif time.monotonic() - self.ultimo_dado > self.dead_s:
            raise LobbyDown("lobby sem enviar dados há muito tempo")
        return saida

    # ---------- internos ----------

    def _enviar(self, msg):
        if not self.sock:
            raise LobbyDown("sem conexão com o lobby")
        try:
            self.sock.sendall(p.encode_line(msg))
        except OSError as e:
            self.close()
            raise LobbyDown(f"falha ao enviar ao lobby: {e}")

    def _ler(self):
        """Lê o que houver no socket e devolve as mensagens decodificadas."""
        try:
            dados = self.sock.recv(4096)
        except OSError as e:
            self.close()
            raise LobbyDown(f"erro de leitura no lobby: {e}")
        if not dados:
            self.close()
            raise LobbyDown("o lobby fechou a conexão")
        self.ultimo_dado = time.monotonic()
        try:
            return self.buf.feed(dados)
        except p.LineTooLong:
            self.close()
            raise LobbyDown("o lobby enviou uma linha grande demais")

    def _pedir(self, msg, esperado):
        """Envia msg e espera a resposta do tipo 'esperado' (ou ERROR).

        Mensagens assíncronas que chegarem no meio ficam em self.eventos.
        """
        self._enviar(msg)
        limite = time.monotonic() + self.request_timeout
        while True:
            restante = limite - time.monotonic()
            if restante <= 0:
                raise LobbyDown(f"o lobby não respondeu a {msg['t']}")
            pronto, _, _ = select.select([self.sock], [], [], restante)
            if not pronto:
                continue
            achada = None
            for resp in self._ler():
                if resp is None:
                    continue
                if resp["t"] == esperado and achada is None:
                    achada = resp
                elif resp["t"] == "ERROR" and achada is None:
                    raise LobbyError(resp["code"], resp["msg"])
                elif resp["t"] == "PING":
                    self._enviar(p.pong())
                elif resp["t"] in self.EVENTOS:
                    self.eventos.append(resp)
            if achada is not None:
                return achada