# rom_source.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Source of games found as ROM files in user folders.

ROMs are avulsos game files (no launcher, no store) that the user keeps in
folders of their choice. The source scans those folders recursively and
creates one game per recognised ROM file. The file hash is used as the
canonical identity so the same ROM imported from two folders is grouped
(Taiga F1/F2).

Extensions are kept intentionally small: anything the user drops in the
configured folders that looks like a game file is a candidate.
"""

import logging
from pathlib import Path
from typing import NamedTuple

from cartridges import shared
from cartridges.game import Game
from cartridges.importer.location import Location, LocationSubPath
from cartridges.importer.source import ExecutableFormatSource, SourceIterable
from cartridges.utils.file_hash import sha256_of_file

# Extensões de ROM reconhecidas. Não é exaustiva: o utilizador pode sempre
# adicionar um atalho manual para o que faltar.
ROM_EXTENSIONS = (
    ".iso",
    ".wad",
    ".zip",
    ".nsp",
    ".xci",
    ".nsx",
    ".pbp",
    ".cue",
    ".ccd",
    ".md",
    ".gen",
    ".smd",
    ".gb",
    ".gbc",
    ".gba",
    ".nds",
    ".3ds",
    ".cia",
)


def _is_rom(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in ROM_EXTENSIONS


class RomSourceIterable(SourceIterable):
    source: "RomSource"

    def __iter__(self):
        roots = self.source.locations.data["roots"]
        if not roots:
            return

        seen: set[str] = set()
        for root in roots:
            root_path = Path(root)
            if not root_path.is_dir():
                continue
            for path in root_path.rglob("*"):
                if not _is_rom(path):
                    continue
                file_hash = sha256_of_file(path)
                game_id = f"rom_{file_hash or path.stem}"
                if game_id in seen:
                    continue
                seen.add(game_id)
                values = {
                    "source": self.source.source_id,
                    "added": shared.import_time,
                    "name": path.stem,
                    "game_id": game_id,
                    "executable": str(path),
                    "file_hash": file_hash,
                    "launch_working_directory": str(path.parent),
                }
                yield Game(values), {}


class RomLocations(NamedTuple):
    data: Location


class RomSource(ExecutableFormatSource):
    """Games found as ROM files in user folders."""

    source_id = "rom"
    name = _("ROMs")
    executable_format = "{}"
    iterable_class = RomSourceIterable
    available_on = {"linux"}

    locations: RomLocations

    def __init__(self) -> None:
        super().__init__()
        self.locations = RomLocations(
            Location(
                schema_key="rom-location",
                candidates=(
                    shared.home / "ROMs",
                    shared.home / "Games",
                    shared.home / ".local" / "share" / "jolven" / "roms",
                ),
                paths={
                    "roots": LocationSubPath(".", is_directory=True),
                },
                invalid_subtitle=Location.DATA_INVALID_SUBTITLE,
            ),
        )
