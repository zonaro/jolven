# detector.py
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Steam installation detector — finds valid Steam runs (native, Flatpak,
# Snap, custom) whose ``steamui/css`` can carry the Adwaita-for-Steam skin.
#
# Design notes
# ------------
# * Paths are resolved with :mod:`pathlib` / ``expanduser`` so they work
#   regardless of the user's home location.
# * Validation is lightweight: only that the expected ``steamui/css``
#   directory and patch files exist, plus a readability probe. Steam is
#   never started or queried.
# * :func:`expand_steam_path` and :func:`is_steam_path_valid` used to be
#   imported from ``cartridges.utils.steam``; that module only holds the
#   metadata/API helpers, so the two small helpers live here instead.
# * Multiple installations are returned; the caller picks one.
# * When the sandbox or permissions block a candidate, it is returned with
#   ``accessible=False`` and a human-readable ``reason`` instead of being
#   silently dropped.

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, NamedTuple, Optional

from cartridges.integrations.steam_skin.constants import (
    CSS_DIR,
    REQUIRED_PATCH_FILES,
    STEAMUI_DIR,
)

# ── Result type ──────────────────────────────────────────────────────────


class Installation(NamedTuple):
    """A detected Steam installation the skin manager can target.

    Attributes
    ----------
    path:
        Absolute path to the Steam root (where ``steamui/css`` lives).
    kind:
        One of ``"native"``, ``"flatpak"``, ``"snap"``, ``"custom"``.
    accessible:
        ``True`` when the directory was inspected successfully. ``False``
        when the sandbox or permissions prevented it — ``reason`` then
        explains why.
    reason:
        Human-readable explanation when ``accessible`` is ``False``.
    """

    path: Path
    kind: str
    accessible: bool
    reason: Optional[str]


# ── Path helpers (local replacements for the discarded imports) ──────────


def expand_steam_path(value: "str | Path") -> Path:
    """Expand ``~`` and return an absolute :class:`pathlib.Path`.

    Kept intentionally small: detection must never fail because of a
    malformed environment variable.
    """
    return Path(str(value)).expanduser()


def is_steam_path_valid(path: "str | Path") -> bool:
    """Return ``True`` when *path* looks like a patchable Steam interface.

    Requires ``steamui/css`` plus the files the integration knows how to
    patch (``library.css`` and ``gamerecording.css``; ``gamenotes.css`` is
    optional because a few Steam builds omit it).
    """
    css_dir = expand_steam_path(path) / STEAMUI_DIR / CSS_DIR
    if not css_dir.is_dir():
        return False
    return all((css_dir / name).is_file() for name in REQUIRED_PATCH_FILES)


# ── Sandbox awareness ────────────────────────────────────────────────────

#: Flatpak application id of the Steam flatpak.
FLATPAK_STEAM_ID = "com.valvesoftware.Steam"

#: Paths used by the three common packaging methods.
NATIVE_SUBPATH = Path(".steam") / "steam"
FLATPAK_SUBPATH = (
    Path(".var") / "app" / FLATPAK_STEAM_ID / ".steam" / "steam"
)
SNAP_SUBPATH = Path("snap") / "steam" / "common" / ".steam" / "steam"


def in_flatpak() -> bool:
    """``True`` when Jolven itself runs inside a Flatpak sandbox."""
    return bool(os.environ.get("FLATPAK_ID")) or Path("/.flatpak-info").is_file()


def _permission_reason(path: Path) -> Optional[str]:
    """Return a reason string when *path*'s CSS dir cannot be read."""
    css_dir = path / STEAMUI_DIR / CSS_DIR
    try:
        os.listdir(css_dir)
    except PermissionError:
        return "permission denied reading steamui/css"
    except OSError as error:
        return f"cannot read steamui/css: {error}"
    return None


def _probe(path: Path, kind: str) -> Installation:
    """Inspect a single candidate and describe it as an :class:`Installation`."""
    try:
        if not path.is_dir():
            return Installation(path, kind, False, "directory not found")
    except OSError as error:
        return Installation(path, kind, False, f"cannot stat directory: {error}")

    if not is_steam_path_valid(path):
        return Installation(path, kind, False, "not a valid Steam interface directory")

    reason = _permission_reason(path)
    if reason is not None:
        return Installation(path, kind, False, reason)

    return Installation(path, kind, True, None)


# ── GSettings ────────────────────────────────────────────────────────────

_SCHEMA_ID = "io.github.zonaro.Jolven"
_CUSTOM_PATH_KEY = "steam-install-path"


def _settings_custom_path() -> Optional[Path]:
    """Read the custom install path from GSettings, if set and non-empty."""
    try:
        from gi.repository import Gio  # local import: keep detector GI-free

        settings = Gio.Settings.new(_SCHEMA_ID)
        # A stale compiled schema makes get_string() abort the process, so
        # only read the key when the schema actually declares it.
        if _CUSTOM_PATH_KEY not in settings.list_keys():
            logging.debug("Schema %s has no %s key yet", _SCHEMA_ID, _CUSTOM_PATH_KEY)
            return None
        raw = settings.get_string(_CUSTOM_PATH_KEY).strip()
    except Exception as error:  # pylint: disable=broad-exception-caught
        logging.debug("Could not read %s from GSettings: %s", _CUSTOM_PATH_KEY, error)
        return None
    if not raw:
        return None
    return expand_steam_path(raw)


# ── Detectors ────────────────────────────────────────────────────────────


def detect_native() -> List[Installation]:
    """Detect a native Linux Steam installation at ``~/.steam/steam``."""
    path = Path.home() / NATIVE_SUBPATH
    installation = _probe(path, "native")
    return [installation] if installation.accessible or installation.path.is_dir() else []


def detect_flatpak() -> List[Installation]:
    """Detect a Flatpak Steam installation.

    Under Jolven-in-Flatpak, writing into another flatpak's ``~/.var/app``
    tree is normally blocked (the manifest mounts it read-only), so the
    installation is reported with ``accessible=False`` and a reason the UI
    can surface — never silently ignored.
    """
    path = Path.home() / FLATPAK_SUBPATH
    installation = _probe(path, "flatpak")
    if installation.accessible and in_flatpak():
        # Reading works, but the common manifest mounts this path read-only.
        # Report it as reachable-but-not-writable so the UI can explain it.
        return [
            Installation(
                path,
                "flatpak",
                False,
                "running in Flatpak: another flatpak's ~/.var/app is mounted read-only",
            )
        ]
    return [installation] if installation.accessible or installation.path.is_dir() else []


def detect_snap() -> List[Installation]:
    """Detect a Snap Steam installation at ``~/snap/steam/common/.steam/steam``."""
    path = Path.home() / SNAP_SUBPATH
    installation = _probe(path, "snap")
    return [installation] if installation.accessible or installation.path.is_dir() else []


def detect_custom(path_str: "str | Path") -> List[Installation]:
    """Validate a user-supplied Steam path as a ``custom`` installation."""
    path = expand_steam_path(path_str)
    return [_probe(path, "custom")]


def detect_all(include_custom: bool = True) -> List[Installation]:
    """Run every detector and return each finding once, order preserved.

    Multiple installations are allowed (e.g. native *and* Flatpak). Custom
    paths from GSettings are appended last. Invalid/absent candidates are
    dropped; only candidates that exist but are blocked are kept with
    ``accessible=False``.
    """
    found: List[Installation] = []
    found.extend(detect_native())
    found.extend(detect_flatpak())
    found.extend(detect_snap())

    if include_custom:
        custom = _settings_custom_path()
        if custom is not None:
            found.extend(detect_custom(custom))

    seen: set[Path] = set()
    deduped: List[Installation] = []
    for installation in found:
        key = installation.path
        if key in seen:
            continue
        seen.add(key)
        deduped.append(installation)

    logging.info("Detected %d Steam installation candidate(s)", len(deduped))
    return deduped


def find_installation(path: "str | Path") -> Installation:
    """Describe a single path without guessing its packaging kind.

    Used by the manager when an explicit ``steam-install-path`` is set: the
    caller already knows the path, so only validity is in question.
    """
    return _probe(expand_steam_path(path), "custom")
