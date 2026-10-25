# appimage_scan.py
#
# Copyright 2026 Jolven contributors
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

"""Discovery of the AppImage files installed on the machine.

An AppImage is a self-contained executable: there is no catalog to read and
no service to ask, so the games are found by looking for the files
themselves. Everything here is filesystem and text work, with no GTK, so it
can be exercised without a display.
"""

import hashlib
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional

from gi.repository import GLib


#: Suffix of the AppImage files. The case varies between the projects that
#: publish them, so every comparison is made without it.
APPIMAGE_SUFFIX = ".appimage"

#: Magic number of the AppImage format: the file starts with "AI" and the
#: version of the format. Type 1 is the ISO9660 one and type 2 the squashfs
#: one; both are still in the wild.
APPIMAGE_MAGICS = (b"AI\x01", b"AI\x02")

#: Magic number of an ELF binary, the format of the payload of every
#: AppImage.
ELF_MAGIC = b"\x7fELF"

#: Suffixes of the icon files that sit next to an AppImage.
ICON_SUFFIXES = (".png", ".svg", ".xpm", ".webp", ".jpg", ".jpeg")

#: Tokens that name the machine a build was made for. They say nothing
#: about the game and are dropped from the name.
ARCH_TOKENS = frozenset(
    {
        "x86_64",
        "x86-64",
        "amd64",
        "x64",
        "x86",
        "i386",
        "i486",
        "i586",
        "i686",
        "32bit",
        "32-bit",
        "64bit",
        "64-bit",
        "arm64",
        "aarch64",
        "armhf",
        "armv7",
        "armv7l",
        "arm",
    }
)

#: Tokens that name the platform a build was made for.
PLATFORM_TOKENS = frozenset(
    {
        "linux",
        "linux64",
        "linux32",
        "linuxx86",
        "linuxx86_64",
        "unix",
    }
)

#: A version at the end of a name. The "v" is what tells a version from a
#: number that belongs to the title: "Portal 2" is a game, not a version.
VERSION_WITH_V_RE = re.compile(
    r"[\s\-_]*\(?v\d+(?:[.\s]\d+)*(?:[-._\s]?(?:beta|alpha|rc\d*))?\)?[\s]*$",
    re.IGNORECASE,
)

#: A dotted version at the end of a name ("SuperTuxKart 0.6.1").
VERSION_DOTTED_RE = re.compile(
    r"[\s\-_]*\(?\d+(?:[.\s]\d+)+(?:[-._\s]?(?:beta|alpha|rc\d*))?\)?[\s]*$",
    re.IGNORECASE,
)

#: Characters kept in the id of a game.
UNSAFE_ID_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")

#: The separators between the words of the name of a file.
SEPARATOR_RE = re.compile(r"^[\s\-]+$")

#: Names of the launchers the Jolven already knows as sources. An AppImage
#: with one of these names is a launcher, not a game: importing an emulator
#: in the middle of the library is noise. The names are the ones the
#: projects use in the file name of the build they publish.
KNOWN_LAUNCHERS = frozenset(
    {
        "appimagelauncher",
        "bottles",
        "cemu",
        "dolphin",
        "eden",
        "gamehub",
        "gamescope",
        "heroic",
        "heroic games launcher",
        "itch",
        "itch.io",
        "legendary",
        "lutris",
        "playonlinux",
        "protonup-qt",
        "retroarch",
        "steam",
        "twintail",
        "twintail launcher",
        "uzdoom",
        "yuzu",
    }
)

#: Names that also match when something else follows them: "Steam Linux
#: Runtime" is the runtime of the Steam, not a game with that name. The
#: short and ambiguous names are not here: "Dolphin Tale" is a game.
KNOWN_LAUNCHER_PREFIXES = frozenset(
    {
        "appimagelauncher",
        "bottles",
        "gamehub",
        "gamescope",
        "heroic",
        "legendary",
        "lutris",
        "playonlinux",
        "protonup-qt",
        "retroarch",
        "steam",
        "twintail",
    }
)

#: Characters that separate a name from what follows it. A name that only
#: starts with the name of a launcher is not a launcher: "itchy" is a game.
NAME_SEPARATORS = (" ", "-", "_", ".", "(", ")", "/", ",")


@dataclass(frozen=True)
class DesktopEntry:
    """A desktop entry that runs a program."""

    path: Path
    name: str
    categories: tuple[str, ...]
    icon: str
    programs: tuple[Path, ...]


def read_header(path: Path, size: int = 8) -> bytes:
    """The first bytes of a file, empty when it cannot be read."""
    try:
        with path.open("rb") as handle:
            return handle.read(size)
    except OSError:
        return b""


def has_appimage_suffix(path: Path) -> bool:
    """Whether the name of a file says that it is an AppImage."""
    return path.name.casefold().endswith(APPIMAGE_SUFFIX)


def is_appimage(path: Path) -> bool:
    """Whether a file is an AppImage.

    The magic number of the format is the reliable signal: the file starts
    with "AI" and the version of the format. The suffix is the fallback for
    the files that were renamed or repacked, and it is only trusted when
    the file is a program, so a text file that happens to be named
    "readme.appimage" is not a game.
    """
    header = read_header(path)
    if header[:3] in APPIMAGE_MAGICS:
        return True
    if not has_appimage_suffix(path):
        return False
    return header.startswith(ELF_MAGIC)


def find_appimages(roots: Iterable[Path], max_depth: int = 1) -> list[Path]:
    """The AppImage files found in the given folders.

    The walk is bounded: a folder of AppImages is a folder of files, and a
    deep tree is the data of a game, not another program.
    """
    found: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        for path in _walk_appimages(root, max_depth):
            key = _identity(path)
            if key in seen:
                continue
            seen.add(key)
            found.append(path)
    return found


def _identity(path: Path) -> Path:
    """The path that tells two files apart, symlinks included."""
    try:
        return path.resolve()
    except OSError:
        return path


def _walk_appimages(root: Path, max_depth: int) -> Iterator[Path]:
    """The AppImage files under a folder, up to a depth."""
    if not root.is_dir():
        return
    base_depth = len(root.parts)
    for dir_path, dir_names, file_names in os.walk(root):
        current = Path(dir_path)
        if len(current.parts) - base_depth >= max_depth:
            dir_names[:] = []
        for name in file_names:
            path = current / name
            if is_appimage(path):
                yield path


def default_roots(home: Path, extra: str = "") -> list[Path]:
    """The folders where AppImages are usually installed.

    The convention is the binary folder of the user, the folder
    AppImageLauncher uses and the usual home folders. The extra folder is
    the one the user chose in the preferences.
    """
    roots = [
        home / ".local" / "bin",
        home / "Applications",
        home / "bin",
        Path("/opt"),
    ]
    if extra and extra.strip():
        # The folder is made absolute: the executable of a game is the path
        # of the file, and a relative path would depend on the folder the
        # app happens to run from.
        roots.append(Path(os.path.abspath(os.path.expanduser(extra.strip()))))
    return roots


def clean_appimage_name(name: str) -> str:
    """The title of an AppImage, without the noise of the packaging.

    The build scripts of the projects append the version, the machine and
    the platform to the name of the file: "SuperTuxKart-0.6.1-x86_64" is
    the game "SuperTuxKart".
    """
    stem = name.strip()
    if stem.casefold().endswith(APPIMAGE_SUFFIX):
        stem = stem[: -len(APPIMAGE_SUFFIX)].strip()

    # The separators are kept: a dash can be part of the title ("Half-Life")
    # and only the tokens that name the build are dropped.
    parts = re.split(r"([\s\-]+)", stem)
    kept: list[str] = []
    index = 0
    while index < len(parts):
        part = parts[index]
        is_separator = index % 2 == 1
        is_noise = not is_separator and (
            part.casefold() in ARCH_TOKENS or part.casefold() in PLATFORM_TOKENS
        )
        if is_noise:
            # The separator that comes before the token goes with it, so the
            # title does not end with a dash.
            if kept and SEPARATOR_RE.match(kept[-1]):
                kept.pop()
            index += 2
            continue
        kept.append(part)
        index += 1

    title = "".join(kept)
    title = VERSION_WITH_V_RE.sub("", title)
    title = VERSION_DOTTED_RE.sub("", title)
    title = title.replace("_", " ").strip(" -–—.")

    return title or stem.replace("_", " ").strip() or name.strip()


def is_launcher_name(name: str) -> bool:
    """Whether the name of an AppImage is the name of a launcher.

    The name is the only signal: an AppImage carries no manifest the Jolven
    can read, and the desktop entry that may exist for it is not reliable
    either, since the launchers also claim the "Game" category.
    """
    normalized = " ".join(name.casefold().split())
    if not normalized:
        return False
    if normalized in KNOWN_LAUNCHERS:
        return True
    for launcher in KNOWN_LAUNCHER_PREFIXES:
        if not normalized.startswith(launcher):
            continue
        rest = normalized[len(launcher) :]
        if rest[:1] in NAME_SEPARATORS:
            return True
    return False


def appimage_id(path: Path) -> str:
    """The stable part of the id of a game, taken from the file name.

    The name of the file is the identity of the AppImage: it survives the
    move to another folder, and it does not depend on the title shown on
    screen.
    """
    stem = path.stem
    return UNSAFE_ID_CHARS_RE.sub("-", stem).strip("-._") or "appimage"


def appimage_id_suffix(path: Path) -> str:
    """A suffix that tells two AppImages of the same name apart."""
    digest = hashlib.sha256(str(path.parent).encode("utf-8", "replace"))
    return digest.hexdigest()[:6]


def programs_from_exec(exec_line: str) -> tuple[Path, ...]:
    """The absolute paths an Exec line runs.

    The field codes (``%U``, ``%F``) and the environment assignments of
    the line are ignored: only the paths are of interest here.
    """
    try:
        tokens = shlex.split(exec_line)
    except ValueError:
        tokens = exec_line.split()

    programs: list[Path] = []
    for token in tokens:
        if not token or token.startswith("-"):
            continue
        if "=" in token:
            # An environment assignment, not a program.
            continue
        if token.startswith("/"):
            programs.append(Path(token).expanduser())
    return tuple(programs)


def read_desktop_entry(path: Path) -> Optional[DesktopEntry]:
    """Read a desktop entry, ``None`` when it cannot be parsed."""
    keyfile = GLib.KeyFile.new()
    try:
        keyfile.load_from_file(str(path), 0)
    except GLib.Error:
        return None

    def get_string(key: str) -> str:
        try:
            return keyfile.get_string("Desktop Entry", key)
        except GLib.Error:
            return ""

    try:
        categories = keyfile.get_string_list("Desktop Entry", "Categories")
    except GLib.Error:
        categories = []

    return DesktopEntry(
        path=path,
        name=get_string("Name"),
        categories=tuple(category.casefold() for category in categories),
        icon=get_string("Icon"),
        programs=programs_from_exec(get_string("Exec")),
    )


def desktop_index(directories: Iterable[Path]) -> dict[Path, DesktopEntry]:
    """The desktop entries that run a program, indexed by that program.

    Both the path written in the entry and the real path of the file are
    indexed: an entry often points to a symlink that lives somewhere else.
    """
    index: dict[Path, DesktopEntry] = {}
    for directory in directories:
        if not directory.is_dir():
            continue
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.suffix != ".desktop":
                continue
            desktop = read_desktop_entry(entry)
            if desktop is None:
                continue
            for program in desktop.programs:
                index.setdefault(program, desktop)
                real = _identity(program)
                index.setdefault(real, desktop)
    return index


def find_desktop_entry(
    index: dict[Path, DesktopEntry], path: Path
) -> Optional[DesktopEntry]:
    """The desktop entry that runs a program, when there is one."""
    entry = index.get(path)
    if entry is not None:
        return entry
    return index.get(_identity(path))


def find_sibling_icon(appimage: Path, names: Iterable[str]) -> Optional[Path]:
    """The icon file that sits next to an AppImage.

    The build of a game usually leaves the icon beside the executable, and
    it is the best image available: it is the one the game ships with.
    """
    directory = appimage.parent
    candidates = [appimage.stem]
    for name in names:
        if not name:
            continue
        candidates.append(name)
        candidates.append(name.replace(" ", "_"))
        candidates.append(name.replace(" ", "-"))

    for candidate in candidates:
        for suffix in ICON_SUFFIXES:
            icon = directory / f"{candidate}{suffix}"
            if icon.is_file():
                return icon
    return None
