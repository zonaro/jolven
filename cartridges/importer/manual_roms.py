# SPDX-License-Identifier: GPL-3.0-or-later
"""Safe, backend-independent manual ROM discovery for Jolven Desktop.

This module deliberately does not import GTK, alter the Store, install cores,
extract ZIP files or launch an emulator. It feeds a future explicit user-facing
preview/import flow, alongside the existing RetroArch playlist source.
"""

from __future__ import annotations

import os
import re
import shlex
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator

# Conservative candidates. Ambiguous disc images/archives are never guessed.
PLATFORM_EXTENSIONS: dict[str, frozenset[str]] = {
    "nes": frozenset({"nes", "fds"}),
    "snes": frozenset({"sfc", "smc", "fig"}),
    "gb": frozenset({"gb"}),
    "gbc": frozenset({"gbc"}),
    "gba": frozenset({"gba"}),
    "n64": frozenset({"n64", "z64", "v64"}),
    "nds": frozenset({"nds", "dsi"}),
    "3ds": frozenset({"3ds", "cci", "cxi"}),
    "gamecube": frozenset({"gcm", "gcz", "rvz", "iso"}),
    "wii": frozenset({"wbfs", "rvz", "iso"}),
    "megadrive": frozenset({"md", "smd", "gen"}),
    "mastersystem": frozenset({"sms"}),
    "gamegear": frozenset({"gg"}),
    "ps1": frozenset({"ccd", "pbp", "chd", "bin", "cue", "img", "iso"}),
    "ps2": frozenset({"chd", "bin", "cue", "iso"}),
    "psp": frozenset({"cso", "pbp", "iso"}),
    "saturn": frozenset({"chd", "bin", "cue", "iso"}),
    "dreamcast": frozenset({"gdi", "chd", "bin", "cue"}),
    "arcade": frozenset({"zip", "7z", "chd"}),
    "atari2600": frozenset({"a26"}),
    "atari7800": frozenset({"a78"}),
    "c64": frozenset({"d64", "t64", "prg"}),
}
AMBIGUOUS_EXTENSIONS = frozenset(
    {"zip", "7z", "rar", "iso", "bin", "cue", "chd", "pbp", "rvz"}
)


@dataclass(frozen=True)
class RomCandidate:
    path: Path
    platforms: tuple[str, ...]
    requires_choice: bool

    @property
    def is_unknown(self) -> bool:
        return not self.platforms


def detect_rom(path: str | os.PathLike[str]) -> RomCandidate:
    """Return candidates but do not auto-select ambiguous systems."""
    filename = Path(path)
    extension = filename.suffix.lower().lstrip(".")
    platforms = tuple(
        name
        for name, supported in PLATFORM_EXTENSIONS.items()
        if extension in supported
    )
    return RomCandidate(
        path=filename,
        platforms=platforms,
        requires_choice=extension in AMBIGUOUS_EXTENSIONS
        or len(platforms) != 1,
    )


def scan_rom_paths(
    roots: Iterable[Path],
    *,
    max_depth: int = 8,
    max_files: int = 5_000,
) -> Iterator[RomCandidate]:
    """Scan user-supplied roots without following symlinks or unbounded walks."""
    if max_depth < 0 or max_files <= 0:
        raise ValueError("Invalid scanning limits")
    stack = [(Path(root), 0) for root in roots]
    visited_directories: set[tuple[int, int]] = set()
    inspected = 0
    while stack and inspected < max_files:
        path, depth = stack.pop()
        try:
            if path.is_symlink():
                continue
            if path.is_file():
                inspected += 1
                result = detect_rom(path)
                if not result.is_unknown:
                    yield result
                continue
            if not path.is_dir() or depth > max_depth:
                continue
            info = path.stat(follow_symlinks=False)
            inode = info.st_dev, info.st_ino
            if inode in visited_directories:
                continue
            visited_directories.add(inode)
            if depth == max_depth:
                continue
            with os.scandir(path) as entries:
                children = [
                    Path(entry.path)
                    for entry in entries
                    if not entry.is_symlink()
                ]
            stack.extend((child, depth + 1) for child in reversed(children))
        except (OSError, PermissionError):
            continue


def inspect_rom_zip(
    archive: Path,
    *,
    max_entries: int = 2_000,
    max_uncompressed: int = 1024 * 1024 * 1024,
    max_ratio: float = 200.0,
) -> tuple[str, ...]:
    """List safe member names. Does not extract files or create directories."""
    if max_entries <= 0 or max_uncompressed <= 0 or max_ratio <= 0:
        raise ValueError("Invalid ZIP limits")
    names: list[str] = []
    total = 0
    try:
        with zipfile.ZipFile(archive) as zf:
            if len(zf.infolist()) > max_entries:
                raise ValueError("Too many ZIP entries")
            for member in zf.infolist():
                name = member.filename.replace("\\", "/")
                target = PurePosixPath(name)
                if (
                    not name
                    or name.startswith("/")
                    or re.match(r"^[A-Za-z]:", name)
                    or ".." in target.parts
                    or member.flag_bits & 0x1
                    or stat.S_IFMT(member.external_attr >> 16) == stat.S_IFLNK
                ):
                    raise ValueError("Unsafe ZIP member")
                if member.is_dir():
                    continue
                total += member.file_size
                if total > max_uncompressed:
                    raise ValueError("ZIP uncompressed data exceeds limit")
                if member.file_size > max(1, member.compress_size) * max_ratio:
                    raise ValueError("Potential ZIP decompression bomb")
                names.append(name)
    except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ValueError("Invalid ZIP archive") from exc
    return tuple(names)


def retroarch_launch_command(
    rom: Path, core: Path, *, flatpak: bool = False
) -> str:
    """Build a quoted command without shell interpolation or config mutation.

    The caller must explicitly choose a core path; detecting installed cores
    is the emulation setup assistant's responsibility.
    """
    if not rom.is_absolute() or not core.is_absolute():
        raise ValueError("Absolute ROM and core paths are required")
    command = (
        ["flatpak", "run", "org.libretro.RetroArch"] if flatpak
        else ["retroarch"]
    )
    return shlex.join([*command, "-L", str(core), str(rom)])
