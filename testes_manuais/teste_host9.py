# HOST de teste (passo 9) COM A TELA DE VERDADE. Rode num terminal de pelo menos 70x23.
# Controle a moto do host (Alice, pid 0) com W/A/S/D ou setas; Q sai (ABORT).
# uso: python3 -m testes_manuais.teste_host9
# Suba antes os peers em outros terminais:
#   python3 -m testes_manuais.teste_peer8 1 6002
#   python3 -m testes_manuais.teste_peer8 2 6003
from peer.host import Host, configurar_log
from peer.ui import TerminalUI

configurar_log()
MS = {"match_id": "m1", "host_slot": 0,
      "config": {"width": 40, "height": 20, "tick_ms": 200},        # 200 ms: dá para ver
      "players": [{"slot": 0, "name": "Alice", "host": "127.0.0.1", "port": 6001},
                  {"slot": 1, "name": "Bob",   "host": "127.0.0.1", "port": 6002},
                  {"slot": 2, "name": "Carol", "host": "127.0.0.1", "port": 6003}]}
CONFIG = {"timeouts": {"hello_deadline_ms": 15000, "peer_timeout_ms": 1500}}

with TerminalUI() as ui:
    resultado = Host(CONFIG, MS, ui=ui).run()
    ui.wait_key()
print("resultado:", resultado)