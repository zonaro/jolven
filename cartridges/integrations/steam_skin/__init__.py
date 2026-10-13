# Steam skin integration (backend)
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Applies the Adwaita-for-Steam palette (vendored under
# ``data/vendor/adwaita-for-steam``) to a Steam installation by patching
# ``steamui/css`` and dropping the skin into ``steamui/adwaita``.
#
# Public surface:
#
# * :func:`detector.detect_all` — find native/Flatpak/Snap/custom Steam runs.
# * :func:`installer.instalar` / :func:`installer.restaurar` — apply/remove.
# * :func:`recovery.verificar_estado` — :class:`recovery.Estado` health check.
# * :class:`manager.SteamSkinManager` — GSettings-bound coordinator for the UI.

from cartridges.integrations.steam_skin.constants import (
    PATCH_FILES,
    PATCH_HEADER,
    SKIN_DIR_NAME,
)
from cartridges.integrations.steam_skin.detector import (
    Installation,
    detect_all,
    detect_custom,
    detect_flatpak,
    detect_native,
    detect_snap,
    expand_steam_path,
    find_installation,
    is_steam_path_valid,
)
from cartridges.integrations.steam_skin.installer import (
    SkinError,
    esta_instalada,
    instalar,
    restaurar,
    totalmente_instalada,
)
from cartridges.integrations.steam_skin.recovery import (
    Estado,
    precisa_reparo,
    reparar_se_seguro,
    texto_do_estado,
    verificar_estado,
)

__all__ = [
    "Estado",
    "Installation",
    "PATCH_FILES",
    "PATCH_HEADER",
    "SKIN_DIR_NAME",
    "SkinError",
    "detect_all",
    "detect_custom",
    "detect_flatpak",
    "detect_native",
    "detect_snap",
    "esta_instalada",
    "expand_steam_path",
    "find_installation",
    "instalar",
    "is_steam_path_valid",
    "precisa_reparo",
    "reparar_se_seguro",
    "restaurar",
    "texto_do_estado",
    "totalmente_instalada",
    "verificar_estado",
]
