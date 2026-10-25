# zdoom_archives.py
#
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2026 Geoffrey Coulaud

"""Detection of the ZDoom-family game archives.

The ZDoom family (UZDoom, GZDoom, ZDoom) stores its content in WAD files and
in zip archives:

- an ``.ipk3`` archive is an installed game: the engine only accepts it as
  the game (``uzdoom -iwad game.ipk3``) when the archive holds an ``IWADINFO``
  lump at its root, that is, an ``iwadinfo.txt`` file at the top level of the
  zip. Without that lump the engine refuses the file;
- a ``.pk3`` archive is a mod: it is loaded on top of an IWAD with the
  ``-file`` flag.

The name of the game is the ``Name`` entry of the ``IWad`` block of that
``IWADINFO`` file.

Only the central directory of the archive and that single small text file are
read: nothing is ever extracted, and every failure (missing file, file that
is not a zip, corrupt archive, denied permission, broken encoding) is
reported as "not a game archive" instead of raising.
"""

import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Optional

#: Magic header of a zip file, the format of every ZDoom archive.
ZIP_MAGIC = b"PK\x03\x04"

#: Name of the lump that tells the engine the archive holds a game. The lump
#: is the file of the root of the archive whose name without extension is
#: this one: the engine upper-cases it, so ``iwadinfo.txt`` is the
#: ``IWADINFO`` lump.
IWADINFO_LUMP = "iwadinfo"

#: Upper bound of the number of bytes read from the ``IWADINFO`` file. The
#: file is a few lines long, so anything bigger is not a sane one.
MAX_IWADINFO_BYTES = 64 * 1024

#: The ``IWad`` block of an ``IWADINFO`` file, with its body.
_IWAD_BLOCK_RE = re.compile(
    r"\bIWad\s*\{(?P<body>[^{}]*)\}", re.IGNORECASE
)

#: The ``Name`` entry of an ``IWad`` block.
_NAME_RE = re.compile(r'\bName\s*=\s*"(?P<value>[^"]*)"', re.IGNORECASE)


def _open_archive(path: Path) -> Optional[zipfile.ZipFile]:
    """Open *path* as a zip archive, or return None when it is not one.

    The magic header is checked first, so a file that is not a zip is
    rejected after four bytes are read.
    """

    try:
        with path.open("rb") as archive_file:
            magic = archive_file.read(len(ZIP_MAGIC))
    except (OSError, TypeError, ValueError):
        return None

    if magic != ZIP_MAGIC:
        return None

    try:
        return zipfile.ZipFile(path)
    except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile):
        return None


def _iwadinfo_entries(archive: zipfile.ZipFile) -> list[str]:
    """Return the names of the entries of *archive* that are the lump.

    Only the entries at the root of the archive are the lump: a file inside
    a subdirectory is not found by the engine.
    """

    try:
        entries = archive.infolist()
    except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile):
        return []

    return [
        entry.filename
        for entry in entries
        if "/" not in entry.filename
        and PurePosixPath(entry.filename).stem.lower() == IWADINFO_LUMP
    ]


def _read_entry(archive: zipfile.ZipFile, name: str) -> Optional[str]:
    """Read the text of the entry *name* of *archive*, or return None.

    The decoding is tolerant: a byte that is not valid UTF-8 is dropped
    instead of raising, because the file comes from the user's disk.
    """

    try:
        with archive.open(name) as member:
            data = member.read(MAX_IWADINFO_BYTES + 1)
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        NotImplementedError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
    ):
        return None

    return data[:MAX_IWADINFO_BYTES].decode("utf-8", errors="ignore")


def _parse_game_name(text: str) -> Optional[str]:
    """Return the ``Name`` of the ``IWad`` block of *text*, if there is one."""

    for block in _IWAD_BLOCK_RE.finditer(text):
        match = _NAME_RE.search(block.group("body"))
        if match is None:
            continue
        name = match.group("value").strip()
        if name:
            return name

    return None


def is_game_archive(path: Path) -> bool:
    """Tell whether *path* is an archive the engine accepts as a game.

    The archive must be a zip file whose central directory holds an
    ``IWADINFO`` lump at its root. Any problem is reported as False.
    """

    archive = _open_archive(path)
    if archive is None:
        return False

    try:
        return bool(_iwadinfo_entries(archive))
    finally:
        archive.close()


def read_game_name(path: Path) -> Optional[str]:
    """Return the name of the game held by the archive at *path*.

    The name is the ``Name`` entry of the ``IWad`` block of the ``IWADINFO``
    lump of the archive. None is returned when the archive is not a game
    archive, when it has no ``IWad`` block, or when that block has no usable
    name.
    """

    archive = _open_archive(path)
    if archive is None:
        return None

    try:
        for entry in _iwadinfo_entries(archive):
            text = _read_entry(archive, entry)
            if text is None:
                continue
            name = _parse_game_name(text)
            if name:
                return name
    finally:
        archive.close()

    return None
