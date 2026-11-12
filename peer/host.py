"""Host (árbitro) da partida DualNode. Roteiro: docs/roteiro-host.md"""
import json
import logging
import os
import socket
import time
import math

log = logging.getLogger("host")
from peer.ui import GameView

try:
    from common.game_logic import step
except ImportError:
    _OPOSTO = {"U": "D", "D": "U", "L": "R", "R": "L"}
    _DELTA = {"U": (0, -1), "D": (0, 1), "L": (-1, 0), "R": (1, 0)}

    def step(estado, desejadas, desconectados, n):
        el = []
        for p in sorted(estado["alive"]):
            if estado["alive"][p] and p in desconectados:
                estado["alive"][p] = False
                el.append([p, "DISC"])
        alvos = {}
        for p in sorted(estado["alive"]):
            if not estado["alive"][p]:
                continue
            d = desejadas.get(p)
            if d and d != _OPOSTO[estado["dirs"][p]]:
                estado["dirs"][p] = d
            dx, dy = _DELTA[estado["dirs"][p]]
            x, y = estado["heads"][p]
            alvos[p] = (x + dx, y + dy)
        mv = []
        for p, (x, y) in alvos.items():
            if not (0 <= x < estado["width"] and 0 <= y < estado["height"]):
                estado["alive"][p] = False
                el.append([p, "WALL"])
            else:
                estado["heads"][p] = (x, y)
                estado["cells"][(x, y)] = p
                mv.append([p, x, y])
        vivos = [p for p in sorted(estado["alive"]) if estado["alive"][p]]
        fim = None
        if not vivos:
            fim = {"result": "DRAW"}
        elif len(vivos) == 1:
            fim = {"result": "WIN", "winner": vivos[0]}
        return {"n": n, "mv": mv, "el": sorted(el), "end": fim}


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
TOLERANCIA_ATRASO = 5
JANELA = 8

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
def _proximo_instante(proximo, agora, tick_s):

    proximo += tick_s
    if agora - proximo > TOLERANCIA_ATRASO * tick_s:
        log.warning("atrasado %.0f ms; reajustando o relógio do ciclo",
                    (agora - proximo) * 1000)
        proximo = agora + tick_s
    return proximo


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
        cfg = match_start["config"]
        self.width, self.height, self.tick_ms = cfg["width"], cfg["height"], cfg["tick_ms"]
        t = config.get("timeouts", {})
        self.hello_deadline_s = t.get("hello_deadline_ms", 10000) / 1000
        self.peer_timeout_s = t.get("peer_timeout_ms", 3000) / 1000


        self.jogo = novo_estado(self.width, self.height, sorted(self.nomes))
        self.desconectados_iniciais = set()
        self.historico = []
        self.a_eliminar = set()
        self.resultado = None
        self.motivo_abort = None
        self.dir_host = None
        self.quer_sair = False
        self.view = GameView(self.meu_pid, self.nomes)
        self.view.load_welcome(welcome_state(self.jogo, self.tick_ms))
        log.info("Host criado (partida %s)", match_start.get("match_id"))

    def _enviar_tick_vazio(self, so_presentes=False):
        for pid, j in self.jog.items():
            if j["conectado"] and (j["presente"] or not so_presentes):
                self._enviar(pid, {"v": 1, "t": "TICK", "m": self.match_start["match_id"],
                                   "pid": self.meu_pid, "recs": []})

    def _fase_countdown(self):

        tick_s = self.tick_ms / 1000
        total = math.ceil(COUNTDOWN_MS / self.tick_ms)
        log.info("COUNTDOWN: %d TICKs vazios, um a cada %d ms", total, self.tick_ms)

        proximo = time.monotonic()
        enviados, ultimo, intervalos = 0, None, []
        while enviados < total:

            self._ler_teclado()
            if self.quer_sair:
                return None

            for dados, addr in self._receber_tudo():
                self._tratar_datagrama(dados, addr)

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
        agora = time.monotonic()
        for j in self.jog.values():
            if j["conectado"]:
                j["visto"] = agora
        return proximo

    def _descartar(self, addr, motivo):
        log.debug("descartado de %s: %s", addr, motivo)
        return None

    def _validar(self, dados, addr):

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

    def _enviar(self, pid, msg):
        dados = encode(msg)
        if len(dados) > MAX_DATAGRAMA:
            log.error("mensagem %s para pid %s tem %d bytes (limite %d)",
                      msg.get("t"), pid, len(dados), MAX_DATAGRAMA)
        try:
            self.sock.sendto(dados, self.jog[pid]["addr"])
        except OSError as e:
            log.warning("falha ao enviar %s para pid %s: %s", msg.get("t"), pid, e)

    def _tratar_hello(self, pid, msg, addr):
        j = self.jog[pid]
        if not j["conectado"]:
            log.info("HELLO tardio de pid %s ignorado (já dado como ausente)", pid)
            return
        j["presente"] = True
        j["visto"] = time.monotonic()
        log.info("HELLO de pid %s: respondendo WELCOME", pid)
        self._enviar_welcome(pid)

    def _enviar_welcome(self, pid):
        self._enviar(pid, {
            "v": 1, "t": "WELCOME", "m": self.match_start["match_id"], "pid": self.meu_pid,
            "state": welcome_state(self.jogo, self.tick_ms),
            "countdown_ms": COUNTDOWN_MS,
        })

    def _abortar(self, motivo, tentativas=3, intervalo_s=0.05):

        self.estado = "ABORTED"
        self.motivo_abort = motivo
        log.warning("partida abortada: %s", motivo)
        self._desenhar("Partida encerrada (%s). Pressione qualquer tecla." % motivo)
        for i in range(tentativas):
            for pid, j in self.jog.items():
                if j["conectado"]:
                    self._enviar(pid, {"v": 1, "t": "ABORT", "m": self.match_start["match_id"],
                                       "pid": self.meu_pid, "reason": motivo})
            if i < tentativas - 1:
                time.sleep(intervalo_s)

    def _fase_collecting(self):

        self._desenhar("Aguardando jogadores...")
        tick_s = self.tick_ms / 1000
        proximo_vida = time.monotonic() + tick_s
        limite = time.monotonic() + self.hello_deadline_s
        while time.monotonic() < limite:
            for dados, addr in self._receber_tudo():
                self._tratar_datagrama(dados, addr)
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

        ausentes = [pid for pid, j in self.jog.items() if not j["presente"]]
        for pid in ausentes:
            self.jog[pid]["conectado"] = False
            self.desconectados_iniciais.add(pid)
        if ausentes:
            log.warning("não se apresentaram (serão eliminados com DISC): %s", ausentes)

        if len(ausentes) == len(self.jog):           # só o host sobrou
            self._abortar("jogadores insuficientes")
            return False
        self.estado = "COUNTDOWN"
        return True


    def _tratar_input(self, pid, msg):
        j = self.jog[pid]
        if not j["conectado"]:
            return
        if not j["presente"]:
            log.debug("INPUT de pid %s antes do HELLO", pid)
            return

        iseq, d, ack = msg.get("iseq"), msg.get("dir"), msg.get("ack")
        if any(isinstance(v, bool) or not isinstance(v, int) for v in (iseq, ack)) or ack < 0:
            log.debug("INPUT de pid %s com iseq/ack inválido: %s", pid, msg)
            return
        if d not in ("U", "D", "L", "R"):
            log.debug("INPUT de pid %s com direção inválida: %r", pid, d)
            return
        if iseq <= j["iseq"]:
            log.debug("INPUT de pid %s repetido/atrasado (iseq %s <= %s)", pid, iseq, j["iseq"])
            return

        j["iseq"] = iseq
        j["dir"] = d
        j["visto"] = time.monotonic()
        j["ack"] = max(j["ack"], min(ack, len(self.historico)))

    def _enviar_ticks(self, so_pendentes=False):
        for pid, j in self.jog.items():
            if not j["conectado"]:
                continue
            if so_pendentes and j["ack"] >= len(self.historico):
                    continue
            recs = self.historico[j["ack"]: j["ack"] + JANELA]
            msg = {"v": 1, "t": "TICK", "m": self.match_start["match_id"],
                   "pid": self.meu_pid, "recs": recs}
            while len(recs) > 1 and len(encode(msg)) > MAX_DATAGRAMA:
                recs = recs[:-1]
                msg["recs"] = recs
            self._enviar(pid, msg)

    def _fase_ending(self):

        n_final = len(self.historico)
        tick_s = self.tick_ms / 1000
        inicio = time.monotonic()
        limite = inicio + self.peer_timeout_s
        proximo = inicio + tick_s
        log.info("ENDING: aguardando confirmação do ciclo %d (até %.1f s)", n_final, self.peer_timeout_s)
        while True:
            for dados, addr in self._receber_tudo():
                self._tratar_datagrama(dados, addr)
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

            if agora >= proximo:
                self._enviar_ticks(so_pendentes=True)
                proximo += tick_s
            else:
                time.sleep(min(proximo - agora, 0.005))
        self.estado = "FINISHED"

    def _verificar_timeouts(self, agora=None):

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
        if self.ui is None:
            return
        if status is not None:
            self.view.status = status
        self.ui.draw(self.view)

    def _ler_teclado(self):

        if self.ui is None:
            return
        tecla = self.ui.poll_input()
        if tecla == "QUIT":
            self.quer_sair = True
        elif tecla is not None:
            self.dir_host = tecla

    def _executar_ciclo(self):

        n = len(self.historico) + 1
        self._verificar_timeouts()
        desejadas = {pid: j["dir"] for pid, j in self.jog.items() if j["dir"] is not None}
        if self.dir_host is not None:
            desejadas[self.meu_pid] = self.dir_host
        registro = step(self.jogo, desejadas, self.a_eliminar, n)
        self.a_eliminar = set()
        self.historico.append(registro)
        self._enviar_ticks()
        self.view.apply_record(registro)
        self._desenhar()
        for pid, motivo in registro["el"]:
            log.info("ciclo %d: %s eliminado (%s)", n, self.nomes.get(pid, pid), motivo)
        if registro["end"] is not None:
            self.estado = "ENDING"
            log.info("ciclo %d: FIM %s", n, registro["end"])
        return registro["end"]

    def _fase_rodando(self, proximo):
        tick_s = self.tick_ms / 1000
        while True:
            for dados, addr in self._receber_tudo():
                self._tratar_datagrama(dados, addr)
            self._ler_teclado()
            if self.quer_sair:
                    return None
            agora = time.monotonic()
            if agora < proximo:
                time.sleep(min(proximo - agora, 0.005))
                continue
            fim = self._executar_ciclo()
            if fim is not None:
                return fim
            proximo = _proximo_instante(proximo, agora, tick_s)

    def _montar_jogadores(self):
        self.meu_pid = self.match_start.get("host_slot", 0)
        for p in self.match_start["players"]:
            pid = p["slot"]
            self.nomes[pid] = p["name"]
            if pid == self.meu_pid:
                continue
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

        return self.addr_para_pid.get(addr)

    def _abrir_socket(self):
        eu = next(p for p in self.match_start["players"] if p["slot"] == 0)
        bind_host = self.config.get("peer", {}).get("bind_host", "0.0.0.0")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind((bind_host, eu["port"]))
        except OSError as e:
            log.error("não foi possível abrir %s:%s (%s). Já existe outro host nessa porta?",
                      bind_host, eu["port"], e)
            self.sock.close()
            raise
        self.sock.setblocking(False)
        sim = self.config.get("sim")
        if sim:
            from common.simnet import SimSocket
            self.sock = SimSocket(self.sock, **sim)
            log.warning("REDE SIMULADA ativa: %s", sim)
        log.info("Host escutando em %s:%s", bind_host, eu["port"])

    def _receber_tudo(self):

        recebidos = []
        while True:
            try:
                dados, addr = self.sock.recvfrom(2048)
            except BlockingIOError:
                break                    # acabou o que tinha
            except ConnectionResetError:
                continue
            recebidos.append((dados, addr))
        return recebidos

    def _abortado(self):

        if self.estado != "ABORTED":
            self._abortar("host saiu")
        return {"result": "ABORT", "winner": None}

    def _rodar_partida(self):
        if not self._fase_collecting():
            return self._abortado()
        proximo = self._fase_countdown()
        if proximo is None:
            return self._abortado()
        self.a_eliminar = set(self.desconectados_iniciais)
        fim = self._fase_rodando(proximo)
        if fim is None:
            return self._abortado()
        self.resultado = {"result": fim["result"], "winner": fim.get("winner")}
        self._fase_ending()
        return self.resultado

    def _resumo(self):
        caidos = sorted(pid for pid, j in self.jog.items() if not j["conectado"])
        log.info("Resumo: estado=%s ciclos=%d desconectados=%s resultado=%s motivo_abort=%s",
                 self.estado, len(self.historico), caidos, self.resultado, self.motivo_abort)
        stats = getattr(self.sock, "stats", None)
        if stats:
            log.info("Rede simulada: %s", stats)

    def run(self):
        self._abrir_socket()
        try:
            return self._rodar_partida()
        except KeyboardInterrupt:
            if self.resultado is not None:
                log.warning("host interrompido (Ctrl+C) depois do fim da partida")
                return self.resultado
            if self.estado != "ABORTED":
                self._abortar("host interrompido (Ctrl+C)")
            return {"result": "ABORT", "winner": None}
        finally:
            self._resumo()
            self.sock.close()