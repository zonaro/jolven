# uzdoom_source.py
#
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2026 Geoffrey Coulaud

"""UZDoom source: lists the base games (IWADs) of a user-picked folder.

UZDoom is a source port for the Doom engine. Its content is made of WAD
files: an IWAD holds a base game (Doom, Doom II, ...) and a PWAD holds a
mod that needs another IWAD to run. Only the IWADs are listed as games.
"""

from pathlib import Path
from shlex import quote as shell_quote
from shutil import which
from typing import Callable, Generator, NamedTuple, Optional

from cartridges import shared
from cartridges.game import Game
from cartridges.importer.location import Location, LocationSubPath
from cartridges.importer.source import (
    ExecutableFormatSource,
    SourceIterable,
    SourceIterationResult,
)
from cartridges.launchers import flatpak_installed


UZDOOM_BINARY = "uzdoom"
UZDOOM_FLATPAK_ID = "org.zdoom.UZDoom"

# Magic headers written at the beginning of a WAD file.
IWAD_MAGIC = b"IWAD"
PWAD_MAGIC = b"PWAD"


def resolve_uzdoom_base(
    *,
    find_program: Callable[[str], str | None] = which,
    has_flatpak: Callable[[str], bool] = flatpak_installed,
) -> str:
    """Return the base command used to launch UZDoom.

    The native binary is preferred; the Flatpak is used when the binary is
    not installed. When neither is found the native form is kept as a best
    effort, like the TwinTail launcher does.

    The lookup is injectable so the tests never spawn a subprocess.
    """
    if find_program(UZDOOM_BINARY):
        return UZDOOM_BINARY
    if has_flatpak(UZDOOM_FLATPAK_ID):
        return f"flatpak run {UZDOOM_FLATPAK_ID}"
    return UZDOOM_BINARY


class UzdoomSourceIterable(SourceIterable):
    source: "UzdoomSource"

    extensions = (".wad",)

    def iter_wad_files(self, root: Path) -> Generator[Path, None, None]:
        """Yield the WAD files directly inside *root*, without recursion."""

        try:
            for path in root.iterdir():
                if not path.is_file():
                    continue
                if path.suffix.lower() not in self.extensions:
                    continue
                yield path
        except OSError:
            return

    @staticmethod
    def read_magic(path: Path) -> Optional[bytes]:
        """Read the magic header of a WAD file, if it can be read."""

        try:
            with path.open("rb") as wad_file:
                return wad_file.read(4)
        except OSError:
            return None

    def __iter__(self) -> Generator[SourceIterationResult, None, None]:
        """Generator method producing games"""

        root = self.source.locations.data["dir"]
        if root is None:
            return

        for path in self.iter_wad_files(root):
            magic = self.read_magic(path)
            if magic == PWAD_MAGIC:
                # A PWAD is a mod: it needs another IWAD to run, so it is
                # never listed as a game.
                continue
            if magic != IWAD_MAGIC:
                # Not a WAD file, or a truncated one.
                continue

            values = {
                "added": shared.import_time,
                "source": self.source.source_id,
                "name": path.stem,
                "game_id": self.source.game_id_format.format(game_id=path.stem),
                "executable": self.source.make_executable(iwad_path=path),
            }
            game = Game(values)
            additional_data = {}
            yield game, additional_data


class UzdoomLocations(NamedTuple):
    data: Location


class UzdoomSource(ExecutableFormatSource):
    source_id = "uzdoom"
    name = _("UZDoom")
    available_on = {"linux"}
    iterable_class = UzdoomSourceIterable

    locations: UzdoomLocations

    def __init__(
        self,
        *,
        find_program: Callable[[str], str | None] = which,
        has_flatpak: Callable[[str], bool] = flatpak_installed,
    ) -> None:
        super().__init__()
        self.locations = UzdoomLocations(
            Location(
                schema_key="uzdoom-location",
                # No auto-discovery: the folder is picked by the user, so
                # there is no candidate to try. A blank schema makes the
                # location unresolvable, and the importer then skips the
                # source instead of pruning its games.
                candidates=[],
                # The "." subpath makes the picked folder the only valid
                # root: a configured folder that was deleted raises
                # UnresolvableLocationError instead of scanning nothing and
                # pruning the games of the source.
                paths={"dir": LocationSubPath(".", is_directory=True)},
                invalid_subtitle=Location.DATA_INVALID_SUBTITLE,
            )
        )
        self._find_program = find_program
        self._has_flatpak = has_flatpak
        self._executable_base: Optional[str] = None

    @property
    def executable_base(self) -> str:
        """The UZDoom base command, resolved once per source instance.

        The import iterates over many games, so the detection (which may
        run ``flatpak info``) must not be repeated for each one of them.
        """

        if self._executable_base is None:
            self._executable_base = resolve_uzdoom_base(
                find_program=self._find_program,
                has_flatpak=self._has_flatpak,
            )
        return self._executable_base

    @property
    def executable_format(self) -> str:
        return f"{self.executable_base} -iwad {{iwad_path}}"

    def make_executable(self, iwad_path: Path) -> str:
        return self.executable_format.format(iwad_path=shell_quote(str(iwad_path)))
