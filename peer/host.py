"""Host (árbitro) da partida DualNode. Roteiro: docs/roteiro-host.md"""
import json
import logging
import os
import socket
import time
log = logging.getLogger("host")

try:
    from common.protocol import decode, encode            # pessoa E
except ImportError:

    def decode(data):
        try:
            msg = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(msg, dict) or msg.get("v") != 1 or "t" not in msg:
            return None
        return msg


    def encode(msg):
        return json.dumps(msg, separators=(",", ":")).encode("utf-8")


try:
    from common.game_logic import novo_estado, welcome_state   # pessoa C
except ImportError:
    _START = {0: (5, 5, "R"), 1: (34, 14, "L"), 2: (20, 1, "D"), 3: (20, 18, "U")}


    def novo_estado(width, height, pids):
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

MAX_DATAGRAMA = 1200
COUNTDOWN_MS = 3000

# Tipos que um PEER pode mandar ao host, por estado do host
ACEITOS = {
    "COLLECTING": {"HELLO", "INPUT"},
    "COUNTDOWN": {"HELLO", "INPUT"},
    "RUNNING": {"INPUT"},
    "ENDING": {"INPUT"},
}

def configurar_log(caminho="logs/host.log"):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    logging.basicConfig(
        filename=caminho,
        filemode="w",
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(message)s",
    )


class Host:
    def __init__(self, config, match_start, ui=None):
        self.config = config
        self.match_start = match_start
        self.ui = ui
        self.sock = None
        self.meu_pid = None
        self.nomes = {}
        self.jog = {}
        self.addr_para_pid = {}
        self._montar_jogadores()
        self.estado = "COLLECTING"
        log.info("Host criado (partida %s)", match_start.get("match_id"))

    def _descartar(self, addr, motivo):
        log.debug("descartado de %s: %s", addr, motivo)
        return None

    def _validar(self, dados, addr):
        """Devolve (pid, msg) se o datagrama for aceito; senão None."""
        if len(dados) > MAX_DATAGRAMA:
            return self._descartar(addr, "grande demais (%d bytes)" % len(dados))

        msg = decode(dados)
        if msg is None:
            return self._descartar(addr, "mensagem inválida")

        if msg.get("m") != self.match_start.get("match_id"):
            return self._descartar(addr, "partida diferente")

        pid = msg.get("pid")
        if not isinstance(pid, int):
            return self._descartar(addr, "pid ausente ou inválido")

        dono = self._pid_da_origem(addr)
        if dono is None:
            return self._descartar(addr, "origem desconhecida")
        if dono != pid:
            return self._descartar(addr, "pid %s veio do endereço do pid %s" % (pid, dono))

        if msg["t"] not in ACEITOS.get(self.estado, set()):
            return self._descartar(addr, "tipo %s fora de estado (%s)" % (msg["t"], self.estado))

        return pid, msg

    def _tratar_datagrama(self, dados, addr):
        r = self._validar(dados, addr)
        if r is None:
            return
        pid, msg = r
        if msg["t"] == "HELLO":
            self._tratar_hello(pid, msg, addr)
        elif msg["t"] == "INPUT":
            self._tratar_input(pid, msg)

    def _tratar_hello(self, pid, msg, addr):
        log.info("HELLO aceito de pid %s (%s)", pid, addr)  # passo 4

    def _tratar_input(self, pid, msg):
        log.debug("INPUT aceito de pid %s: %s", pid, msg)  # passo 7

    def _montar_jogadores(self):
        self.meu_pid = self.match_start.get("host_slot", 0)
        for p in self.match_start["players"]:
            pid = p["slot"]
            self.nomes[pid] = p["name"]
            if pid == self.meu_pid:
                continue  # o host não é "peer" de si mesmo
            addr = (p["host"], int(p["port"]))
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
        """Devolve o pid dono desse endereço, ou None se for desconhecido."""
        return self.addr_para_pid.get(addr)

    def _abrir_socket(self):
        eu = next(p for p in self.match_start["players"] if p["slot"] == 0)
        bind_host = self.config.get("peer", {}).get("bind_host", "0.0.0.0")

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((bind_host, eu["port"]))
        self.sock.setblocking(False)
        log.info("Host escutando em %s:%s", bind_host, eu["port"])

    def _receber_tudo(self):
        """Lê todos os datagramas pendentes. Devolve [(dados, addr), ...]."""
        recebidos = []
        while True:
            try:
                dados, addr = self.sock.recvfrom(2048)
            except BlockingIOError:
                break                    # acabou o que tinha
            except ConnectionResetError:
                continue                 # Windows avisa quando um peer fecha
            recebidos.append((dados, addr))
        return recebidos

    def run(self):
        raise NotImplementedError