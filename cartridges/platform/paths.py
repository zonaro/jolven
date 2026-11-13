# paths.py
#
# Copyright 2026 zonaro
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Diretorios de dados, configuracao e cache Linux/XDG.

Esta camada nao importa `gi` e respeita XDG_*_HOME, com os caminhos
padrao Linux quando as variaveis nao estiverem definidas.
"""

from __future__ import annotations

import os
from pathlib import Path

# Pasta do aplicativo dentro do diretorio do usuario.
APP_DIR_NAME = "jolven"

__all__ = [
    "APP_DIR_NAME",
    "base_cache_dir",
    "base_config_dir",
    "base_data_dir",
    "cache_dir",
    "config_dir",
    "data_dir",
    "logs_dir",
]


def _from_env(variable: str) -> Path | None:
    value = os.environ.get(variable)
    return Path(value) if value else None


def base_data_dir() -> Path:
    """Diretorio base de dados (sem o sufixo do aplicativo)."""
    return _from_env("XDG_DATA_HOME") or Path.home() / ".local" / "share"


def base_config_dir() -> Path:
    """Diretorio base de configuracao (sem o sufixo do aplicativo)."""
    return _from_env("XDG_CONFIG_HOME") or Path.home() / ".config"


def base_cache_dir() -> Path:
    """Diretorio base de cache (sem o sufixo do aplicativo)."""
    return _from_env("XDG_CACHE_HOME") or Path.home() / ".cache"


def data_dir() -> Path:
    """Dados persistentes do aplicativo (banco, capas, historico)."""
    return base_data_dir() / APP_DIR_NAME


def config_dir() -> Path:
    """Configuracao do aplicativo."""
    return base_config_dir() / APP_DIR_NAME


def cache_dir() -> Path:
    """Cache descartavel; nunca guarda dados do usuario."""
    return base_cache_dir() / APP_DIR_NAME


def logs_dir() -> Path:
    """Logs do aplicativo."""
    return cache_dir() / "logs"
