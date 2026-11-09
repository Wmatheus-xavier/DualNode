"""Host (árbitro) da partida DualNode. Roteiro: docs/roteiro-host.md"""
import logging
import os
import socket

log = logging.getLogger("host")


def _abrir_socket(self):
    eu = next(p for p in self.match_start["players"] if p["slot"] == 0)
    bind_host = self.config.get("peer", {}).get("bind_host", "0.0.0.0")

    self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    self.sock.bind((bind_host, eu["port"]))
    self.sock.setblocking(False)
    log.info("Host escutando em %s:%s", bind_host, eu["port"])


def configurar_log(caminho="logs/host.log"):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    logging.basicConfig(
        filename=caminho,
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(message)s",
    )

class Host:
    def __init__(self, config, match_start, ui=None):
        self.config = config
        self.match_start = match_start
        self.ui = ui
        log.info("Host criado (partida %s)", match_start.get("match_id"))

    def run(self):
        raise NotImplementedError