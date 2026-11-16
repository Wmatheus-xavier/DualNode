# common/config.py
import argparse
import copy
import json
import os
import re

DEFAULT_PATH = "config.json"

DEFAULTS = {
    "lobby": {
        "host": "127.0.0.1",
        "port": 5000,
        "game": {"width": 40, "height": 20, "tick_ms": 100},
    },
    "peer": {
        "name": None,
        "bind_host": "0.0.0.0",
        "advertise_host": None,
        "udp_port": 6001,
    },
    "timeouts": {
        "peer_timeout_ms": 3000,
        "host_timeout_ms": 3000,
        "hello_retry_ms": 500,
        "hello_deadline_ms": 10000,
        "lobby_ping_ms": 5000,
        "lobby_dead_ms": 15000,
    },
    "debug": {"sim_loss": 0.0, "sim_delay_ms": 0, "log_level": "INFO"},
}

# argumento da linha de comando -> caminho no dicionário
OVERRIDES = {
    "lobby_host": "lobby.host",
    "lobby_port": "lobby.port",
    "name": "peer.name",
    "bind_host": "peer.bind_host",
    "advertise_host": "peer.advertise_host",
    "udp_port": "peer.udp_port",
    "sim_loss": "debug.sim_loss",
    "sim_delay_ms": "debug.sim_delay_ms",
    "log_level": "debug.log_level",
}


class ConfigError(Exception):
    """Configuração inválida (mensagem pronta para mostrar ao usuário)."""


def build_parser():
    """Parser com as opções comuns. O main.py pode reaproveitar e acrescentar as suas."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None, help="caminho do config.json")
    ap.add_argument("--lobby-host", "--host", dest="lobby_host")
    ap.add_argument("--lobby-port", "--port", dest="lobby_port", type=int)
    ap.add_argument("--name")
    ap.add_argument("--bind-host", dest="bind_host")
    ap.add_argument("--advertise-host", dest="advertise_host")
    ap.add_argument("--udp-port", dest="udp_port", type=int)
    ap.add_argument("--sim-loss", dest="sim_loss", type=float)
    ap.add_argument("--sim-delay-ms", dest="sim_delay_ms", type=int)
    ap.add_argument("--log-level", dest="log_level")
    return ap


def _mesclar(base, extra, caminho=""):
    """Copia 'extra' por cima de 'base' (recursivo). Chave desconhecida é erro (pega typo)."""
    for chave, valor in extra.items():
        local = caminho + chave
        if chave not in base:
            raise ConfigError(f"chave desconhecida no config: '{local}'")
        if isinstance(base[chave], dict):
            if not isinstance(valor, dict):
                raise ConfigError(f"'{local}' deveria ser um objeto {{...}}")
            _mesclar(base[chave], valor, local + ".")
        else:
            base[chave] = valor


def _obter(cfg, caminho):
    atual = cfg
    for parte in caminho.split("."):
        atual = atual[parte]
    return atual


def _definir(cfg, caminho, valor):
    *pais, ultimo = caminho.split(".")
    atual = cfg
    for parte in pais:
        atual = atual[parte]
    atual[ultimo] = valor


def _inteiro(cfg, caminho, minimo, maximo=None):
    valor = _obter(cfg, caminho)
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ConfigError(f"'{caminho}' deve ser um número inteiro (veio {valor!r})")
    if valor < minimo or (maximo is not None and valor > maximo):
        faixa = f"entre {minimo} e {maximo}" if maximo is not None else f"maior ou igual a {minimo}"
        raise ConfigError(f"'{caminho}' deve ser {faixa} (veio {valor})")


def _texto(cfg, caminho, pode_nulo=False):
    valor = _obter(cfg, caminho)
    if valor is None and pode_nulo:
        return
    if not isinstance(valor, str) or not valor:
        raise ConfigError(f"'{caminho}' deve ser um texto não vazio (veio {valor!r})")


def validar(cfg):
    _texto(cfg, "lobby.host")
    _inteiro(cfg, "lobby.port", 1, 65535)
    _inteiro(cfg, "lobby.game.width", 5)
    _inteiro(cfg, "lobby.game.height", 5)
    _inteiro(cfg, "lobby.game.tick_ms", 10)

    _texto(cfg, "peer.bind_host")
    _texto(cfg, "peer.advertise_host", pode_nulo=True)
    _inteiro(cfg, "peer.udp_port", 1024, 65535)
    nome = cfg["peer"]["name"]
    if nome is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,16}", str(nome)):
        raise ConfigError("'peer.name' deve ter 1 a 16 caracteres [A-Za-z0-9_-]")

    for chave in cfg["timeouts"]:
        _inteiro(cfg, "timeouts." + chave, 1)
    if cfg["timeouts"]["lobby_dead_ms"] <= cfg["timeouts"]["lobby_ping_ms"]:
        raise ConfigError("'timeouts.lobby_dead_ms' deve ser maior que 'timeouts.lobby_ping_ms'")

    perda = cfg["debug"]["sim_loss"]
    if isinstance(perda, bool) or not isinstance(perda, (int, float)) or not 0 <= perda <= 1:
        raise ConfigError("'debug.sim_loss' deve estar entre 0 e 1")
    _inteiro(cfg, "debug.sim_delay_ms", 0)
    _texto(cfg, "debug.log_level")


def load_config(argv=None, parser=None):
    """Devolve (cfg, args). cfg é um dicionário aninhado, já validado.

    Ordem de prioridade: linha de comando > config.json > valores padrão.
    """
    args = (parser or build_parser()).parse_args(argv)
    cfg = copy.deepcopy(DEFAULTS)

    caminho = args.config or DEFAULT_PATH
    if os.path.exists(caminho):
        try:
            with open(caminho, encoding="utf-8") as f:
                dados = json.load(f)
        except (OSError, ValueError) as e:
            raise ConfigError(f"não foi possível ler '{caminho}': {e}")
        if not isinstance(dados, dict):
            raise ConfigError(f"'{caminho}' deve conter um objeto JSON")
        _mesclar(cfg, dados)
    elif args.config:
        raise ConfigError(f"arquivo de configuração não encontrado: '{caminho}'")

    for arg, destino in OVERRIDES.items():
        valor = getattr(args, arg, None)
        if valor is not None:
            _definir(cfg, destino, valor)

    validar(cfg)
    return cfg, args