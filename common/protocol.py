# common/protocol.py
import json

PROTOCOL_VERSION = 1
MAX_UDP_SIZE = 1200
MAX_LINE_SIZE = 4096
VALID_DIRS = ("U", "D", "L", "R")


REQUIRED_UDP = {
    # peer -> host
    "HELLO": {"m": str, "pid": int},
    "INPUT": {"m": str, "pid": int, "iseq": int, "dir": str, "ack": int},

    # host -> peer
    "WELCOME": {"m": str, "state": dict, "countdown_ms": int},
    "TICK": {"m": str, "recs": list},
    "ABORT": {"m": str, "reason": str},
}

REQUIRED_TCP = {
    # jogador -> lobby
    "REGISTER": {"name": str, "udp_port": int},        # udp_host é opcional
    "CREATE_MATCH": {"name": str, "max_players": int},
    "LIST_MATCHES": {},
    "JOIN_MATCH": {"match_id": str},
    "LEAVE_MATCH": {},
    "START_MATCH": {},
    "MATCH_END": {"winner": (int, type(None))},        # pid ou None (empate)
    "PING": {},
    "PONG": {},

    # lobby -> jogador
    "REGISTER_OK": {"player_id": (int, str)},          # README não fixa o tipo
    "MATCH_CREATED": {"match_id": str, "slot": int},
    "MATCH_LIST": {"matches": list},
    "JOIN_OK": {"match_id": str, "slot": int, "players": list},
    "PLAYER_JOINED": {"slot": int, "name": str},
    "PLAYER_LEFT": {"slot": int, "name": str},
    "MATCH_CANCELLED": {"reason": str},
    "MATCH_START": {"match_id": str, "host_slot": int,
                    "config": dict, "players": list},
    "ERROR": {"code": str, "msg": str},
}


def _tipo_ok(valor, esperado):
    """Confere o tipo de um campo. Aceita tupla de tipos e rejeita bool onde se espera int."""
    tipos = esperado if isinstance(esperado, tuple) else (esperado,)
    if isinstance(valor, bool) and bool not in tipos:
        return False
    return isinstance(valor, tipos)


def _validar(msg, tabela):
    """Devolve msg se for válida para a tabela dada, senão None. Nunca lança exceção."""
    if not isinstance(msg, dict):
        return None
    if msg.get("v") != PROTOCOL_VERSION:
        return None
    tipo = msg.get("t")
    if not isinstance(tipo, str) or tipo not in tabela:
        return None
    for campo, esperado in tabela[tipo].items():
        if campo not in msg or not _tipo_ok(msg[campo], esperado):
            return None
    if "dir" in msg and msg["dir"] not in VALID_DIRS:
        return None
    return msg


# ---------- UDP: um objeto JSON por datagrama ----------

def encode(msg):
    """dict -> bytes (um datagrama UDP)."""
    return json.dumps(msg, separators=(",", ":")).encode("utf-8")


def decode(data):
    """bytes -> dict válido, ou None para qualquer lixo. Nunca lança exceção."""
    if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_UDP_SIZE:
        return None
    try:
        msg = json.loads(bytes(data).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return _validar(msg, REQUIRED_UDP)


# ---------- TCP: um objeto JSON por linha ----------

class LineTooLong(Exception):
    """Linha acumulada passou de MAX_LINE_SIZE sem '\\n'."""


def encode_line(msg):
    """dict -> bytes (JSON + '\\n') para enviar pelo TCP."""
    return json.dumps(msg, separators=(",", ":")).encode("utf-8") + b"\n"


def decode_line(linha):
    """Uma linha (bytes, sem '\\n') -> dict válido do lobby, ou None."""
    try:
        msg = json.loads(linha.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return _validar(msg, REQUIRED_TCP)


class LineBuffer:
    """Acumula bytes do TCP e devolve as linhas completas."""

    def __init__(self):
        self._buf = b""

    def feed(self, data):
        """Recebe bytes; devolve lista de dicts (ou None para linha inválida)."""
        self._buf += data
        resultado = []
        while b"\n" in self._buf:
            linha, self._buf = self._buf.split(b"\n", 1)
            if len(linha) > MAX_LINE_SIZE:
                raise LineTooLong()
            if linha.strip():
                resultado.append(decode_line(linha))
        if len(self._buf) > MAX_LINE_SIZE:
            raise LineTooLong()
        return resultado 
    # ---------- Construtoras UDP (peer <-> host) ----------

def _base(tipo, **campos):
    msg = {"v": PROTOCOL_VERSION, "t": tipo}
    msg.update(campos)
    return msg


def hello(match_id, pid):
    return _base("HELLO", m=match_id, pid=pid)


def welcome(match_id, state, countdown_ms):
    return _base("WELCOME", m=match_id, state=state, countdown_ms=countdown_ms)


def input_msg(match_id, pid, iseq, direcao, ack):
    return _base("INPUT", m=match_id, pid=pid, iseq=iseq, dir=direcao, ack=ack)


def tick(match_id, recs):
    return _base("TICK", m=match_id, recs=recs)


def abort(match_id, reason):
    return _base("ABORT", m=match_id, reason=reason)


# ---------- Construtoras TCP: jogador -> lobby ----------

def register(name, udp_port, udp_host=None):
    msg = _base("REGISTER", name=name, udp_port=udp_port)
    if udp_host is not None:
        msg["udp_host"] = udp_host
    return msg


def create_match(name, max_players):
    return _base("CREATE_MATCH", name=name, max_players=max_players)


def list_matches():
    return _base("LIST_MATCHES")


def join_match(match_id):
    return _base("JOIN_MATCH", match_id=match_id)


def leave_match():
    return _base("LEAVE_MATCH")


def start_match():
    return _base("START_MATCH")


def match_end(winner):
    return _base("MATCH_END", winner=winner)


def ping():
    return _base("PING")


def pong():
    return _base("PONG")


# ---------- Construtoras TCP: lobby -> jogador ----------

def register_ok(player_id):
    return _base("REGISTER_OK", player_id=player_id)


def match_created(match_id, slot):
    return _base("MATCH_CREATED", match_id=match_id, slot=slot)


def match_list(matches):
    return _base("MATCH_LIST", matches=matches)


def join_ok(match_id, slot, players):
    return _base("JOIN_OK", match_id=match_id, slot=slot, players=players)


def player_joined(slot, name):
    return _base("PLAYER_JOINED", slot=slot, name=name)


def player_left(slot, name):
    return _base("PLAYER_LEFT", slot=slot, name=name)


def match_cancelled(reason):
    return _base("MATCH_CANCELLED", reason=reason)


def match_start(match_id, host_slot, config, players):
    return _base("MATCH_START", match_id=match_id, host_slot=host_slot,
                 config=config, players=players)


def error(code, msg):
    return _base("ERROR", code=code, msg=msg)