# vendor.py
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Locates and reads the reduced Adwaita-for-Steam vendor tree that ships
# with Jolven (``data/vendor/adwaita-for-steam``).  No network, no GResource:
# the vendor is plain files on disk, so it can be inspected and updated by
# hand (see ``UPSTREAM.md`` in that directory).

from __future__ import annotations

import logging
import os
from pathlib import Path

from cartridges.integrations.steam_skin.constants import _ADW_VERSION_FALLBACK

#: Environment override, mostly useful for tests and packagers.
VENDOR_ENV = "JOLVEN_STEAM_SKIN_VENDOR"

_VENDOR_DIR_NAME = "adwaita-for-steam"


def _candidate_roots() -> list[Path]:
    """Every plausible location of the vendor tree, most specific first."""
    candidates: list[Path] = []

    override = os.environ.get(VENDOR_ENV)
    if override:
        candidates.append(Path(override).expanduser())

    # Source tree: <repo>/cartridges/integrations/steam_skin/vendor.py
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "data" / "vendor" / _VENDOR_DIR_NAME
        if candidate not in candidates:
            candidates.append(candidate)

    # Installed layouts: <prefix>/share/jolven/vendor/adwaita-for-steam and
    # share/.../data/vendor/adwaita-for-steam.
    for parent in here.parents:
        candidates.append(parent / "share" / "jolven" / "vendor" / _VENDOR_DIR_NAME)
        candidates.append(parent / "share" / "jolven" / "data" / "vendor" / _VENDOR_DIR_NAME)

    return candidates


def vendor_root() -> Path:
    """Return the vendor directory, preferring one that actually exists.

    Falls back to the source-tree path so error messages stay meaningful
    even when the vendor is missing.
    """
    candidates = _candidate_roots()
    for candidate in candidates:
        if (candidate / "colorthemes").is_dir() and (candidate / "palette.css").is_file():
            return candidate
    # Nothing complete found: return the source-tree candidate.
    return candidates[0] if candidates else Path(_VENDOR_DIR_NAME)


def vendor_available() -> bool:
    """``True`` when the vendor tree can actually be used."""
    root = vendor_root()
    return (root / "palette.css").is_file() and (root / "colorthemes").is_dir()


def palette_path() -> Path:
    """Path to the vendored ``palette.css``."""
    return vendor_root() / "palette.css"


def colorthemes_dir() -> Path:
    """Directory holding ``<slug>/<slug>.css`` for every colortheme."""
    return vendor_root() / "colorthemes"


def colortheme_path(slug: str) -> Path:
    """Path to the vendored stylesheet for *slug* (may not exist)."""
    return colorthemes_dir() / slug / f"{slug}.css"


def extras_dir() -> Path:
    """Directory holding the vendored ``extras/**/*.css`` option files."""
    return vendor_root() / "extras"


def windowcontrols_dir() -> Path:
    """Directory holding the vendored ``windowcontrols/*.css`` files."""
    return vendor_root() / "windowcontrols"


def fonts_dir() -> Path:
    """Directory holding the vendored ``fonts/<name>/<name>.css`` files."""
    return vendor_root() / "fonts"


def list_fonts() -> list[str]:
    """Sorted list of vendored font names (directories with ``<name>.css``)."""
    directory = fonts_dir()
    if not directory.is_dir():
        return []
    return sorted(
        entry.name
        for entry in directory.iterdir()
        if entry.is_dir() and (entry / f"{entry.name}.css").is_file()
    )


def list_colorthemes() -> list[str]:
    """Sorted list of vendored colortheme slugs."""
    directory = colorthemes_dir()
    if not directory.is_dir():
        return []
    slugs = []
    for entry in directory.iterdir():
        if entry.is_dir() and (entry / f"{entry.name}.css").is_file():
            slugs.append(entry.name)
    return sorted(slugs)


def vendor_version() -> str:
    """Upstream version recorded in the vendor tree, or the compiled default."""
    version_file = vendor_root() / "VERSION"
    try:
        version = version_file.read_text(encoding="utf-8").strip()
    except OSError as error:
        logging.debug("Could not read vendor VERSION: %s", error)
        return _ADW_VERSION_FALLBACK
    return version or _ADW_VERSION_FALLBACK
