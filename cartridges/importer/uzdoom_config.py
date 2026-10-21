# uzdoom_config.py
#
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2026 Geoffrey Coulaud

"""Reading of the UZDoom configuration file (``uzdoom.ini``).

UZDoom keeps the folders it searches in its own configuration file. The
file is an INI file: the folders of the base games (the IWADs) live in
the ``[IWADSearch.Directories]`` section and the folders of the mods
(the PWADs and the PK3s) in the ``[FileSearch.Directories]`` section.
UZDoom has no separate "mods folder": a mod is a file found in one of
the folders the engine searches.

The module only reads the file. It never writes it, never touches the
network and never talks to the user, and it does not import GTK, so it
can be read and tested on its own.
"""

import logging
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Optional

#: The section of ``uzdoom.ini`` that holds the folders of the IWADs.
IWAD_SECTION = "IWADSearch.Directories"

#: The section of ``uzdoom.ini`` that holds the folders of the mods.
FILE_SECTION = "FileSearch.Directories"

#: The keys of a search section. "PathList" holds several folders
#: separated by a colon, and "RecursivePath" is a folder like "Path".
PATH_KEYS = ("path", "pathlist", "recursivepath")

#: The comment styles of the format. A semicolon is not a comment.
COMMENT_PREFIXES = ("#", "//")

#: The configuration files of UZDoom, relative to the home directory.
CONFIG_FILES = (
    ".config/uzdoom/uzdoom.ini",
    ".config/uzdoom.ini",
    ".var/app/org.zdoom.UZDoom/config/uzdoom/uzdoom.ini",
)

#: The share folders the engine adds by itself, with the subfolders it
#: looks into. They are not the choice of the user.
ENGINE_DEFAULT_SHARES = ("/usr/share", "/usr/local/share", "/app/share")

#: The subfolders of a share folder the engine adds by itself.
ENGINE_DEFAULT_SUFFIXES = ("games/uzdoom", "games/doom", "doom")

#: The folders the engine adds by itself inside the home directory.
ENGINE_DEFAULT_HOME = (
    ".local/share/games/uzdoom",
    ".local/share/games/doom",
    ".local/share/doom",
)

#: A variable of the value of a folder.
_VARIABLE = re.compile(r"\$(\w+)|\$\{([^}]*)\}")


class _UnsetVariable(Exception):
    """Raised when a value holds a variable that is not set."""


def default_home() -> Path:
    """The home directory of the user.

    The project keeps the home directory in ``shared``, but the module is
    also used outside the application (the tests), where that module may
    not exist or may not hold the home directory.
    """

    try:
        # pylint: disable=import-outside-toplevel
        from cartridges import shared

        return Path(shared.home)
    except Exception:  # pylint: disable=broad-except
        return Path.home()


def _resolve(text: str, *, home: Path) -> str:
    """The absolute and normalized form of *text*.

    The home directory expands a leading ``~``. A relative path is
    resolved against the current directory, like the engine does.
    """

    expanded = text
    if expanded.startswith("~"):
        expanded = str(home) + expanded[1:]
    path = Path(expanded)
    if not path.is_absolute():
        path = Path.cwd() / path
    return os.path.normpath(str(path))


def _engine_defaults(*, home: Path) -> set[str]:
    """The folders the engine adds by itself, in absolute form."""

    defaults: set[str] = set()
    for share in ENGINE_DEFAULT_SHARES:
        defaults.add(_resolve(share, home=home))
        for suffix in ENGINE_DEFAULT_SUFFIXES:
            defaults.add(_resolve(f"{share}/{suffix}", home=home))
    for suffix in ENGINE_DEFAULT_HOME:
        defaults.add(_resolve(f"~/{suffix}", home=home))
    return defaults


def find_config_files(
    *,
    env: Optional[Mapping[str, str]] = None,
    home: Optional[Path] = None,
) -> list[Path]:
    """The configuration files of UZDoom that exist, in priority order.

    The files are the native one and the one of the Flatpak. The list
    only holds the files that exist, and the same file is never twice.
    """

    env = os.environ if env is None else env
    home = default_home() if home is None else home

    candidates: list[Path] = []
    xdg_config = (env.get("XDG_CONFIG_HOME") or "").strip()
    if xdg_config:
        candidates.append(Path(xdg_config) / "uzdoom" / "uzdoom.ini")
    candidates.extend(home / relative for relative in CONFIG_FILES)

    found: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            if not candidate.is_file():
                continue
        except OSError:
            continue
        key = os.path.normpath(str(candidate))
        if key in seen:
            continue
        seen.add(key)
        found.append(candidate)
    return found


def _skip_block(lines: list[str], index: int) -> int:
    """The index of the line after the end of a multi-line value."""

    while index < len(lines):
        line = lines[index]
        index += 1
        if ">>>" in line:
            break
    return index


def parse_section_paths(ini_path: Path, section: str) -> list[str]:
    """The folder values of *section* in the INI file *ini_path*.

    The values are returned in the order of the file and without any
    expansion: the caller decides what to do with them. The section and
    the key names are case insensitive, the values are not.
    """

    try:
        raw = ini_path.read_bytes()
    except OSError as error:
        logging.debug("Could not read the UZDoom configuration: %s", error)
        return []

    text = raw.decode("utf-8", errors="replace").replace("\r", "")
    wanted = section.strip().lower()

    values: list[str] = []
    inside = False
    lines = text.split("\n")
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        index += 1

        if not stripped or stripped.startswith(COMMENT_PREFIXES):
            continue

        if stripped.startswith("[") and stripped.endswith("]"):
            inside = stripped[1:-1].strip().lower() == wanted
            continue

        if not inside or "=" not in stripped:
            continue

        key, _, value = stripped.partition("=")
        key = key.strip().lower()
        value = value.strip()
        if key not in PATH_KEYS:
            continue

        if "<<<" in value:
            # A multi-line value: it holds no folder, and the parser
            # skips to the end of the block to not read it as keys.
            if ">>>" not in value:
                index = _skip_block(lines, index)
            continue

        if key == "pathlist":
            for part in value.split(":"):
                part = part.strip()
                if part:
                    values.append(part)
            continue

        if value:
            values.append(value)

    return values


def expand_entry(
    value: str,
    *,
    env: Optional[Mapping[str, str]] = None,
    home: Optional[Path] = None,
) -> Optional[str]:
    """The value of a folder with ``~`` and ``$VAR`` expanded.

    ``None`` is returned when the value cannot be used: it is empty, or
    it holds a variable that is not set. The variables of the engine
    (``$DOOMWADDIR``, ``$DOOMWADPATH``, ``$PROGDIR``) are usually not
    set, and a folder that depends on them is not the choice of the
    user.
    """

    env = os.environ if env is None else env
    home = default_home() if home is None else home

    text = value.strip()
    if not text:
        return None

    def substitute(match: "re.Match[str]") -> str:
        """The value of a variable of the text."""

        name = match.group(1) or match.group(2) or ""
        if not name:
            return match.group(0)
        if name == "HOME":
            return str(home)
        found = env.get(name)
        if not found:
            raise _UnsetVariable
        return found

    try:
        expanded = _VARIABLE.sub(substitute, text)
    except _UnsetVariable:
        return None

    if expanded.startswith("~"):
        expanded = str(home) + expanded[1:]
    return expanded or None


def is_engine_default(path: Path, *, home: Optional[Path] = None) -> bool:
    """Whether *path* is a folder the engine adds by itself."""

    home = default_home() if home is None else home

    text = str(path).strip()
    if not text:
        return False
    if text in (".", "./"):
        return True
    return _resolve(text, home=home) in _engine_defaults(home=home)


def search_dirs(
    section: str,
    *,
    env: Optional[Mapping[str, str]] = None,
    home: Optional[Path] = None,
) -> list[str]:
    """The folders of *section*, detected in the configuration of UZDoom.

    The configuration files are read in the order of the priority and the
    folders of all of them are merged. The folders the engine adds by
    itself are dropped, and the same folder is kept only once.
    """

    env = os.environ if env is None else env
    home = default_home() if home is None else home

    found: list[str] = []
    seen: set[str] = set()
    for ini_path in find_config_files(env=env, home=home):
        for raw in parse_section_paths(ini_path, section):
            expanded = expand_entry(raw, env=env, home=home)
            if expanded is None:
                continue
            if is_engine_default(Path(expanded), home=home):
                continue
            resolved = _resolve(expanded, home=home)
            if resolved in seen:
                continue
            seen.add(resolved)
            found.append(resolved)
    return found
