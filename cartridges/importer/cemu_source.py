# cemu_source.py
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

import logging
from pathlib import Path
from shlex import quote as shell_quote
from typing import Iterable, NamedTuple, Optional

from cartridges import shared
from cartridges.game import Game
from cartridges.importer.location import Location, LocationSubPath
from cartridges.importer.source import ExecutableFormatSource, SourceIterable
from cartridges.utils.cemu_config_reader import CemuConfigReader, is_base_game_title
from cartridges.utils.cemu_game_scan import clean_game_name, scan_game_paths
from cartridges.utils.cemu_title_list import (
    TITLE_LIST_CACHE_NAME,
    find_title_list_cache,
    read_title_list_cache,
)


def canonical_title_id(title_id: str) -> str:
    """Return the canonical form of a Wii U title id.

    Title ids are hexadecimal and case insensitive: the legacy cache
    writes them in upper case and the title list cache in lower case, so
    they are normalized to be merged into a single title.
    """
    return title_id.strip().upper()


class _CemuTitle:
    """A title of Cemu, gathered from every source that knows it.

    The names and the paths are kept in order of preference: the first
    name is the one shown to the user and the first existing path is the
    one used to launch the game.
    """

    __slots__ = ("names", "paths")

    def __init__(self) -> None:
        self.names: list[str] = []
        self.paths: list[Path] = []

    def add(self, names: Iterable[str], path: Path) -> None:
        """Register the names and the path of the title.

        The names are given in order of preference and the first one
        that is not empty is the name of the title.
        """
        for name in names:
            if name:
                self.names.append(name)
        self.paths.append(path)

    def display_name(self) -> str:
        """Return the name of the title, or an empty string."""
        return self.names[0] if self.names else ""

    def existing_path(self) -> Optional[Path]:
        """Return the first path of the title that still exists."""
        for path in self.paths:
            try:
                if path.exists():
                    return path
            except OSError:
                continue
        return None


class CemuSourceIterable(SourceIterable):
    source: "CemuSource"

    def __iter__(self):
        config = self.source.locations.config
        config.resolve()
        settings_file = config["settings_file"]
        cache_reader = CemuConfigReader(settings_file)

        titles: dict[str, _CemuTitle] = {}

        def remember(title_id: str, names: Iterable[str], path: Path) -> None:
            title = titles.get(title_id)
            if title is None:
                title = _CemuTitle()
                titles[title_id] = title
            title.add(names, path)

        # The legacy cache of Cemu 1.x carries the custom names, so it
        # comes first: its names win over every other source.
        for entry in cache_reader.get_game_cache_entries():
            title_id = canonical_title_id(entry["title_id"])
            if not title_id:
                continue
            remember(
                title_id,
                (entry["custom_name"], entry["name"]),
                Path(entry["path"]),
            )

        # The title list cache of Cemu 2.x holds the games Cemu knows.
        title_list = find_title_list_cache(self.source.title_list_candidates())
        if title_list is not None:
            for entry in read_title_list_cache(title_list):
                title_id = canonical_title_id(entry.title_id)
                if not title_id:
                    continue
                remember(title_id, (entry.name,), entry.path)

        # The game folders of Cemu are scanned, so the games are imported
        # even when Cemu never wrote its own cache.
        for scanned in scan_game_paths(cache_reader.get_game_paths()):
            title_id = canonical_title_id(scanned.title_id)
            if not title_id:
                continue
            remember(title_id, (scanned.name,), scanned.path)

        logging.debug("Cemu knows %d titles", len(titles))

        for title_id, title in titles.items():
            # Only the base games belong in a game library: DLC, updates
            # and system titles are skipped.
            if not is_base_game_title(title_id):
                continue
            # The paths of the caches may be stale, so the title is only
            # imported when one of them still exists.
            rom_path = title.existing_path()
            if rom_path is None:
                continue

            values = {
                "source": self.source.source_id,
                "added": shared.import_time,
                "name": title.display_name() or clean_game_name(rom_path.stem),
                "game_id": self.source.game_id_format.format(game_id=title_id),
                "executable": self.source.make_executable(rom_path=rom_path),
            }

            yield Game(values), {}


class CemuLocations(NamedTuple):
    config: Location


class CemuSource(ExecutableFormatSource):
    name = _("Cemu")
    source_id = "cemu"
    available_on = {"linux"}
    iterable_class = CemuSourceIterable

    locations: CemuLocations

    def __init__(self) -> None:
        super().__init__()
        self.locations = CemuLocations(
            Location(
                schema_key="cemu-location",
                candidates=(
                    shared.flatpak_dir / "info.cemu.Cemu" / "config" / "Cemu",
                    shared.config_dir / "Cemu",
                    shared.host_config_dir / "Cemu",
                ),
                paths={"settings_file": LocationSubPath("settings.xml")},
                invalid_subtitle=Location.CONFIG_INVALID_SUBTITLE,
            )
        )

    def title_list_candidates(self) -> list[Path]:
        """Return the paths where Cemu may keep its title list cache.

        Cemu writes the cache in its data directory, which is not the
        folder of its configuration: the Flatpak keeps them apart
        (``config/Cemu`` and ``data/Cemu``) and a native installation
        uses the XDG data directory.

        The configuration location must be resolved before.
        """
        config = self.locations.config
        root = config.root
        if root is None:
            return []

        candidates = [root / TITLE_LIST_CACHE_NAME]
        parent = root.parent
        if parent.name == "config":
            # A Flatpak installation: the data folder is a sibling of
            # the configuration folder.
            candidates.append(parent.parent / "data" / "Cemu" / TITLE_LIST_CACHE_NAME)
        candidates.append(shared.host_data_dir / "Cemu" / TITLE_LIST_CACHE_NAME)
        return candidates

    @property
    def executable_format(self) -> str:
        self.locations.config.resolve()
        is_flatpak = self.locations.config.root.is_relative_to(shared.flatpak_dir)
        base = "flatpak run info.cemu.Cemu" if is_flatpak else "Cemu"
        return f"{base} -f -g {{rom_path}}"

    def make_executable(self, rom_path: Path) -> str:
        return self.executable_format.format(rom_path=shell_quote(str(rom_path)))
