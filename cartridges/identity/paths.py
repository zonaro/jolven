# paths.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""De uma linha de comando para o arquivo do jogo (issue #110).

``Game.executable`` é uma string pronta para o shell — pode ser
``flatpak run org.libretro.RetroArch -L /usr/lib/core.so "/jogos/rom.sfc"``,
``dolphin-emu -b -e "/jogos/disco.rvz"`` ou ``xdg-open steam://run/123``. Achar
o arquivo dentro disso é o primeiro passo da identidade, e o resultado nunca é
executado: só ``Path`` existente, com extensão conhecida, fora de URLs.

Quando o importador já sabe o caminho (é o caso de RetroArch, Dolphin e Cemu),
ele deve mandar ``additional_data["identity_path"]``: string parsing é o plano B.
"""

from __future__ import annotations

import logging
import shlex
from pathlib import Path
from typing import Any, Iterable, Optional

from cartridges.identity.serials import EXTENSION_PLATFORMS

#: Tokens que são comandos, não arquivos.
_COMMAND_TOKENS = frozenset(
    {
        "flatpak",
        "run",
        "steam",
        "xdg-open",
        "gamemoderun",
        "mangohud",
        "env",
        "wine",
        "wine64",
        "proton",
        "bash",
        "sh",
        "-c",
        "python",
        "python3",
    }
)

#: Extensões que valem como arquivo de jogo mesmo fora do mapa principal.
_EXTRA_GAME_SUFFIXES = frozenset(
    {
        ".exe",
        ".appimage",
        ".sh",
        ".bat",
        ".ipk3",
        ".pk3",
        ".wad",
        ".zip",
        ".7z",
        ".rar",
        ".bin",
        ".cue",
        ".gdi",
        ".dat",
    }
)


def executable_tokens(executable: Any) -> list[str]:
    """Divide a linha de comando sem nunca levantar erro."""
    if isinstance(executable, (list, tuple)):
        return [str(item) for item in executable]
    if not isinstance(executable, str) or not executable.strip():
        return []
    try:
        return shlex.split(executable)
    except ValueError:
        return executable.split()


def _looks_like_path(token: str) -> bool:
    if not token or token.startswith("-") or "=" in token:
        return False
    if "://" in token:
        return False
    if token.lower() in _COMMAND_TOKENS:
        return False
    suffix = Path(token).suffix.lower()
    return "/" in token or suffix in EXTENSION_PLATFORMS or suffix in _EXTRA_GAME_SUFFIXES


def candidate_paths(executable: Any) -> list[Path]:
    """Caminhos plausíveis citados na linha de comando, na ordem de menção."""
    paths: list[Path] = []
    for token in executable_tokens(executable):
        if not _looks_like_path(token):
            continue
        try:
            candidate = Path(token).expanduser()
        except (OSError, ValueError):
            continue
        if candidate not in paths:
            paths.append(candidate)
    return paths


def _is_game_file(path: Path) -> bool:
    if not path.is_file():
        return False
    suffix = path.suffix.lower()
    return suffix in EXTENSION_PLATFORMS or suffix in _EXTRA_GAME_SUFFIXES


def choose_file(
    candidates: Iterable[Path], *, require_exists: bool = True
) -> Optional[Path]:
    """Escolhe o arquivo mais provável entre os candidatos.

    Arquivos que existem vencem; entre eles, quem tem extensão de jogo vence um
    ``.so``/``.cfg`` que só apareceu no meio da linha de comando.
    """
    existing = [path for path in candidates if path.is_file()]
    pool = existing or ([] if require_exists else list(candidates))
    if not pool:
        return None
    for path in pool:
        if _is_game_file(path):
            return path
    return pool[0]


def identity_path_from_data(additional_data: Optional[dict]) -> Optional[Path]:
    """Caminho explícito que o importador entregou, se ainda existir."""
    if not additional_data:
        return None
    for key in ("identity_path", "rom_path", "file_path"):
        value = additional_data.get(key)
        if isinstance(value, Path):
            candidate = value
        elif isinstance(value, str) and value:
            candidate = Path(value).expanduser()
        else:
            continue
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def game_file_path(game: Any, additional_data: Optional[dict] = None) -> Optional[Path]:
    """O arquivo que representa o jogo, ou ``None`` quando não há um.

    A ordem é: o que o importador sabia, o que a identidade já persistiu e, por
    último, a linha de comando. Um caminho que sumiu do disco não é devolvido:
    quem chama precisa saber que o arquivo não está mais lá.
    """
    explicit = identity_path_from_data(additional_data)
    if explicit is not None:
        return explicit

    identity = getattr(game, "identity", None) or {}
    stored = (identity.get("file") or {}).get("path") if isinstance(identity, dict) else None
    if isinstance(stored, str) and stored:
        try:
            path = Path(stored)
            if path.is_file():
                return path
        except OSError:
            pass

    try:
        return choose_file(candidate_paths(getattr(game, "executable", "")))
    except Exception:  # pylint: disable=broad-exception-caught
        logging.debug("Não foi possível extrair caminho de jogo", exc_info=True)
        return None
