# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only RetroArch installation diagnostics.

No RetroArch process control, no writes to its config, no downloads, no
assumptions about private Android paths. Call from a background UI worker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_MAX_CONFIG_BYTES = 1024 * 1024
_MAX_ENTRIES = 512
_CORE_SUFFIXES = (".so", ".dll", ".dylib")


@dataclass(frozen=True)
class RetroArchStatus:
    config_file: Path
    present: bool
    core_directory: Path | None
    cores: tuple[str, ...]
    system_directory: Path | None
    shader_directory: Path | None
    warnings: tuple[str, ...]


def parse_retroarch_config(content: str) -> dict[str, str]:
    """Parse simple RetroArch key=value settings without evaluating expressions.

    RetroArch supports comments/quoted strings. Only the paths needed for
    diagnostics are used. Malformed lines are ignored rather than executed.
    """
    result: dict[str, str] = {}
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        match = re.fullmatch(r"([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.*)", line)
        if not match:
            continue
        key, value = match.groups()
        value = value.strip()
        if value.startswith('"'):
            end = value.find('"', 1)
            if end < 0:
                continue
            value = value[1:end]
        else:
            value = value.split("#", 1)[0].strip()
        result[key.lower()] = value
    return result


def _resolve_config_path(raw: str | None, config_file: Path) -> Path | None:
    if not raw or raw in ("default", "DETECT"):
        return None
    if "\x00" in raw or len(raw) > 4096:
        return None
    # RetroArch's colon syntax is rooted at the config directory.
    if raw.startswith(":"):
        candidate = config_file.parent / raw[1:].lstrip("/")
    else:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = config_file.parent / candidate
    return candidate.resolve(strict=False)


def inspect_retroarch(
    config_file: Path,
    *,
    allow_outside_home: bool = False,
) -> RetroArchStatus:
    """Inspect an explicitly supplied RetroArch config path, read-only.

    The caller must choose the config path. To avoid arbitrary filesystem
    traversal on malformed configs, directories outside the config parent
    or the user's home are excluded unless explicitly opted in.
    """
    config_file = Path(config_file).expanduser().resolve(strict=False)
    if not config_file.is_file():
        return RetroArchStatus(config_file, False, None, (), None, None,
                               ("config_not_found",))
    if config_file.stat().st_size > _MAX_CONFIG_BYTES:
        return RetroArchStatus(config_file, True, None, (), None, None,
                               ("config_too_large",))
    try:
        data = parse_retroarch_config(config_file.read_text(
            encoding="utf-8", errors="replace"))
    except OSError:
        return RetroArchStatus(config_file, True, None, (), None, None,
                               ("config_not_readable",))

    home = Path.home().resolve(strict=False)
    base = config_file.parent
    warnings: list[str] = []

    def directory(option: str) -> Path | None:
        raw = data.get(option)
        candidate = _resolve_config_path(raw, config_file)
        if candidate is None:
            warnings.append(option + "_not_set")
            return None
        if not allow_outside_home and not (
            candidate == home or home in candidate.parents or
            candidate == base or base in candidate.parents
        ):
            warnings.append(option + "_outside_allowed_roots")
            return None
        if not candidate.is_dir():
            warnings.append(option + "_missing")
            return candidate
        if candidate.is_symlink():
            warnings.append(option + "_symlink")
            return None
        return candidate

    cores_path = directory("libretro_directory")
    system_path = directory("system_directory")
    shaders_path = directory("video_shader_dir")
    cores: list[str] = []

    if cores_path and cores_path.is_dir():
        try:
            for entry in sorted(cores_path.iterdir(), key=lambda x: x.name.casefold()):
                if len(cores) >= _MAX_ENTRIES:
                    warnings.append("cores_list_truncated")
                    break
                if entry.is_file() and not entry.is_symlink() and entry.name.endswith(_CORE_SUFFIXES):
                    cores.append(entry.name)
        except OSError:
            warnings.append("cores_unreadable")

    return RetroArchStatus(
        config_file, True, cores_path, tuple(cores),
        system_path, shaders_path, tuple(warnings)
    )
