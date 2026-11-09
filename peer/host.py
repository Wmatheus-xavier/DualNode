"""Host (árbitro) da partida DualNode. Roteiro: docs/roteiro-host.md"""
import logging
import os

log = logging.getLogger("host")

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