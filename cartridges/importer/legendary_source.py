# legendary_source.py
#
# Copyright 2023 Geoffrey Coulaud
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

import json
import logging
from json import JSONDecodeError
from typing import NamedTuple

from cartridges import shared
from cartridges.game import Game
from cartridges.importer.location import Location, LocationSubPath
from cartridges.importer.source import (
    ExecutableFormatSource,
    SourceIterable,
    SourceIterationResult,
)


class LegendarySourceIterable(SourceIterable):
    source: "LegendarySource"

    def game_from_library_entry(self, entry: dict) -> SourceIterationResult:
        # Skip non-games
        if entry["is_dlc"]:
            return None

        # Build game
        app_name = entry["app_name"]
        values = {
            "added": shared.import_time,
            "source": self.source.source_id,
            "name": entry["title"],
            "game_id": self.source.game_id_format.format(game_id=app_name),
            "executable": self.source.make_executable(app_name=app_name),
        }
        data = {}

        # Get additional metadata from file (optional)
        metadata_file = self.source.locations.config["metadata"] / f"{app_name}.json"
        try:
            metadata = json.load(metadata_file.open())
            values["developer"] = metadata["metadata"]["developer"]
            for image_entry in metadata["metadata"]["keyImages"]:
                if image_entry["type"] == "DieselGameBoxTall":
                    data["online_cover_url"] = image_entry["url"]
                    break
        except (JSONDecodeError, OSError, KeyError):
            pass

        game = Game(values)
        return (game, data)

    def game_from_uninstalled_metadata_entry(
        self, app_name: str, entry: dict
    ) -> SourceIterationResult:
        # Skip non-games
        if entry.get("is_dlc", False):
            return None

        # Build game (owned but not installed, from the offline metadata cache)
        title = entry.get("title", app_name)
        values = {
            "added": shared.import_time,
            "source": self.source.source_id,
            "name": title,
            "game_id": self.source.game_id_format.format(game_id=app_name),
            "executable": self.source.make_executable(app_name=app_name),
            "installed": False,
            "install_executable": f"legendary install {app_name} -y",
        }
        data: dict = {}

        # Get additional metadata from the same file (optional)
        try:
            values["developer"] = entry["metadata"]["developer"]
            for image_entry in entry["metadata"]["keyImages"]:
                if image_entry["type"] == "DieselGameBoxTall":
                    data["online_cover_url"] = image_entry["url"]
                    break
        except (KeyError, TypeError):
            pass

        logging.debug("Including Legendary game %s: not installed", app_name)
        game = Game(values)
        return (game, data)

    def __iter__(self):
        # Open library
        file = self.source.locations.config["installed.json"]
        try:
            library: dict = json.load(file.open())
        except (JSONDecodeError, OSError):
            logging.warning("Couldn't open Legendary file: %s", str(file))
            return

        installed_app_names: set[str] = set(library.keys())
        for installed_entry in library.values():
            if isinstance(installed_entry, dict):
                installed_app_name = installed_entry.get("app_name")
                if installed_app_name:
                    installed_app_names.add(installed_app_name)

        # Generate games from library
        for entry in library.values():
            try:
                result = self.game_from_library_entry(entry)
            except KeyError as error:
                # Skip invalid games
                logging.warning(
                    "Invalid Legendary game skipped in %s", str(file), exc_info=error
                )
                continue
            yield result

        # Owned but uninstalled games always come from the offline metadata
        # cache, populated on the first sync. A missing directory simply
        # means only installed games are imported.
        metadata_dir = self.source.locations.config["metadata"]
        if not metadata_dir.is_dir():
            logging.debug(
                "Skipped Legendary uninstalled games: no metadata dir at %s",
                str(metadata_dir),
            )
            return

        try:
            metadata_files = sorted(metadata_dir.glob("*.json"))
        except OSError as error:
            logging.debug(
                "Skipped Legendary uninstalled games: cannot list %s",
                str(metadata_dir),
                exc_info=error,
            )
            return

        for metadata_file in metadata_files:
            if metadata_file.stem in installed_app_names:
                continue
            try:
                metadata_entry: dict = json.load(metadata_file.open())
            except (JSONDecodeError, OSError) as error:
                logging.debug(
                    "Skipped Legendary metadata file %s",
                    str(metadata_file),
                    exc_info=error,
                )
                continue
            if not isinstance(metadata_entry, dict):
                logging.debug(
                    "Skipped Legendary metadata file %s: invalid content",
                    str(metadata_file),
                )
                continue
            app_name = metadata_entry.get("app_name", metadata_file.stem)
            if app_name in installed_app_names:
                continue
            try:
                result = self.game_from_uninstalled_metadata_entry(
                    app_name, metadata_entry
                )
            except KeyError as error:
                logging.warning(
                    "Invalid Legendary game skipped in %s",
                    str(metadata_file),
                    exc_info=error,
                )
                continue
            if result is None:
                continue
            installed_app_names.add(app_name)
            yield result


class LegendaryLocations(NamedTuple):
    config: Location


class LegendarySource(ExecutableFormatSource):
    source_id = "legendary"
    name = _("Legendary")
    executable_format = "legendary launch {app_name}"
    available_on = {"linux"}
    iterable_class = LegendarySourceIterable

    locations: LegendaryLocations

    def __init__(self) -> None:
        super().__init__()
        self.locations = LegendaryLocations(
            Location(
                schema_key="legendary-location",
                candidates=(
                    shared.config_dir / "legendary",
                    shared.host_config_dir / "legendary",
                ),
                paths={
                    "installed.json": LocationSubPath("installed.json"),
                    "metadata": LocationSubPath("metadata", True),
                },
                invalid_subtitle=Location.CONFIG_INVALID_SUBTITLE,
            )
        )
