"""Host (árbitro) da partida DualNode. Roteiro: docs/roteiro-host.md"""
import logging
import os
import socket

log = logging.getLogger("host")

try:
    from common.protocol import decode
except ImportError:          # provisório, até a pessoa E entregar o protocol.py
    import json

    def decode(data):
        try:
            msg = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(msg, dict) or msg.get("v") != 1 or "t" not in msg:
            return None
        return msg

MAX_DATAGRAMA = 1200

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