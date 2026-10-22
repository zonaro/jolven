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

from pathlib import Path
from shlex import quote as shell_quote
from typing import NamedTuple

from cartridges import shared
from cartridges.game import Game
from cartridges.importer.location import Location, LocationSubPath
from cartridges.importer.source import ExecutableFormatSource, SourceIterable
from cartridges.utils.cemu_config_reader import CemuConfigReader, is_base_game_title


class CemuSourceIterable(SourceIterable):
    source: "CemuSource"

    def __iter__(self):
        cache_reader = CemuConfigReader(self.source.locations.config["settings_file"])

        for entry in cache_reader.get_game_cache_entries():
            # The cache is persistent and may be stale: ignore entries
            # whose game is gone, and everything that is not a base
            # game (DLC, updates, system titles)
            if not is_base_game_title(entry["title_id"]):
                continue
            rom_path = Path(entry["path"])
            if not rom_path.is_file():
                continue

            values = {
                "source": self.source.source_id,
                "added": shared.import_time,
                "name": entry["custom_name"] or entry["name"] or rom_path.stem,
                "game_id": self.source.game_id_format.format(
                    game_id=entry["title_id"]
                ),
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

    @property
    def executable_format(self) -> str:
        self.locations.config.resolve()
        is_flatpak = self.locations.config.root.is_relative_to(shared.flatpak_dir)
        base = "flatpak run info.cemu.Cemu" if is_flatpak else "Cemu"
        return f"{base} -f -g {{rom_path}}"

    def make_executable(self, rom_path: Path) -> str:
        return self.executable_format.format(rom_path=shell_quote(str(rom_path)))
