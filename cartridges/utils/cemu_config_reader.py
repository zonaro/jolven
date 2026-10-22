"""Reads the Cemu (Wii U emulator) game database from settings.xml"""
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
from typing import Iterator, Optional
from xml.etree import ElementTree


def is_base_game_title(title_id: str) -> bool:
    """Tell if a Wii U title ID identifies a base game.

    Cemu's game cache also holds DLC (``0005000c``), updates
    (``0005000e``) and system titles (``00050010`` and up); only base
    games (``00050000``) belong in a game library.
    """
    return title_id.lower().startswith("00050000")


class CemuConfigReader:
    """Parse the game database out of a Cemu ``settings.xml``.

    Cemu (2.x) stores the game scan roots under ``<GamePaths>`` and a
    persistent game cache under ``<GameCache>``, each entry of which
    carries the title id, the display name and the path of the game's
    main RPX or disc file. See ``CemuConfig::Load`` in the Cemu project
    (src/config/CemuConfig.cpp).
    """

    def __init__(self, settings_file: Path) -> None:
        self.settings_file = settings_file

    def _content_root(self) -> Optional[ElementTree.Element]:
        """Return the element holding GamePaths/GameCache, or None.

        Cemu reads its settings from a ``<content>`` root but also
        accepts the keys directly at the document root, so both are
        handled here.
        """
        try:
            root = ElementTree.parse(self.settings_file).getroot()
        except (OSError, ElementTree.ParseError) as error:
            logging.warning(
                "Failed to read Cemu settings %s: %s", self.settings_file, error
            )
            return None
        if root.tag == "content":
            return root
        content = root.find("content")
        return content if content is not None else root

    def get_game_paths(self) -> list[str]:
        """Return the configured game scan directories"""
        content = self._content_root()
        if content is None:
            return []
        game_paths = content.find("GamePaths")
        if game_paths is None:
            return []
        return [
            entry.text.strip()
            for entry in game_paths.findall("Entry")
            if entry.text and entry.text.strip()
        ]

    def get_game_cache_entries(self) -> Iterator[dict[str, str]]:
        """Yield every parsed ``<GameCache>`` entry.

        Entries without a title ID or a file path are skipped. The
        yielded keys are ``title_id``, ``name``, ``custom_name`` and
        ``path``.
        """
        content = self._content_root()
        if content is None:
            return
        game_cache = content.find("GameCache")
        if game_cache is None:
            return
        for element in game_cache.findall("Entry"):
            title_id = (element.findtext("title_id") or "").strip()
            path = (element.findtext("path") or "").strip()
            if not title_id or not path:
                continue
            yield {
                "title_id": title_id,
                "name": (element.findtext("name") or "").strip(),
                "custom_name": (element.findtext("custom_name") or "").strip(),
                "path": path,
            }
