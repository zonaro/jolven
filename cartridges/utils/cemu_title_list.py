"""Reads the title list cache written by Cemu 2.x (``title_list_cache.xml``).

Cemu 2.x does not use the ``<GameCache>`` of ``settings.xml`` anymore:
that element is a legacy cache inherited from Cemu 1.x and is always
written empty. The titles Cemu knows about live in a separate file of the
Cemu *data* directory, ``title_list_cache.xml``, written by
``CafeTitleList::SaveCache`` (src/Cafe/TitleList/TitleList.cpp) when the
game list is scanned.

The file holds one ``<title>`` element per title, with the title id, the
display name and the path Cemu itself uses to launch it: the game folder
of an extracted game, the ``title.tmd`` of a NUS title or the archive of
a packed game.
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
from pathlib import Path
from typing import Iterable, NamedTuple, Optional
from xml.etree import ElementTree

# Name of the file Cemu writes in its data directory.
TITLE_LIST_CACHE_NAME = "title_list_cache.xml"


class CemuTitleListEntry(NamedTuple):
    """A title known by Cemu.

    ``title_id`` is the hexadecimal Wii U title id, ``name`` the display
    name shown by Cemu (it may be empty), ``path`` the path Cemu uses to
    launch the title and ``format`` the format of the title as Cemu
    classifies it.
    """

    title_id: str
    name: str
    path: Path
    format: int


def find_title_list_cache(candidates: Iterable[Path]) -> Optional[Path]:
    """Return the first candidate that is an existing file.

    The candidates are given by the caller, in order of preference. None
    is returned when no candidate exists.
    """
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def read_title_list_cache(path: Path) -> list[CemuTitleListEntry]:
    """Return the titles listed in a Cemu title list cache.

    A missing, unreadable or malformed file yields an empty list: the
    cache is an optional source of games and must never break the import.
    Entries without a title id or without a path are skipped.
    """
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError) as error:
        logging.warning(
            "Failed to read Cemu title list cache %s: %s", path, error
        )
        return []

    entries: list[CemuTitleListEntry] = []
    for element in root.iter("title"):
        title_id = (element.get("titleId") or "").strip()
        title_path = (element.findtext("path") or "").strip()
        if not title_id or not title_path:
            continue
        entries.append(
            CemuTitleListEntry(
                title_id=title_id,
                name=(element.findtext("name") or "").strip(),
                path=Path(title_path),
                format=_read_format(element),
            )
        )
    return entries


def _read_format(element: ElementTree.Element) -> int:
    """Return the format of a title, or zero when it is unknown."""
    raw = (element.findtext("format") or element.get("format") or "").strip()
    try:
        return int(raw)
    except ValueError:
        return 0
