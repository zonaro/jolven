# quiver_source.py
#
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2026 Geoffrey Coulaud

"""Importer for the library of the Quiver Launcher.

Quiver Launcher (https://github.com/tgeorgiadis/quiver-launcher, MIT) keeps
its library in ``apps.json`` inside its user data root and installs the apps
in ``Apps/<folderName>`` under the same root, unless ``settings.json``
points somewhere else through its ``AppsPath`` key.

Only local files are read here: the library file, the settings file and the
folders of the installed apps. Nothing is written, no network call is made
and no credential is touched.
"""

import json
import logging
import os
import re
import shlex
from pathlib import Path
from typing import Any, Generator, NamedTuple, Optional
from urllib.parse import urlparse

from cartridges import shared
from cartridges.game import Game
from cartridges.importer.location import (
    Location,
    LocationSubPath,
    UnresolvableLocationError,
)
from cartridges.importer.source import (
    Source,
    SourceIterable,
    SourceIterationResult,
    SourceScanError,
)
from cartridges.utils.quiver_catalog import QuiverEnrichment, enrich_entry

#: Name of the library file inside the data root of the launcher.
LIBRARY_FILE_NAME = "apps.json"

#: Name of the settings file inside the data root of the launcher.
SETTINGS_FILE_NAME = "settings.json"

#: Name of the data root of the launcher.
DATA_ROOT_NAME = "QuiverLauncher"

#: Folder of the data root where the apps are installed by default.
DEFAULT_INSTALL_DIR_NAME = "Apps"

#: File the launcher writes in an app folder with the chosen executable.
SELECTED_EXECUTABLE_FILE_NAME = "selected_executable.txt"

#: File the launcher writes in an app folder with the installed version.
VERSION_FILE_NAME = "version.txt"

#: Flatpak application id of the launcher.
FLATPAK_APP_ID = "io.github.tgeorgiadis.QuiverLauncher"

#: Sections of the old library format, still read by the launcher.
LEGACY_SECTIONS = ("standard", "experimental", "custom")

#: Files the launcher writes next to the game files. They are never the
#: program to launch, so the scan of an app folder ignores them.
LAUNCHER_METADATA_FILES = frozenset(
    {
        "version.txt",
        "install-incomplete.txt",
        "lastplayed.txt",
        "installed-build.txt",
        "selected_executable.txt",
        "flatpak-install.json",
        "flatpak-install.pending.json",
    }
)

#: Suffixes of the programs the launcher downloads (AppImages and raw
#: binaries). They are the launch targets even without the executable bit.
LAUNCHER_SUFFIXES = (".appimage", ".x86_64", ".arm64", ".aarch64")

#: Suffix of a Windows program, which needs a runner (Wine or Proton).
WINDOWS_SUFFIX = ".exe"

#: Folders of a Wine or Proton prefix. They hold the Windows copy of the
#: game, not the native one, so the scan never descends into them.
COMPATIBILITY_DIRS = frozenset({".wine-prefix", ".steam-compat-data"})

#: Placeholders a custom launch command may use.
PLACEHOLDERS = ("{exe}", "{gamePath}", "{exeDir}")

#: A placeholder the expansion does not know about.
LEFTOVER_PLACEHOLDER_RE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")

#: Characters that cannot be part of a game id (the id names a file).
UNSAFE_ID_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")

#: Longest tag kept for a game. A tag is a label, not a sentence.
MAX_TAG_LENGTH = 40

#: Most tags kept for a game. The details view shows them in one line.
MAX_TAGS = 16


def sanitize_tags(value: Any) -> list[str]:
    """The tags of an entry, cleaned up.

    Only strings are kept, trimmed and cut to a sane length. The list is
    deduplicated ignoring the case and capped, so a broken library file
    cannot flood the details view of the game.
    """
    if not isinstance(value, (list, tuple)):
        return []
    tags: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        tag = item.strip()[:MAX_TAG_LENGTH].strip()
        if not tag:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        tags.append(tag)
        if len(tags) >= MAX_TAGS:
            break
    return tags


def sanitize_id_part(value: str) -> str:
    """Reduce a text to a stable fragment usable inside a game id."""
    return UNSAFE_ID_CHARS_RE.sub("-", value.strip()).strip("-._")


def sanitize_repository(value: str) -> str:
    """Reduce ``owner/repository`` to ``owner_repository``."""
    return UNSAFE_ID_CHARS_RE.sub("-", value.strip().replace("/", "_")).strip("-._")


def is_inside(path: Path, root: Path) -> bool:
    """Whether a path is inside a folder (or is the folder itself)."""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def is_launcher_metadata(path: Path) -> bool:
    """Whether a file is metadata written by the launcher."""
    return path.name.casefold() in LAUNCHER_METADATA_FILES


def is_launcher_name(path: Path) -> bool:
    """Whether the name of a file is the one of a downloaded program."""
    return path.name.casefold().endswith(LAUNCHER_SUFFIXES)


def is_windows_name(path: Path) -> bool:
    """Whether a file is a Windows program."""
    return path.name.casefold().endswith(WINDOWS_SUFFIX)


def has_executable_bit(path: Path) -> bool:
    """Whether a file carries the executable bit."""
    try:
        return os.access(path, os.X_OK)
    except OSError:
        return False


def looks_like_program(path: Path) -> bool:
    """Whether a file without the executable bit looks like a program.

    The launcher downloads AppImages and raw binaries, but a wrapper script
    is a program too. The magic number is the same check the launcher does.
    """
    try:
        with path.open("rb") as handle:
            header = handle.read(64)
    except OSError:
        return False
    if header.startswith(b"\x7fELF"):
        return True
    return header.startswith(b"#!")


def join_command(tokens: list[str]) -> str:
    """Join a command for the launcher of the Jolven.

    The Jolven runs the command through a shell, so every argument is
    quoted: a path with spaces must not become two arguments.
    """
    return " ".join(shlex.quote(token) for token in tokens)


def expand_custom_command(
    template: str, executable: Path, app_dir: Path
) -> Optional[list[str]]:
    """Expand the placeholders of a custom launch command.

    The command is split the way a shell would split it, so a path with
    spaces stays a single argument. ``None`` comes back when the command
    cannot be expanded safely: an unknown placeholder, an unmatched quote
    or a command that does not say what to run.
    """
    if not template:
        return None
    if not any(placeholder in template for placeholder in PLACEHOLDERS):
        # The command does not name the program to launch.
        return None
    try:
        tokens = shlex.split(template)
    except ValueError:
        logging.warning("Quiver custom launch command has an unmatched quote")
        return None
    if not tokens:
        return None
    resolved: list[str] = []
    for token in tokens:
        value = token.replace("{exe}", str(executable))
        value = value.replace("{gamePath}", str(app_dir))
        value = value.replace("{exeDir}", str(executable.parent))
        if LEFTOVER_PLACEHOLDER_RE.search(value):
            logging.warning(
                "Quiver custom launch command has an unknown placeholder: %s", template
            )
            return None
        resolved.append(value)
    return resolved


def has_catalog_identity(entry: dict[str, Any]) -> bool:
    """Whether an entry carries something the public catalog can answer for.

    The catalog resolves an app by its catalog id, by its repository or by
    its name. An entry with none of them is not worth a request.
    """
    for key in ("catalogEntryId", "repository", "name"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def safe_http_url(value: Any) -> Optional[str]:
    """An http/https address with a host, or nothing.

    The addresses come from the library file and from the public catalog,
    so both are untrusted: only http and https are taken, the other
    schemes are dropped.
    """
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https"):
        return None
    if not parsed.netloc:
        return None
    return url


def candidate_roots() -> list[Path]:
    """Roots where the launcher may keep its data.

    Resolved lazily: the launcher can be installed (and the XDG variable
    can change) after the preferences window was built.

    The portable mode of the launcher keeps the data beside the AppImage
    instead of the XDG folder. That path cannot be guessed, so it is the
    user who points the Jolven at it through the location chooser of the
    preferences.
    """
    roots: list[Path] = []
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        roots.append(Path(xdg_data_home) / DATA_ROOT_NAME)
    roots.append(shared.home / ".local" / "share" / DATA_ROOT_NAME)
    roots.append(shared.flatpak_dir / FLATPAK_APP_ID / "data" / DATA_ROOT_NAME)
    return roots


class QuiverSourceIterable(SourceIterable):
    """Games of the library of the Quiver Launcher."""

    source: "QuiverSource"

    def __init__(self, source: "QuiverSource") -> None:
        super().__init__(source)
        self._seen_game_ids: set[str] = set()
        self._install_root: Optional[Path] = None

    # Reading of the library file

    def read_library(self, path: Path) -> list[dict[str, Any]]:
        """Read the app entries of the library file.

        :raises SourceScanError: when the file cannot be read or parsed.
        """
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            # The launcher can be uninstalled between the resolution of the
            # location and this read. An absent library is an empty library.
            logging.debug("The Quiver library file %s is gone", path)
            return []
        except (OSError, UnicodeDecodeError) as error:
            raise SourceScanError(
                _("Could not read the Quiver library"),
                _(
                    "The Quiver library file could not be read. Check the "
                    "Quiver folder in the preferences and import again."
                ),
            ) from error

        try:
            document = json.loads(content)
        except json.JSONDecodeError as error:
            raise SourceScanError(
                _("Could not read the Quiver library"),
                _(
                    "The Quiver library file is not valid JSON. Quiver may be "
                    "writing it right now: close Quiver and import again."
                ),
            ) from error

        return list(self.iter_app_entries(document))

    def iter_app_entries(self, document: Any) -> Generator[dict[str, Any], None, None]:
        """Yield the usable app entries of a parsed library file.

        The library file has three accepted shapes: the modern ``apps``
        list, a bare list and the legacy ``standard``/``experimental``/
        ``custom`` sections. Anything else is not a library file at all.
        """
        if isinstance(document, list):
            arrays = [document]
        elif isinstance(document, dict):
            arrays = []
            for key in ("apps", *LEGACY_SECTIONS):
                if key not in document:
                    continue
                value = document[key]
                if not isinstance(value, list):
                    raise SourceScanError(
                        _("Could not read the Quiver library"),
                        _(
                            "The Quiver library file has an invalid section. "
                            "Fix the file in Quiver and import again."
                        ),
                    )
                arrays.append(value)
            if not arrays:
                raise SourceScanError(
                    _("Could not read the Quiver library"),
                    _(
                        "The Quiver library file has no app list. Fix the file "
                        "in Quiver and import again."
                    ),
                )
        else:
            raise SourceScanError(
                _("Could not read the Quiver library"),
                _(
                    "The Quiver library file has an unknown format. Fix the "
                    "file in Quiver and import again."
                ),
            )

        for array in arrays:
            for entry in array:
                if not isinstance(entry, dict):
                    logging.warning("Skipped an invalid Quiver library entry")
                    continue
                name = entry.get("name")
                if not isinstance(name, str) or not name.strip():
                    logging.warning(
                        "Skipped a Quiver library entry without a name"
                    )
                    continue
                yield entry

    # Identity of the apps

    def make_game_id(self, entry: dict[str, Any]) -> str:
        """Stable id of a library entry.

        The folder name is the identity the launcher itself uses: it is
        unique in the library. Entries without one fall back to the
        repository and then to the name, so the id of an app does not
        change between two scans.
        """
        folder_name = entry.get("folderName")
        if isinstance(folder_name, str) and folder_name.strip():
            fragment = sanitize_id_part(folder_name)
        else:
            repository = entry.get("repository")
            if isinstance(repository, str) and repository.strip():
                fragment = sanitize_repository(repository)
            else:
                fragment = sanitize_id_part(str(entry.get("name") or ""))
        if not fragment:
            fragment = "app"
        return self.source.game_id_format.format(game_id=fragment)

    # Folders of the installed apps

    def install_root(self) -> Path:
        """Folder where the launcher installs the apps."""
        if self._install_root is not None:
            return self._install_root
        settings_path = self.data_root / SETTINGS_FILE_NAME
        override = self.read_install_root(settings_path)
        if override is not None:
            self._install_root = override
        else:
            self._install_root = self.data_root / DEFAULT_INSTALL_DIR_NAME
        return self._install_root

    def read_install_root(self, settings_path: Path) -> Optional[Path]:
        """Apps folder set in ``settings.json``, when it is usable.

        Only an absolute path of an existing folder is taken: a relative
        path or a folder that is not there is ignored, and the default
        folder of the data root is used instead.
        """
        try:
            content = settings_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        try:
            document = json.loads(content)
        except json.JSONDecodeError:
            return None
        if not isinstance(document, dict):
            return None
        value = document.get("AppsPath")
        if not isinstance(value, str) or not value.strip():
            return None
        candidate = Path(value.strip()).expanduser()
        if not candidate.is_absolute():
            logging.debug("Ignoring the relative Quiver AppsPath %s", value)
            return None
        if not candidate.is_dir():
            logging.debug("Ignoring the missing Quiver AppsPath %s", candidate)
            return None
        return candidate

    def app_dir(self, entry: dict[str, Any]) -> Optional[Path]:
        """Folder of an app inside the install root.

        ``None`` when the entry says no folder at all: the install root
        itself is not the folder of an app.
        """
        install_path = entry.get("installPath")
        if isinstance(install_path, str) and install_path.strip():
            candidate = Path(install_path.strip()).expanduser()
            if candidate.is_absolute():
                return candidate
            logging.debug("Ignoring the relative Quiver installPath %s", install_path)
        folder_name = entry.get("folderName")
        if isinstance(folder_name, str) and folder_name.strip():
            return self.install_root() / folder_name.strip()
        return None

    def read_version(self, app_dir: Path) -> str:
        """Version the launcher recorded for an installed app."""
        version_path = app_dir / VERSION_FILE_NAME
        try:
            return version_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return ""

    # Executables

    def resolve_executable(self, app_dir: Path) -> tuple[Optional[Path], bool]:
        """Find the program to launch of an installed app.

        Returns the path of the program and whether it is a Windows one,
        which then needs a runner (Wine or Proton).
        """
        selected = self.read_selected_executable(app_dir)
        if selected is not None:
            return selected, is_windows_name(selected)

        native, windows = self.scan_candidates(app_dir)
        if len(native) == 1:
            return native[0], False
        if len(native) > 1:
            # Several programs of the same folder: the launcher would ask
            # the user, and the Jolven does not guess between them.
            logging.debug("Ambiguous Quiver programs in %s", app_dir)
            return None, False
        if len(windows) == 1:
            return windows[0], True
        if len(windows) > 1:
            logging.debug("Ambiguous Quiver Windows programs in %s", app_dir)
        return None, False

    def read_selected_executable(self, app_dir: Path) -> Optional[Path]:
        """Program the user chose in the launcher, when it is usable.

        The file holds the path of the program. It may be relative to the
        app folder; either way it has to stay inside it, so a tampered
        file cannot point the Jolven at another folder.
        """
        marker = app_dir / SELECTED_EXECUTABLE_FILE_NAME
        if not marker.is_file():
            return None
        try:
            raw = marker.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return None
        if not raw:
            return None
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = app_dir / candidate
        try:
            resolved = candidate.resolve()
            root = app_dir.resolve()
        except OSError:
            return None
        if not is_inside(resolved, root):
            logging.warning(
                "Quiver chose a program outside of the app folder: %s", raw
            )
            return None
        if not resolved.is_file():
            return None
        return resolved

    def scan_candidates(self, app_dir: Path) -> tuple[list[Path], list[Path]]:
        """Programs found in an app folder, native ones first.

        The top of the folder is scanned first; only when it holds no
        program at all the sub folders are looked at.
        """
        native, windows = self.top_level_candidates(app_dir)
        if native or windows:
            return native, windows
        return self.recursive_candidates(app_dir)

    def top_level_candidates(self, app_dir: Path) -> tuple[list[Path], list[Path]]:
        """Programs found at the top of an app folder."""
        try:
            entries = sorted(app_dir.iterdir())
        except OSError:
            return [], []
        files = [
            path
            for path in entries
            if path.is_file() and not is_launcher_metadata(path)
        ]
        windows = [path for path in files if is_windows_name(path)]
        others = [path for path in files if not is_windows_name(path)]

        native = [path for path in others if has_executable_bit(path)]
        if len(native) > 1:
            # Several programs at the top: the one named after the
            # platform wins, but two of them are still a guess.
            launchers = [path for path in native if is_launcher_name(path)]
            if len(launchers) == 1:
                return launchers, windows
            return native, windows
        if native:
            return native, windows

        launchers = [path for path in others if is_launcher_name(path)]
        if launchers:
            return launchers, windows

        if len(others) == 1 and looks_like_program(others[0]):
            return others, windows
        return [], windows

    def recursive_candidates(
        self, app_dir: Path, max_depth: int = 2
    ) -> tuple[list[Path], list[Path]]:
        """Programs found in the sub folders of an app folder.

        The walk stops after a couple of levels: a deep tree is a data
        folder of the game, not the program to launch.
        """
        native: list[Path] = []
        windows: list[Path] = []
        base_depth = len(app_dir.parts)
        try:
            for dir_path, dir_names, file_names in os.walk(app_dir):
                current = Path(dir_path)
                depth = len(current.parts) - base_depth
                if depth >= max_depth:
                    dir_names[:] = []
                dir_names[:] = [
                    name
                    for name in dir_names
                    if name.casefold() not in COMPATIBILITY_DIRS
                ]
                for name in file_names:
                    path = current / name
                    if is_launcher_metadata(path):
                        continue
                    if is_windows_name(path):
                        windows.append(path)
                    elif has_executable_bit(path) or is_launcher_name(path):
                        native.append(path)
        except OSError:
            return native, windows
        return native, windows

    # Commands

    def make_command(
        self,
        entry: dict[str, Any],
        app_dir: Path,
        executable: Optional[Path],
        needs_runner: bool,
    ) -> str:
        """Command that launches an app, empty when it cannot be built."""
        if executable is None:
            return ""
        if not needs_runner:
            return self.source.make_executable(executable)
        return self.make_runner_command(entry, app_dir, executable)

    def make_runner_command(
        self, entry: dict[str, Any], app_dir: Path, executable: Path
    ) -> str:
        """Command that runs a Windows program through Wine or Proton.

        The runner of the app wins over the custom command, the same way
        the launcher does it. When the app does not say which runner to
        use, the Jolven does not guess: the app is imported without a
        command and the user picks the program in the details of the game.
        """
        runner = str(entry.get("linuxRunner") or "").strip().casefold()
        custom = entry.get("linuxCustomLaunchCommand")
        custom_command = custom.strip() if isinstance(custom, str) else ""

        if runner == "wine":
            return join_command(["wine", str(executable)])

        if runner == "proton":
            proton_path = str(entry.get("linuxProtonPath") or "").strip()
            if not proton_path:
                logging.debug("The Quiver app %s has no Proton path", executable)
                return ""
            proton = Path(proton_path).expanduser()
            if not proton.is_file():
                logging.debug("The Proton path %s of Quiver is missing", proton)
                return ""
            return join_command([str(proton), "waitforexitandrun", str(executable)])

        if runner == "custom" or custom_command:
            tokens = expand_custom_command(custom_command, executable, app_dir)
            if tokens is None:
                return ""
            return join_command(tokens)

        # "auto" or an unknown runner: the launcher decides between Wine
        # and Proton, and the Jolven does not.
        logging.debug("The Quiver app %s has no usable runner", executable)
        return ""

    # Cover

    def cover_url(self, entry: dict[str, Any]) -> Optional[str]:
        """Icon of an app, when the launcher holds an usable address.

        The address comes from the library file, so it is untrusted: only
        http and https are taken, the other schemes are dropped.
        """
        for key in ("appIconUrl", "gameIconUrl"):
            if url := safe_http_url(entry.get(key)):
                return url
        return None

    # Enrichment of the public catalog

    def enrich(self, entry: dict[str, Any]) -> Optional[QuiverEnrichment]:
        """Ask the public catalog about an app, when the user wants it.

        The catalog is a network service and its answer is a bonus: it
        never fails an import. The lookup itself never raises, and the
        scan has to survive even if it does.
        """
        if not shared.schema.get_boolean("quiver-enrich"):
            return None
        if not has_catalog_identity(entry):
            return None
        try:
            return enrich_entry(entry)
        except Exception as error:  # pylint: disable=broad-exception-caught
            # Only the kind of the failure is logged: the entry holds the
            # name of the game and its repository, nothing secret.
            logging.debug(
                "The Quiver catalog failed for %s: %s",
                entry.get("name"),
                type(error).__name__,
            )
            return None

    # Games

    def build_game(
        self, entry: dict[str, Any]
    ) -> Optional[tuple[Game, dict[str, Any]]]:
        """Build the game of a library entry, when the entry is usable."""
        name = str(entry.get("name") or "").strip()
        if not name:
            return None

        game_id = self.make_game_id(entry)
        if game_id in self._seen_game_ids:
            logging.debug("Skipped the duplicate Quiver entry %s", game_id)
            return None
        self._seen_game_ids.add(game_id)

        enrichment = self.enrich(entry)

        app_dir = self.app_dir(entry)
        installed = app_dir is not None and app_dir.is_dir()

        command = ""
        version = ""
        if app_dir is not None and installed:
            executable, needs_runner = self.resolve_executable(app_dir)
            command = self.make_command(entry, app_dir, executable, needs_runner)
            version = self.read_version(app_dir)

        values = {
            "added": shared.import_time,
            "source": self.source.source_id,
            "name": name,
            "game_id": game_id,
            "executable": command,
            "installed": installed,
            # The launcher has no address to install an app from, so the
            # game is imported without a command to install it.
            "install_executable": "",
        }
        project = entry.get("project")
        if isinstance(project, str) and project.strip():
            values["developer"] = project.strip()
        tags = sanitize_tags(entry.get("tags"))
        if enrichment is not None:
            # The catalog only fills what the library does not say: the
            # local entry always wins over the remote one.
            description = enrichment.description
            if description and not values.get("description"):
                values["description"] = description
            developer = enrichment.developer
            if developer and not values.get("developer"):
                values["developer"] = developer
            if not tags:
                tags = sanitize_tags(enrichment.tags)
        if tags:
            values["tags"] = tags
        game = Game(values)

        additional_data: dict[str, Any] = {}
        cover = self.cover_url(entry)
        if enrichment is not None and enrichment.cover_url:
            catalog_cover = safe_http_url(enrichment.cover_url)
            if catalog_cover:
                cover = catalog_cover
        if cover:
            additional_data["online_cover_url"] = cover
        if version:
            # The game model has no field for the version of the install;
            # it travels with the other data of the import.
            additional_data["quiver_installed_version"] = version

        return (game, additional_data)

    @property
    def data_root(self) -> Path:
        """Root of the data of the launcher."""
        root = self.source.locations.data.root
        if root is None:
            raise UnresolvableLocationError
        return root

    def __iter__(self) -> Generator[SourceIterationResult, None, None]:
        """Generator method producing games"""
        location = self.source.locations.data
        try:
            location.resolve()
        except UnresolvableLocationError:
            # The launcher is not installed: there is nothing to import.
            return

        for entry in self.read_library(location[LIBRARY_FILE_NAME]):
            result = self.build_game(entry)
            if result is None:
                continue
            yield result


class QuiverLocations(NamedTuple):
    data: Location


class QuiverSource(Source):
    """Games of the library of the Quiver Launcher."""

    source_id = "quiver"
    name = _("Quiver")
    iterable_class = QuiverSourceIterable
    available_on = {"linux"}

    locations: QuiverLocations

    def __init__(self) -> None:
        super().__init__()
        self.locations = QuiverLocations(
            Location(
                schema_key="quiver-location",
                candidates=candidate_roots,
                paths={"apps.json": LocationSubPath(LIBRARY_FILE_NAME)},
                invalid_subtitle=Location.DATA_INVALID_SUBTITLE,
            )
        )

    def make_executable(self, path: Path) -> str:
        """Command that runs a native program."""
        return join_command([str(path)])
