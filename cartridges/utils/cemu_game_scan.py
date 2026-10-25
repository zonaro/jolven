"""Scans the game folders configured in Cemu for Wii U titles.

Cemu scans the directories listed in ``<GamePaths>`` of its
``settings.xml`` looking for titles (``CafeTitleList::ScanGamePath``,
src/Cafe/TitleList/TitleList.cpp). The rules are simple:

* a folder holding ``content``, ``code`` and ``meta`` is an extracted
  game, and the folder itself is the path Cemu launches;
* a file named ``title.tmd`` is a NUS title;
* a file with one of the known disc/archives extensions is a packed
  title.

Only the base games belong in a game library: DLC, updates and system
titles are skipped.
"""
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

import logging
import re
from pathlib import Path
from typing import Iterable, NamedTuple, Optional
from xml.etree import ElementTree

from cartridges.utils.cemu_config_reader import is_base_game_title

# Extensions of the files Cemu treats as a title.
GAME_FILE_EXTENSIONS = (".wud", ".wux", ".iso", ".wua", ".wuhb")

# Name of the file that describes a NUS title.
TITLE_TMD_NAME = "title.tmd"

# Folders an extracted game must hold.
EXTRACTED_GAME_FOLDERS = ("content", "code", "meta")

# The title id of a game folder is usually written between brackets,
# e.g. "Hyrule Warriors [Game] [000500001017d800]".
_TITLE_ID_PATTERN = re.compile(r"\[([0-9A-Fa-f]{16})\]")

# Any other bracketed group is decoration and is dropped from the name.
_GROUP_PATTERN = re.compile(r"\[[^\]]*\]")

# Keys of meta.ini that hold the name of a game, in order of preference.
_NAME_KEYS = ("longname_en", "shortname_en", "longname", "shortname")


class CemuScannedGame(NamedTuple):
    """A title found while scanning the game folders of Cemu.

    ``title_id`` is the hexadecimal Wii U title id, ``name`` the display
    name and ``path`` the path Cemu uses to launch the title.
    """

    title_id: str
    name: str
    path: Path


def clean_game_name(raw: str) -> str:
    """Return the name of a game without its bracketed groups."""
    cleaned = " ".join(_GROUP_PATTERN.sub(" ", raw).split())
    return cleaned or raw.strip()


def scan_game_paths(
    paths: Iterable[str | Path], *, max_depth: int = 6
) -> list[CemuScannedGame]:
    """Return the titles found in the given game folders.

    Every folder of ``paths`` is walked recursively, up to ``max_depth``
    levels below it. Missing folders are ignored and a title whose id
    cannot be determined is skipped.
    """
    games: list[CemuScannedGame] = []
    seen: set[str] = set()
    for raw_root in paths:
        root = Path(raw_root).expanduser()
        try:
            if not root.is_dir():
                logging.debug("Cemu game path is not a folder: %s", root)
                continue
        except OSError as error:
            logging.debug("Failed to read Cemu game path %s: %s", root, error)
            continue
        _scan_directory(root, games, seen, max_depth, 0)
    return games


def _scan_directory(
    directory: Path,
    games: list[CemuScannedGame],
    seen: set[str],
    max_depth: int,
    depth: int,
) -> None:
    """Walk a folder and collect the titles it holds."""
    try:
        entries = sorted(directory.iterdir(), key=lambda entry: entry.name)
    except OSError as error:
        logging.debug("Failed to list Cemu game folder %s: %s", directory, error)
        return

    folders: dict[str, Path] = {}
    for entry in entries:
        try:
            if entry.is_dir():
                folders[entry.name.lower()] = entry
        except OSError:
            continue

    if all(folder in folders for folder in EXTRACTED_GAME_FOLDERS):
        # An extracted game: the folder itself is the title and it is
        # never walked again.
        meta_dir = folders["meta"]
        code_dir = folders["code"]
        title_id = (
            _title_id_from_xml(meta_dir / "meta.xml")
            or _title_id_from_xml(code_dir / "app.xml")
            or _title_id_from_name(directory.name)
        )
        name = _name_from_meta_ini(meta_dir / "meta.ini") or clean_game_name(
            directory.name
        )
        _add_game(games, seen, title_id, name, directory)
        return

    for entry in entries:
        try:
            is_folder = entry.is_dir()
        except OSError:
            continue
        if is_folder:
            if entry.name.startswith("."):
                continue
            if depth + 1 > max_depth:
                continue
            _scan_directory(entry, games, seen, max_depth, depth + 1)
            continue
        if entry.name == TITLE_TMD_NAME:
            if _is_incomplete_download(entry.parent):
                logging.debug(
                    "Skipping the Cemu title %s: its download is incomplete",
                    entry.parent,
                )
                continue
            _add_file_game(games, seen, entry, use_parent_name=True)
        elif entry.suffix.lower() in GAME_FILE_EXTENSIONS:
            _add_file_game(games, seen, entry, use_parent_name=False)


def _is_incomplete_download(directory: Path) -> bool:
    """Tell whether the content of a NUS title was not fully downloaded.

    The downloader of the Wii U dumps writes the content it did not
    finish yet as ``<id>.app.part`` files. A content without its final
    file means the title cannot be mounted, so it is not a game yet.
    """

    try:
        parts = sorted(directory.glob("*.app.part"))
    except OSError as error:
        logging.debug("Failed to list %s: %s", directory, error)
        return False

    for part in parts:
        content_id = part.name[: -len(".app.part")]
        try:
            if not (directory / f"{content_id}.app").is_file():
                return True
        except OSError:
            return True
    return False


def _add_file_game(
    games: list[CemuScannedGame],
    seen: set[str],
    path: Path,
    *,
    use_parent_name: bool,
) -> None:
    """Collect a title that is a single file."""
    title_id = _title_id_from_name(path.name) or _title_id_from_name(path.parent.name)
    if use_parent_name:
        name = clean_game_name(path.parent.name)
    else:
        name = clean_game_name(path.stem)
    _add_game(games, seen, title_id, name, path)


def _add_game(
    games: list[CemuScannedGame],
    seen: set[str],
    title_id: str,
    name: str,
    path: Path,
) -> None:
    """Add a title to the result, skipping the ones that are not games."""
    if not title_id:
        logging.debug("Skipping Cemu title without an id: %s", path)
        return
    if not is_base_game_title(title_id):
        return
    key = title_id.lower()
    if key in seen:
        return
    seen.add(key)
    games.append(CemuScannedGame(title_id=title_id, name=name, path=path))


def _title_id_from_name(name: str) -> str:
    """Return the title id written between brackets in a name."""
    match = _TITLE_ID_PATTERN.search(name)
    return match.group(1) if match else ""


def _title_id_from_xml(path: Path) -> str:
    """Return the title id of a ``meta.xml`` or ``app.xml`` file."""
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError) as error:
        logging.debug("Failed to read %s: %s", path, error)
        return ""
    for element in root.iter("title_id"):
        title_id = (element.text or "").strip()
        if title_id:
            return title_id
    return (root.get("title_id") or "").strip()


def _name_from_meta_ini(path: Path) -> Optional[str]:
    """Return the name of a game, as written in its ``meta.ini``."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        logging.debug("Failed to read %s: %s", path, error)
        return None
    values: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip().lower()] = value.strip()
    for key in _NAME_KEYS:
        value = values.get(key)
        if value:
            return value
    return None
