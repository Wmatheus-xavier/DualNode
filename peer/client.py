"""peer/client.py - jogador comum (peer != host).

PARTE 1: preparacao (ler o MATCH_START) e socket UDP unico.
As proximas partes (handshake, INPUT, TICK, falhas) serao adicionadas aqui.
"""

import ipaddress
import socket


class ErroPreparacao(Exception):
    """MATCH_START invalido ou impossivel de usar neste peer."""


def _ip_numerico(valor):
    """True se for um IPv4 numerico utilizavel (nao 'localhost', nem 0.0.0.0)."""
    try:
        ip = ipaddress.IPv4Address(valor)
    except (ipaddress.AddressValueError, ValueError):
        return False
    return not ip.is_unspecified


def ler_match_start(match_start, meu_slot):
    """Extrai do MATCH_START o que o cliente precisa.

    match_start: dict da mensagem MATCH_START (README, secao 9).
    meu_slot: slot (pid) deste jogador, atribuido pelo lobby.

    Devolve um dict com: match_id, meu_pid, host_pid, host_addr (ip, porta),
    meu_addr (ip, porta), players (slot -> {name, addr}) e config
    ({width, height, tick_ms}). Levanta ErroPreparacao se algo estiver errado.
    """
    try:
        match_id = match_start["match_id"]
        host_pid = match_start["host_slot"]
        config = match_start["config"]
        lista = match_start["players"]
    except (KeyError, TypeError):
        raise ErroPreparacao("MATCH_START sem campos obrigatorios")

    if not isinstance(lista, list) or not lista:
        raise ErroPreparacao("MATCH_START sem lista de jogadores")

    players = {}
    for p in lista:
        try:
            slot, nome, ip, porta = p["slot"], p["name"], p["host"], p["port"]
        except (KeyError, TypeError):
            raise ErroPreparacao("jogador mal formado no MATCH_START")
        if not isinstance(slot, int) or isinstance(slot, bool):
            raise ErroPreparacao("slot invalido: %r" % (slot,))
        if not _ip_numerico(ip):
            raise ErroPreparacao(
                "IP nao numerico para o slot %s: %r (o lobby deve enviar IPs numericos)"
                % (slot, ip)
            )
        if not isinstance(porta, int) or isinstance(porta, bool) or not 1024 <= porta <= 65535:
            raise ErroPreparacao("porta invalida para o slot %s: %r" % (slot, porta))
        if slot in players:
            raise ErroPreparacao("slot repetido: %s" % slot)
        players[slot] = {"name": nome, "addr": (ip, porta)}

    if host_pid not in players:
        raise ErroPreparacao("host_slot %r nao esta na lista de jogadores" % (host_pid,))
    if meu_slot not in players:
        raise ErroPreparacao("meu slot %r nao esta no MATCH_START" % (meu_slot,))
    if meu_slot == host_pid:
        raise ErroPreparacao("este processo e o host; deveria usar peer/host.py")

    return {
        "match_id": match_id,
        "meu_pid": meu_slot,
        "host_pid": host_pid,
        "host_addr": players[host_pid]["addr"],
        "meu_addr": players[meu_slot]["addr"],
        "players": players,
        "config": config,
    }


def abrir_socket(bind_host, porta):
    """Cria o UNICO socket UDP do peer, com bind na porta registrada no lobby.

    Todo envio (HELLO, INPUT) deve sair deste mesmo socket: o host valida a
    origem pelo endereco (IP e porta) informado no MATCH_START.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((bind_host, porta))
    except OSError as e:
        sock.close()
        raise ErroPreparacao("nao foi possivel abrir a porta UDP %s: %s" % (porta, e))
    return sock
