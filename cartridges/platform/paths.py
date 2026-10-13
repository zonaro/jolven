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

"""Diretorios de dados, configuracao e cache por plataforma.

Esta camada e de baixo nivel e **nao importa `gi`**. Os caminhos sao resolvidos
aqui, e nao por `GLib.get_user_*_dir()`, porque no Windows
`GLib.get_user_cache_dir()` aponta para `INetCache`, que a Limpeza de Disco
esvazia por padrao. No Windows, `%APPDATA%` (Roaming) guarda dados e
configuracao, e `%LOCALAPPDATA%` guarda o cache.
"""

from __future__ import annotations

import os
from pathlib import Path

# Pasta do aplicativo dentro do diretorio do usuario.
APP_DIR_NAME = "jolven"

# Resolvido em tempo de import; os testes trocam este atributo para exercitar o
# caminho do Windows sem depender da plataforma real.
_IS_WINDOWS = os.name == "nt"

__all__ = [
    "APP_DIR_NAME",
    "base_cache_dir",
    "base_config_dir",
    "base_data_dir",
    "cache_dir",
    "config_dir",
    "data_dir",
    "logs_dir",
    "appdata_dir",
    "local_appdata_dir",
    "program_files_dir",
]


def _from_env(variable: str) -> Path | None:
    value = os.environ.get(variable)
    return Path(value) if value else None


def _windows_dir(variable: str, fallback: str) -> Path:
    """`%VARIABLE%`, ou o caminho padrao derivado do perfil do usuario."""
    return _from_env(variable) or Path.home() / fallback


def base_data_dir() -> Path:
    """Diretorio base de dados (sem o sufixo do aplicativo)."""
    if _IS_WINDOWS:
        return _windows_dir("APPDATA", "AppData/Roaming")
    return _from_env("XDG_DATA_HOME") or Path.home() / ".local" / "share"


def base_config_dir() -> Path:
    """Diretorio base de configuracao (sem o sufixo do aplicativo)."""
    if _IS_WINDOWS:
        return _windows_dir("APPDATA", "AppData/Roaming")
    return _from_env("XDG_CONFIG_HOME") or Path.home() / ".config"


def base_cache_dir() -> Path:
    """Diretorio base de cache (sem o sufixo do aplicativo)."""
    if _IS_WINDOWS:
        return _windows_dir("LOCALAPPDATA", "AppData/Local")
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


def appdata_dir() -> Path | None:
    """`%APPDATA%` (Roaming); `None` fora do Windows."""
    if not _IS_WINDOWS:
        return None
    return _windows_dir("APPDATA", "AppData/Roaming")


def local_appdata_dir() -> Path | None:
    """`%LOCALAPPDATA%`; `None` fora do Windows."""
    if not _IS_WINDOWS:
        return None
    return _windows_dir("LOCALAPPDATA", "AppData/Local")


def program_files_dir() -> Path | None:
    """`%ProgramFiles%`, para achar programas de terceiros; `None` fora do Windows."""
    if not _IS_WINDOWS:
        return None
    return _from_env("ProgramFiles") or Path("C:/Program Files")
