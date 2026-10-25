# epic_source.py
#
# Copyright 2026 zonaro
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

"""The native Epic Games Launcher for Linux (EGLv2).

This is the launcher Epic ships as an AppImage — a Tauri/Rust application —
and it is a different program from the Electron launcher it replaced, so it
shares no files with Heroic or Legendary. Everything it needs is read from
disk:

* ``installations.jsonl`` says what is installed, one JSON record per line
  after a header line. It is append-only, so the same ``installationId``
  shows up repeatedly and the newest line for it is the current state.
* ``cache/prod/catalog-cache.json`` supplies the title, developer and cover
  the install list does not carry. It is joined by ``itemId``.
* ``cache/images/<md5>.jpg`` holds covers the launcher already downloaded.

Games start through the deep link the launcher registers as the system
handler for ``x-scheme-handler/com.epicgames.launcher``. Nothing here needs
the network, a running launcher or credentials, which is what separates this
source from Heroic (which reads Legendary's data) and Legendary itself.
"""

import json
import logging
from json import JSONDecodeError
from pathlib import Path
from typing import Any, NamedTuple, Optional

from cartridges import shared
from cartridges.game import Game
from cartridges.importer.location import Location, LocationSubPath
from cartridges.importer.source import (
    ExecutableFormatSource,
    SourceIterable,
    SourceIterationResult,
    SourceScanError,
)

# The launcher's directory inside the XDG data and cache folders; the same
# string is the app's Tauri identifier.
APP_DIRECTORY = "com.epicgames.eglv2"

# Flatpak ids that may host the launcher. The launcher only publishes one of
# them, and which one is not knowable from this side, so both are offered to
# the location resolver, which keeps the first root that really has the data.
FLATPAK_IDS = ("com.epicgames.EpicGamesLauncher", APP_DIRECTORY)

# The append-only install list: a header line, then one record per line.
INSTALLATIONS_FILE = "installations.jsonl"

# The cached catalog, relative to the data directory.
CATALOG_CACHE_FILE = "cache/prod/catalog-cache.json"

# Covers the launcher downloaded, keyed by the md5 of the catalog image.
IMAGES_DIRECTORY = "images"

# The deep link the launcher handles. The path segment is the artifact's
# ``appId`` ("Turtle", "Fowl", …): passing the ``itemId``, the title or an
# install path there is rejected by the launcher with
# ``DeepLink.AppNameUnresolved``, which was verified against a running
# launcher. The query string is quoted by ``executable_format`` so the shell
# never globs the ``?``.
DEEP_LINK_FORMAT = "com.epicgames.launcher://apps/{app_id}?action=launch"

# The portrait cover key image shared with Epic's own catalog and with the
# Legendary and Heroic caches.
COVER_IMAGE_TYPE = "DieselGameBoxTall"

_ERROR_TITLE = _("Could not read the Epic Games launcher library")
_ERROR_SUBTITLE = _(
    "Close the Epic Games Launcher so it finishes writing, then import again."
)


class Installations(NamedTuple):
    """One ``installations.jsonl`` copy, whatever it turned out to be."""

    # ``installationId`` -> record; for one installation the last line wins.
    entries: dict[str, dict[str, Any]]
    # The header's ``writtenAt``, used to rank this copy against the backup.
    written_at: str
    # A line that is not valid JSON: the copy was read mid-write.
    torn: bool
    # The copy exists but could not be read or decoded.
    unreadable: bool
    # The copy is not there at all.
    absent: bool

    @property
    def usable(self) -> bool:
        """Whether this copy can speak for the whole install list."""
        return not (self.torn or self.unreadable or self.absent)


def _read_installations(path: Path) -> Installations:
    """Read one copy of the install list without judging what it means."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Installations({}, "", False, False, True)
    except (OSError, UnicodeDecodeError):
        logging.debug("Could not read the Epic install list %s", path, exc_info=True)
        return Installations({}, "", False, True, False)

    header: dict[str, Any] = {}
    entries: dict[str, dict[str, Any]] = {}
    torn = False

    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except JSONDecodeError:
            # Append-only, so an unparseable line means the launcher was
            # still writing: nothing from here on can be trusted.
            torn = True
            break
        if not isinstance(record, dict):
            torn = True
            break
        installation_id = record.get("installationId")
        if isinstance(installation_id, str) and installation_id:
            # Records are appended, never rewritten: the newest line for an
            # installation is its current state, and a removal is a record
            # without an install directory.
            entries[installation_id] = record
        elif not header:
            # The first line is the header: version, writtenAt, entries.
            header = record

    written_at = header.get("writtenAt")
    return Installations(
        entries=entries,
        written_at=written_at if isinstance(written_at, str) else "",
        torn=torn,
        unreadable=False,
        absent=False,
    )


def _load_installations(primary: Path) -> dict[str, dict[str, Any]]:
    """Read the install list, honouring the backup the launcher keeps.

    The list can be caught mid-write, so the launcher also writes
    ``installations.jsonl.prev`` and picks between the two copies by
    completeness and then by ``writtenAt``. The same rules run here, because
    the importer prunes every game a scan did not return: publishing a
    partial list would silently delete games that are still installed.

    :raises SourceScanError: when no copy can be trusted.
    """
    current = _read_installations(primary)

    if current.usable:
        return current.entries

    if current.absent:
        # The location already requires the file, so this is a race with the
        # launcher rather than an empty library — an empty library is a file
        # with a header and no records.
        raise SourceScanError(_ERROR_TITLE, _ERROR_SUBTITLE)

    previous = _read_installations(primary.with_name(f"{primary.name}.prev"))

    if previous.usable and current.unreadable:
        # A primary that could not be read leaves nothing to compare.
        return previous.entries
    if (
        previous.usable
        and current.written_at
        and previous.written_at > current.written_at
    ):
        # "The primary is incomplete and the backup is more recent."
        return previous.entries

    # "The primary is incomplete but still the more recent copy": there is no
    # newer good copy to fall back on, and the records that were parsed say
    # nothing about the ones the write had not reached yet.
    raise SourceScanError(_ERROR_TITLE, _ERROR_SUBTITLE)


def _read_catalog(root: Path) -> dict[str, dict[str, Any]]:
    """Read the launcher's catalog cache, keyed by catalog item id.

    Missing or corrupt cache is not a scan failure: the games still import
    under the name of their executable, just without developer or cover.
    """
    path = root / CATALOG_CACHE_FILE
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError, JSONDecodeError):
        logging.debug(
            "Could not read the Epic catalog cache %s", path, exc_info=True
        )
        return {}

    items = document.get("items") if isinstance(document, dict) else None
    if not isinstance(items, dict):
        return {}

    catalog: dict[str, dict[str, Any]] = {}
    for item_id, wrapped in items.items():
        item = wrapped.get("item") if isinstance(wrapped, dict) else None
        if isinstance(item_id, str) and isinstance(item, dict):
            catalog[item_id] = item
    return catalog


def _cached_image(images_dir: Optional[Path], md5: Any) -> Optional[Path]:
    """Resolve a cached bitmap by the md5 the catalog gave the image."""
    if images_dir is None:
        return None
    # The md5 becomes a path component, so it must stay a bare name: no
    # separator, no dot, no way out of the cache directory.
    if not (isinstance(md5, str) and len(md5) == 32 and md5.isalnum()):
        return None
    # The launcher stores the bitmap as <md5>.jpg regardless of the original
    # format of the download.
    for name in (f"{md5}.jpg", md5):
        candidate = images_dir / name
        if candidate.is_file():
            return candidate
    return None


def _cover_data(
    item: Optional[dict[str, Any]], images_dir: Optional[Path]
) -> dict[str, Any]:
    """Cover art: the bitmap the launcher already has, else its URL."""
    if not item:
        return {}
    key_images = item.get("keyImages")
    if not isinstance(key_images, list):
        return {}
    for image in key_images:
        if not isinstance(image, dict) or image.get("type") != COVER_IMAGE_TYPE:
            continue
        local = _cached_image(images_dir, image.get("md5"))
        if local is not None:
            return {"local_image_path": local}
        url = image.get("url")
        if isinstance(url, str) and url.startswith("https://"):
            return {"online_cover_url": url}
        return {}
    return {}


def _title_of(entry: dict[str, Any], item: Optional[dict[str, Any]]) -> str:
    """A display name: the catalog title, else what the record carries.

    ``installations.jsonl`` has no title at all, so without the catalog
    cache the launch executable is the only human-readable thing left.
    """
    if item:
        title = item.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
    executable = entry.get("launchExecutable")
    if isinstance(executable, str) and executable.strip():
        stem = Path(executable).stem.strip()
        if stem:
            return stem
    # The caller rejects records without an artifact id, so this always
    # yields a name without needing a string of its own to translate.
    return str(entry.get("artifactId") or entry.get("itemId") or "")


class EpicSourceIterable(SourceIterable):
    """Games produced from the native launcher's install list."""

    source: "EpicSource"

    def game_from_installation(
        self,
        entry: dict[str, Any],
        catalog: dict[str, dict[str, Any]],
        images_dir: Optional[Path],
    ) -> SourceIterationResult:
        """Build one game from an install record.

        :return: the game with its cover data, or ``None`` for a record that
            describes no game on this machine.
        """
        # A removal is recorded as a tombstone, and a record whose install
        # directory is gone is one the launcher itself drops.
        if entry.get("deleted"):
            return None
        item_id = entry.get("itemId")
        artifact_id = entry.get("artifactId")
        directory = entry.get("dir")
        if not (isinstance(item_id, str) and item_id):
            return None
        if not (isinstance(artifact_id, str) and artifact_id):
            return None
        if not (isinstance(directory, str) and directory):
            return None

        install_dir = Path(directory).expanduser()
        if not install_dir.is_dir():
            logging.debug(
                "Epic game %s skipped: install directory %s is gone",
                item_id,
                install_dir,
            )
            return None

        item = catalog.get(item_id)
        values: dict[str, Any] = {
            "added": shared.import_time,
            "source": self.source.source_id,
            "name": _title_of(entry, item),
            # The catalog item, not the installation: reinstalling keeps the
            # same id, so playtime, notes and covers survive it.
            "game_id": self.source.game_id_format.format(game_id=item_id),
            "executable": self.source.make_executable(app_id=artifact_id),
        }
        if item:
            developer = item.get("developer")
            if isinstance(developer, str) and developer.strip():
                values["developer"] = developer.strip()

        return (Game(values), _cover_data(item, images_dir))

    def __iter__(self):
        installations_path = self.source.locations.data["installations.jsonl"]
        data_root = self.source.locations.data["dir"]
        if installations_path is None or data_root is None:
            # Both are required, so this means a location that resolved
            # without them. Withhold the source rather than report nothing
            # and prune the library on top of it.
            raise SourceScanError(_ERROR_TITLE, _ERROR_SUBTITLE)

        installations = _load_installations(installations_path)
        catalog = _read_catalog(data_root)
        images_dir = self.source.locations.cache["images"]

        for entry in installations.values():
            try:
                result = self.game_from_installation(entry, catalog, images_dir)
            except (TypeError, ValueError) as error:
                logging.warning(
                    "Invalid Epic Games installation skipped", exc_info=error
                )
                continue
            if result is not None:
                yield result


class EpicLocations(NamedTuple):
    data: Location
    cache: Location


class EpicSource(ExecutableFormatSource):
    """The native Epic Games Launcher for Linux (EGLv2)."""

    source_id = "epic"
    name = _("Epic Games Launcher")
    available_on = {"linux"}
    iterable_class = EpicSourceIterable

    executable_format = f'xdg-open "{DEEP_LINK_FORMAT}"'

    locations: EpicLocations

    def __init__(self) -> None:
        super().__init__()
        self.locations = EpicLocations(
            Location(
                schema_key="epic-location",
                candidates=(
                    shared.data_dir / APP_DIRECTORY,
                    shared.host_data_dir / APP_DIRECTORY,
                    # Under Flatpak XDG_DATA_HOME is the app's own data
                    # folder, so the launcher lives one level deeper.
                    *(
                        shared.flatpak_dir / app_id / "data" / APP_DIRECTORY
                        for app_id in FLATPAK_IDS
                    ),
                ),
                # The "." subpath keeps a folder picked in the preferences
                # that was since deleted from resolving: an unresolvable
                # location withholds the source, while a resolved empty one
                # would prune it.
                paths={
                    "dir": LocationSubPath(".", is_directory=True),
                    "installations.jsonl": LocationSubPath(INSTALLATIONS_FILE),
                },
                invalid_subtitle=Location.DATA_INVALID_SUBTITLE,
            ),
            Location(
                schema_key="epic-cache-location",
                candidates=(
                    shared.cache_dir / APP_DIRECTORY,
                    shared.host_cache_dir / APP_DIRECTORY,
                    *(
                        shared.flatpak_dir / app_id / "cache" / APP_DIRECTORY
                        for app_id in FLATPAK_IDS
                    ),
                ),
                paths={
                    "images": LocationSubPath(IMAGES_DIRECTORY, is_directory=True)
                },
                invalid_subtitle=Location.CACHE_INVALID_SUBTITLE,
                # Covers are an enrichment: without the cache the games still
                # import and fall back to the cover URL.
                optional=True,
            ),
        )
