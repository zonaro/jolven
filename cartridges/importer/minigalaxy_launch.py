# minigalaxy_launch.py
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

"""Montagem do comando de lançamento dos jogos importados do Minigalaxy.

Módulo puro (sem ``gi``, sem GTK e sem ``subprocess``): decide apenas, com base
nos arquivos já lidos por ``cartridges.importer.minigalaxy`` e no launcher
detectado, qual comando o Jogo executaria. A execução fica a cargo de
``game_launch.build_game_command``/``utils.run_executable``.

Ordem e comportamento reproduzidos do upstream ``sharkwouter/minigalaxy``
(master, commit ``f23e237``):

* ``start.sh`` — executa ``<instalação>/start.sh``;
* DOSBox — ``dosbox -conf <conf> [-conf <conf>_single] -no-console -c exit``;
* ScummVM — ``scummvm -c <ini>`` (o primeiro ``.ini`` do diretório);
* Wine (prefix) — ``<wine> start /b /wait /d c:\\game\\<workingDir>`` com
  ``WINEPREFIX=<instalação>/prefix`` no ambiente, a partir do ``playTask``
  primário do ``goggame``; sem ele, cai para ``Launch *.lnk`` e depois para o
  primeiro ``.exe``/``.lnk`` que não for desinstalador;
* ``final_resort`` — ``./<path>`` da primeira entrada de ``playTasks``, com
  ``cwd`` em ``<instalação>/game``;
* ``unavailable`` — sem comando: o jogo é importado mas não pode ser lançado.

As preferências do Minigalaxy por jogo (``use_gamemode``, ``use_mangohud``,
``show_fps``, ``custom_wine``) seguem o upstream. ``command`` e ``variable``
continuam fora do escopo: execução arbitrária exige decisão explícita do
usuário.
"""

from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Optional

from cartridges.importer.minigalaxy import (
    DOSBOX_CONFIG_PATTERN,
    GOGGAME_INFO_PATTERN,
    SCUMMVM_CONFIG_PATTERN,
    MAX_METADATA_BYTES,
    InvalidGameMetadata,
    MinigalaxyGame,
    MinigalaxyPreferences,
    parse_goggame_info,
)

#: Executáveis de apoio que o upstream ignora ao escolher um ``.exe``/``.lnk``.
_BINARIES_TO_IGNORE = frozenset(
    {"unins000.exe", "UnityCrashHandler64.exe"}
)

#: Arquivos ``Launch Game.lnk`` têm prioridade sobre qualquer ``.exe``.
_LAUNCH_LNK_PATTERN = re.compile(r"^Launch .*\.lnk$")

#: Variáveis de ambiente do contador de FPS do Minigalaxy (show_fps).
_FPS_ENVIRONMENT = {
    "__GL_SHOW_GRAPHICS_OSD": "1",  # Nvidia + OpenGL/Vulkan
    "GALLIUM_HUD": "simple,fps",  # AMDGPU + OpenGL
    "VK_INSTANCE_LAYERS": "VK_LAYER_MESA_overlay",  # AMDGPU + Vulkan
}


def wine_path(preferences: MinigalaxyPreferences) -> str:
    """``wine`` customizado quando o Minigalaxy o guarda nas preferências."""

    custom = preferences.custom_wine
    if custom and custom.strip():
        return custom.strip()
    return "wine"


def fps_environment(preferences: MinigalaxyPreferences) -> dict[str, str]:
    """Ambiente do contador de FPS, só quando o Minigalaxy o pede.

    Devolver vazio mantém o ambiente global intacto: a chave não vaza para
    jogos que não pediram o contador.
    """

    return dict(_FPS_ENVIRONMENT) if preferences.show_fps else {}


def select_dosbox_configs(entries) -> tuple[Optional[str], Optional[str]]:
    """Escolhe os ``conf`` do DOSBox, preferindo o do jogo ao ``_single``."""

    regular = None
    single = None
    for name in entries:
        if not DOSBOX_CONFIG_PATTERN.match(name):
            continue
        if name.endswith("_single.conf"):
            single = single or name
        else:
            regular = regular or name
    return regular, single


def select_scummvm_config(entries) -> Optional[str]:
    """O primeiro ``.ini`` do diretório, como o upstream."""

    for name in entries:
        if SCUMMVM_CONFIG_PATTERN.match(name):
            return name
    return None


def _primary_task(directory: Path, goggame_names: list[str]):
    """Tarefa primária do ``goggame`` legível mais bem ordenado."""

    for filename in sorted(goggame_names):
        try:
            _name, _gog_id, task = parse_goggame_info(directory / filename)
        except InvalidGameMetadata:
            continue
        if isinstance(task, dict) and isinstance(task.get("path"), str) and task["path"]:
            return task
    return None


def _first_task(directory: Path, goggame_names: list[str]):
    """Primeira ``playTask`` (não primária) — o ``final_resort`` do upstream."""

    for filename in sorted(goggame_names):
        info_path = directory / filename
        try:
            stat = info_path.stat()
        except OSError:
            continue
        if stat.st_size > MAX_METADATA_BYTES:
            continue
        try:
            data = json.loads(info_path.read_bytes().decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        tasks = data.get("playTasks")
        if not isinstance(tasks, list) or not tasks:
            continue
        first = tasks[0]
        if isinstance(first, dict) and isinstance(first.get("path"), str):
            return first
    return None


def windows_command(directory: Path, game: MinigalaxyGame) -> list[str]:
    """Comando ``wine`` do jogo Windows sob Wine.

    Ordem do upstream: ``goggame`` primário, depois ``Launch *.lnk``, depois o
    primeiro ``.exe``/``.lnk`` que não for desinstalador.
    """

    prefix = directory / "prefix"
    wine = wine_path(game.preferences)
    prefix_env = f"WINEPREFIX={prefix}"
    entries = os.listdir(directory)
    goggame_names = sorted(
        name for name in entries if GOGGAME_INFO_PATTERN.match(name)
    )

    task = _primary_task(directory, goggame_names)
    if task is not None:
        working_dir = task.get("workingDir")
        working_dir = working_dir if isinstance(working_dir, str) and working_dir else "."
        command = [
            "env",
            prefix_env,
            wine,
            "start",
            "/b",
            "/wait",
            "/d",
            rf"c:\game\{working_dir}",
            rf"c:\game\{task['path']}",
        ]
        arguments = task.get("arguments")
        if isinstance(arguments, str) and arguments.strip():
            command += _split_arguments(arguments)
        return command

    launch_links = sorted(name for name in entries if _LAUNCH_LNK_PATTERN.match(name))
    if launch_links:
        return ["env", prefix_env, wine, str(directory / launch_links[0])]

    executables = sorted(
        name
        for name in entries
        if os.path.splitext(name.upper())[-1] in {".EXE", ".LNK"}
        and name.lower() not in _BINARIES_TO_IGNORE
    )
    if executables:
        return ["env", prefix_env, wine, str(directory / executables[0])]
    return []


def final_resort_command(game: MinigalaxyGame) -> list[str]:
    """``./<path>`` da primeira ``playTask`` — o fallback "FTL" do upstream."""

    final_resort_dir = game.directory / "game"
    if not final_resort_dir.is_dir():
        return []
    entries = os.listdir(final_resort_dir)
    goggame_names = sorted(
        name for name in entries if GOGGAME_INFO_PATTERN.match(name)
    )
    task = _first_task(final_resort_dir, goggame_names)
    if task is None:
        return []
    return ["./" + task["path"]]


def dosbox_command(directory: Path, entries) -> list[str]:
    """Comando DOSBox, vazio quando não há configuração utilizável."""

    regular, single = select_dosbox_configs(entries)
    if regular is None and single is None:
        return []
    command = ["dosbox"]
    if regular is not None:
        command += ["-conf", str(directory / regular)]
    if single is not None:
        command += ["-conf", str(directory / single)]
    command += ["-no-console", "-c", "exit"]
    return command


def scummvm_command(directory: Path, entries) -> list[str]:
    """Comando ScummVM, vazio quando não há ``.ini``."""

    ini = select_scummvm_config(entries)
    if ini is None:
        return []
    return ["scummvm", "-c", str(directory / ini)]


def launch_argv(game: MinigalaxyGame) -> list[str]:
    """argv do jogo, conforme o launcher detectado."""

    directory = game.directory
    launcher = game.launcher
    if launcher == "start_script":
        return [str(directory / "start.sh")]

    entries: list[str] = []
    if launcher in {"dosbox", "scummvm"}:
        try:
            entries = os.listdir(directory)
        except OSError:
            return []

    if launcher == "dosbox":
        return dosbox_command(directory, entries)
    if launcher == "scummvm":
        return scummvm_command(directory, entries)
    if launcher == "wine":
        return windows_command(directory, game)
    if launcher == "final_resort":
        return final_resort_command(game)
    return []


def launch_working_directory(game: MinigalaxyGame) -> str:
    """Diretório de trabalho, o mesmo ``cwd`` do upstream."""

    if game.launcher == "final_resort":
        return str(game.directory / "game")
    return str(game.directory)


def make_executable(game: MinigalaxyGame) -> str:
    """Comando persistido em ``Game.executable``.

    Junta os argumentos com :func:`shlex.join` para que a string resista ao
    ``/bin/sh -c`` usado por ``run_executable`` em caminhos com espaços e
    acentos. Devolve string vazia quando não há comando utilizável.
    """

    argv = launch_argv(game)
    if not argv:
        return ""
    return shlex.join(argv)


def _split_arguments(arguments: str) -> list[str]:
    """``arguments`` do ``playTask`` no clima do shlex, sem derrubar o jogo."""

    try:
        return shlex.split(arguments)
    except ValueError:
        # Argumento com aspas descasadas não pode matar a importação.
        return arguments.split()
