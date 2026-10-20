# steam_source.py
#
# Copyright 2022-2023 redclaw
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

import logging
import re
from pathlib import Path
from typing import Iterable, NamedTuple, Optional

from cartridges import shared
from cartridges.game import Game
from cartridges.importer.location import Location, LocationSubPath
from cartridges.importer.source import SourceIterable, URLExecutableSource
from cartridges.utils.steam import (
    SteamAPIHelper,
    SteamFileHelper,
    SteamInvalidManifestError,
    SteamRateLimiter,
)

# Same game-type criterion as SteamAPIHelper.parse_app_data: only these
# store item types enter the library as games.
GAME_TYPES = frozenset({"game", "demo", "mod"})


class SteamSourceIterable(SourceIterable):
    source: "SteamSource"

    def get_manifest_dirs(self) -> Iterable[Path]:
        """Get dirs that contain Steam app manifests"""
        libraryfolders_path = self.source.locations.data["libraryfolders.vdf"]
        with open(libraryfolders_path, "r", encoding="utf-8") as file:
            contents = file.read()
        return [
            Path(path) / "steamapps"
            for path in re.findall('"path"\\s+"(.*)"\n', contents, re.IGNORECASE)
        ]

    def get_manifests(self) -> Iterable[Path]:
        """Get app manifests"""
        manifests = set()
        for steamapps_dir in self.get_manifest_dirs():
            if not steamapps_dir.is_dir():
                continue
            manifests.update(
                [
                    manifest
                    for manifest in steamapps_dir.glob("appmanifest_*.acf")
                    if manifest.is_file()
                ]
            )
        return manifests

    def get_librarycache_appids(self) -> set[str]:
        """Appids with a librarycache dir (seen locally, maybe uninstalled)."""
        librarycache = self.source.locations.data["librarycache"]
        if librarycache is None:
            return set()
        return {
            child.name
            for child in librarycache.iterdir()
            if child.is_dir() and child.name.isdigit()
        }

    def get_stored_name(self, game_id: str) -> Optional[str]:
        """Name already on record for `game_id`, if it needs no resolving.

        A game the store already holds (and that is not marked removed) is
        yielded again with the recorded name instead of spending a bulk
        lookup on it. Yielding — rather than skipping — matters: `add_game`
        records re-yielded games as duplicates, which is what keeps them
        from being pruned as missing; a skipped game would look gone.
        """
        try:
            stored = shared.store.get(game_id)
        except Exception:  # pylint: disable=broad-exception-caught
            return None
        if stored is None or getattr(stored, "removed", False):
            return None
        name = getattr(stored, "name", None)
        return name if isinstance(name, str) and name.strip() else None

    def build_owned_game(self, appid: str, name: str) -> tuple[Game, dict]:
        """Build an uninstalled owned game from its bulk-resolved name."""
        values = {
            "added": shared.import_time,
            "name": name,
            "source": self.source.source_id,
            "game_id": self.source.game_id_format.format(game_id=appid),
            "executable": self.source.make_executable(game_id=appid),
            "installed": False,
            "install_executable": f"xdg-open steam://install/{appid}",
        }
        game = Game(values)

        # Same cover pattern as installed games; the cover manager skips
        # paths that are not files, so a missing portrait simply adds none.
        image_path = (
            self.source.locations.data["librarycache"] / appid / "library_600x900.jpg"
        )
        additional_data = {"local_image_path": image_path, "steam_appid": appid}

        return (game, additional_data)

    def iter_owned_games(self, seen_appids: set[str]) -> Iterable[tuple[Game, dict]]:
        """Yield owned-but-never-installed games via bulk-resolved names."""
        try:
            appids = sorted(self.get_librarycache_appids() - seen_appids)
        except OSError as error:
            logging.debug("Skipping Steam owned discovery", exc_info=error)
            return
        if not appids:
            return

        names: dict[str, str] = {}
        to_resolve: list[str] = []
        for appid in appids:
            game_id = self.source.game_id_format.format(game_id=appid)
            if (stored_name := self.get_stored_name(game_id)) is not None:
                names[appid] = stored_name
            else:
                to_resolve.append(appid)

        if to_resolve:
            try:
                helper = SteamAPIHelper(SteamRateLimiter())
                infos = helper.get_store_basic_info_bulk(to_resolve)
            except Exception as error:  # pylint: disable=broad-exception-caught
                # No network, no names: the manifests above already yielded,
                # and the next import tries these appids again.
                logging.debug("Skipping Steam owned names", exc_info=error)
                infos = {}
            if not isinstance(infos, dict):
                infos = {}
            for appid in to_resolve:
                info = infos.get(appid)
                if not isinstance(info, dict):
                    continue
                name = info.get("name")
                if not isinstance(name, str) or not name.strip():
                    logging.debug("Skipping Steam owned appid %s: no usable name", appid)
                    continue
                if info.get("type") not in GAME_TYPES:
                    logging.debug("Skipping Steam owned appid %s: not a game", appid)
                    continue
                names[appid] = name

        for appid in appids:
            if appid in names:
                yield self.build_owned_game(appid, names[appid])

    def __iter__(self):
        """Generator method producing games"""
        appid_cache = set()
        manifests = self.get_manifests()

        for manifest in manifests:
            # Get metadata from manifest
            steam = SteamFileHelper()
            try:
                local_data = steam.get_manifest_data(manifest)
            except (OSError, SteamInvalidManifestError) as error:
                logging.debug("Couldn't load appmanifest %s", manifest, exc_info=error)
                continue

            # Manifests without the fully-installed bit are owned but not
            # installed. They always enter as uninstalled games.
            # Note: a game fully removed from disk leaves no local manifest;
            # what covers it is the librarycache heuristic below (see #44):
            # its dirs linger after uninstalls, but they can also hold
            # appids that were seen and never owned (demos, workshop items),
            # which the game-type filter drops.
            installed_mask = 4
            is_installed = bool(int(local_data["stateflags"]) & installed_mask)
            if not is_installed:
                logging.debug("Including %s: not installed", manifest)

            # Skip duplicate appids
            appid = local_data["appid"]
            if appid in appid_cache:
                logging.debug("Skipped %s: appid already seen during import", manifest)
                continue
            appid_cache.add(appid)

            # Build game from local data
            values = {
                "added": shared.import_time,
                "name": local_data["name"],
                "source": self.source.source_id,
                "game_id": self.source.game_id_format.format(game_id=appid),
                "executable": self.source.make_executable(game_id=appid),
                "installed": is_installed,
                "install_executable": (
                    f"xdg-open steam://install/{appid}"
                    if not is_installed
                    else ""
                ),
            }
            game = Game(values)

            # Add official cover image
            image_path = (
                self.source.locations.data["librarycache"]
                / appid
                / "library_600x900.jpg"
            )
            additional_data = {"local_image_path": image_path, "steam_appid": appid}

            yield (game, additional_data)

        # Owned-but-never-installed games have no manifest; resolve what the
        # librarycache still remembers in bulk. Never fatal: a failure here
        # only skips this step, and the next import retries the appids.
        try:
            yield from self.iter_owned_games(appid_cache)
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.debug("Skipping Steam owned discovery", exc_info=error)


class SteamLocations(NamedTuple):
    data: Location


class SteamSource(URLExecutableSource):
    source_id = "steam"
    name = _("Steam")
    available_on = {"linux"}
    iterable_class = SteamSourceIterable
    url_format = "steam://rungameid/{game_id}"

    locations: SteamLocations

    def __init__(self) -> None:
        super().__init__()
        self.locations = SteamLocations(
            Location(
                schema_key="steam-location",
                candidates=(
                    shared.home / ".steam" / "steam",
                    shared.data_dir / "Steam",
                    shared.flatpak_dir / "com.valvesoftware.Steam" / "data" / "Steam",
                    shared.programfiles32_dir / "Steam",
                    shared.app_support_dir / "Steam",
                ),
                paths={
                    "libraryfolders.vdf": LocationSubPath(
                        "steamapps/libraryfolders.vdf"
                    ),
                    "librarycache": LocationSubPath("appcache/librarycache", True),
                },
                invalid_subtitle=Location.DATA_INVALID_SUBTITLE,
            )
        )
