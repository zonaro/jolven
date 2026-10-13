# constants.py
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Shared constants for the Jolven Steam-skin integration (backend only).
#
# The values mirror the upstream Adwaita-for-Steam installer contract
# (tag 4.4) so the patching mechanics stay faithful and interoperable:
# a patch is only recognised as "ours" when its first line is exactly
# ``PATCH_HEADER``.

from __future__ import annotations

from pathlib import Path

# ── Patch contract ───────────────────────────────────────────────────────

#: Patch key -> CSS file name inside ``<steam>/steamui/css/``.
#: ``base`` = Login/Splash/dialogs/Big Picture, ``main`` = most desktop
#: windows, ``notes`` = notes overlay. Mirrors upstream ``ADW_PATCH_FILES``.
PATCH_FILES: dict[str, str] = {
    "base": "library.css",
    "main": "gamerecording.css",
    "notes": "gamenotes.css",
}

#: Files that must exist for a directory to be a usable Steam interface.
#: ``gamenotes.css`` is absent from a few Steam builds, so it is optional:
#: the installer simply skips a missing patch file.
REQUIRED_PATCH_FILES: tuple[str, ...] = ("library.css", "gamerecording.css")

#: First line written by this integration. Read back to detect our patch.
PATCH_HEADER = "/* Adwaita-for-Steam */"

#: Legacy Adwaita-for-Steam v3 marker, still recognised (needs an update).
PATCH_HEADER_V3 = "/*patched*/"

PATCH_VERSION_PREFIX = "/* Version: "
PATCH_INSTALLED_PREFIX = "/* Installed at: "
PATCH_COMMENT_SUFFIX = " */"

#: Suffix used for the pristine Steam file kept next to each patch.
BACKUP_SUFFIX = ".original.css"

# ── Skin layout ──────────────────────────────────────────────────────────

#: Directory copied into ``<steam>/steamui/`` (matches upstream ``ADW_ROOT``).
SKIN_DIR_NAME = "adwaita"

#: Generated skin configuration file (imports colortheme/accent/scheme).
CONFIG_CSS_NAME = "config.css"

STEAMUI_DIR = "steamui"
CSS_DIR = "css"

#: Entry stylesheets bundled into ``<entry>.min.css`` and referenced by the
#: patched Steam files. One per patch key.
ENTRY_CSS_NAMES: dict[str, str] = {key: f"{key}.css" for key in PATCH_FILES}

#: Palette file location inside the skin tree (upstream keeps it here).
PALETTE_RELATIVE = Path(CSS_DIR) / "_colors" / "palette.css"

# ── Colours ──────────────────────────────────────────────────────────────

#: Named accent colours understood by upstream (map to ``--adw-accent-*``).
NAMED_ACCENTS: tuple[str, ...] = (
    "blue",
    "teal",
    "green",
    "yellow",
    "orange",
    "red",
    "pink",
    "purple",
    "slate",
)

#: The palette slug whose colortheme file is the implicit default; upstream
#: does not emit an import for it.
DEFAULT_COLORTHEME = "adwaita"

#: Value used when ``VERSION`` cannot be read from the vendor tree.
_ADW_VERSION_FALLBACK = "4.4"

# ── Behaviour knobs ──────────────────────────────────────────────────────

#: Milliseconds to coalesce rapid profile changes in ``SteamSkinManager``.
DEBOUNCE_MS = 300
