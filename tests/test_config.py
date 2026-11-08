import json
import os
import tempfile
import unittest

from common.config import ConfigError, load_config


def _arquivo(dados):
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(dados, f)
    f.close()
    return f.name


class TestConfig(unittest.TestCase):
    def test_padroes_sem_arquivo(self):
        cfg, _ = load_config([])
        self.assertEqual(cfg["lobby"]["port"], 5000)
        self.assertEqual(cfg["timeouts"]["peer_timeout_ms"], 3000)

    def test_arquivo_sobrescreve_padrao(self):
        caminho = _arquivo({"lobby": {"port": 7000}})
        self.addCleanup(os.remove, caminho)
        cfg, _ = load_config(["--config", caminho])
        self.assertEqual(cfg["lobby"]["port"], 7000)
        self.assertEqual(cfg["lobby"]["game"]["width"], 40)  # mantém o padrão

    def test_linha_de_comando_vence_arquivo(self):
        caminho = _arquivo({"peer": {"udp_port": 6001}})
        self.addCleanup(os.remove, caminho)
        cfg, _ = load_config(["--config", caminho, "--udp-port", "6005"])
        self.assertEqual(cfg["peer"]["udp_port"], 6005)

    def test_arquivo_inexistente(self):
        with self.assertRaises(ConfigError):
            load_config(["--config", "nao_existe.json"])

    def test_chave_desconhecida(self):
        caminho = _arquivo({"timeouts": {"peer_timeuot_ms": 1}})
        self.addCleanup(os.remove, caminho)
        with self.assertRaises(ConfigError):
            load_config(["--config", caminho])

    def test_porta_invalida(self):
        with self.assertRaises(ConfigError):
            load_config(["--udp-port", "80"])

    def test_sim_loss_fora_da_faixa(self):
        with self.assertRaises(ConfigError):
            load_config(["--sim-loss", "1.5"])


if __name__ == "__main__":
    unittest.main()