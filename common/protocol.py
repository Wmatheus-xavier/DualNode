import json


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
# common/protocol.py


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