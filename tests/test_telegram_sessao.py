# test_telegram_sessao.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Diretório local da sessão TDLib, sem Secret Service e sem rede."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cartridges.integrations.telegram.sessao import diretorio_sessao


class TestDiretorioSessao(unittest.TestCase):
    """A sessão fica sob XDG_DATA_HOME, nunca no repositório."""

    def test_usa_xdg_data_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"XDG_DATA_HOME": tmp}):
                caminho = diretorio_sessao()
                self.assertEqual(caminho, Path(tmp) / "jolven" / "telegram")
                self.assertTrue(caminho.is_dir())

    def test_cria_diretorio_com_modo_restrito(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"XDG_DATA_HOME": tmp}):
                caminho = diretorio_sessao()
                modo = caminho.stat().st_mode & 0o777
                self.assertEqual(modo, 0o700)

    def test_sem_xdg_usa_home_do_usuario(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("XDG_DATA_HOME", None)
                with patch("pathlib.Path.home", return_value=Path(tmp)):
                    caminho = diretorio_sessao()
        self.assertEqual(caminho, Path(tmp) / ".local" / "share" / "jolven" / "telegram")


if __name__ == "__main__":
    unittest.main()
