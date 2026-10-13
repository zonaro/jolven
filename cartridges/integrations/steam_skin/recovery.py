# recovery.py
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Inspects the health of the installed Steam skin and repairs it only when it
# is provably safe.
#
# A Steam update replaces ``steamui/css`` and wipes our patch headers while
# leaving ``X.original.css`` behind.  Recovery must notice that and reapply
# the skin — but it must never:
# * overwrite a third-party patch (unknown header);
# * restore a stale backup over a newer Steam file;
# * touch anything while Steam is running (the changes would not be picked
#   up anyway, and a half-written file could break the running client).

from __future__ import annotations

import logging
import os
from enum import Enum
from pathlib import Path
from typing import Optional

from cartridges.integrations.steam_skin import installer, vendor
from cartridges.integrations.steam_skin.constants import (
    CONFIG_CSS_NAME,
    DEFAULT_COLORTHEME,
    PATCH_FILES,
    PATCH_HEADER,
    PATCH_HEADER_V3,
)
from cartridges.integrations.steam_skin.detector import (
    FLATPAK_SUBPATH,
    expand_steam_path,
    in_flatpak,
    is_steam_path_valid,
)

# ── State ────────────────────────────────────────────────────────────────


class Estado(Enum):
    """Health of the Steam skin for a given installation."""

    #: The path is not a valid Steam interface directory.
    NAO_ENCONTRADA = "nao_encontrada"
    #: Valid Steam, no skin applied.
    NAO_INSTALADA = "nao_instalada"
    #: Installed, current and consistent.
    SINCRONIZADA = "sincronizada"
    #: Partially applied, outdated version, or wiped by a Steam update.
    ATUALIZACAO_NECESSARIA = "atualizacao_necessaria"
    #: Applied, but the running Steam started before the change.
    AGUARDANDO_REINICIO = "aguardando_reinicio"
    #: Patched but the skin directory or a backup is missing.
    INCOMPATIVEL = "incompativel"
    #: Sandbox/permissions block writing to the Steam tree.
    PERMISSAO = "permissao"
    #: Another tool patched one of the CSS files (unknown header).
    CONFLITO_TERCEIROS = "conflito_terceiros"


#: First-line tokens that mark a foreign (non-Adwaita-for-Steam) patch.
_FOREIGN_TOKENS = (
    "patched",
    "millennium",
    "cssloader",
    "css loader",
    "stylus",
    "userstyle",
    "skin",
)


def _foreign_marker(first_line: str) -> bool:
    """``True`` when *first_line* is a recognisable third-party patch header."""
    if not first_line or first_line in (PATCH_HEADER, PATCH_HEADER_V3):
        return False
    if not (first_line.startswith("/*") and first_line.endswith("*/")):
        return False
    lowered = first_line.lower()
    return any(token in lowered for token in _FOREIGN_TOKENS)


def _has_foreign_header(steam: Path) -> bool:
    css_dir = installer.diretorio_css(steam)
    for css_name in PATCH_FILES.values():
        path = css_dir / css_name
        if path.is_file() and _foreign_marker(installer.primeira_linha(path)):
            return True
    return False


# ── Running-state helpers ────────────────────────────────────────────────

_STEAM_COMM_NAMES = ("steam", "steamwebhelper")


def _proc_steam_pids() -> list[int]:
    pids: list[int] = []
    try:
        entries = os.listdir("/proc")
    except OSError:
        return pids
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/comm", encoding="utf-8") as handle:
                comm = handle.read().strip()
        except OSError:
            continue
        if comm in _STEAM_COMM_NAMES:
            pids.append(int(entry))
    return pids


def steam_em_execucao() -> bool:
    """``True`` when a Steam process is running (best effort)."""
    try:
        from cartridges.utils.process_monitor import (  # local import
            is_flatpak_app_running,
            is_process_running,
        )

        if is_process_running("steam") or is_flatpak_app_running("com.valvesoftware.Steam"):
            return True
    except Exception as error:  # pylint: disable=broad-exception-caught
        logging.debug("process_monitor unavailable, falling back to /proc: %s", error)
    return bool(_proc_steam_pids())


def _steam_start_time() -> Optional[float]:
    """Earliest start time among running Steam processes, or ``None``."""
    earliest: Optional[float] = None
    for pid in _proc_steam_pids():
        try:
            started = os.stat(f"/proc/{pid}").st_mtime
        except OSError:
            continue
        earliest = started if earliest is None else min(earliest, started)
    return earliest


def _newest_install_mtime(steam: Path) -> Optional[float]:
    newest: Optional[float] = None
    paths: list[Path] = [installer.diretorio_css(steam) / name for name in PATCH_FILES.values()]
    skin = installer.diretorio_skin(steam)
    if skin.is_dir():
        paths.append(skin)
        for path in skin.rglob("*"):
            paths.append(path)
    for path in paths:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        newest = mtime if newest is None else max(newest, mtime)
    return newest


def _waiting_restart(steam: Path) -> bool:
    """``True`` when Steam is running but started before the last change."""
    started = _steam_start_time()
    if started is None:
        return False
    newest = _newest_install_mtime(steam)
    if newest is None:
        return False
    return newest > started


# ── Permissions ──────────────────────────────────────────────────────────


def _is_flatpak_steam_path(steam: Path) -> bool:
    try:
        return str(steam).startswith(str(Path.home() / FLATPAK_SUBPATH))
    except OSError:
        return False


def _pode_escrever(steam: Path) -> bool:
    """Best-effort writability check for the Steam CSS directory."""
    css_dir = installer.diretorio_css(steam)
    if not os.access(css_dir, os.W_OK):
        return False
    # Inside a Flatpak, os.access can lie: another flatpak's ~/.var/app is
    # normally mounted read-only even when it is listed as a filesystem.
    if in_flatpak() and _is_flatpak_steam_path(steam):
        return False
    return True


# ── Public API ───────────────────────────────────────────────────────────


def verificar_estado(steam_path: "str | Path") -> Estado:
    """Classify the skin health for *steam_path*."""
    steam = expand_steam_path(steam_path)
    try:
        if not steam.is_dir() or not is_steam_path_valid(steam):
            return Estado.NAO_ENCONTRADA
    except OSError:
        return Estado.NAO_ENCONTRADA

    css_dir = installer.diretorio_css(steam)
    existing = [name for name in PATCH_FILES.values() if (css_dir / name).is_file()]
    if not existing:
        return Estado.NAO_ENCONTRADA

    ours: list[str] = []
    foreign: list[str] = []
    for css_name in existing:
        first = installer.primeira_linha(css_dir / css_name)
        if first == PATCH_HEADER:
            ours.append(css_name)
        elif _foreign_marker(first):
            foreign.append(css_name)

    if not ours and not foreign:
        return Estado.NAO_INSTALADA
    if foreign:
        return Estado.CONFLITO_TERCEIROS

    if not _pode_escrever(steam):
        return Estado.PERMISSAO

    skin = installer.diretorio_skin(steam)
    if not skin.is_dir():
        return Estado.INCOMPATIVEL
    if not (skin / CONFIG_CSS_NAME).is_file():
        return Estado.ATUALIZACAO_NECESSARIA

    for css_name in ours:
        if not installer.caminho_backup(steam, css_name).is_file():
            return Estado.INCOMPATIVEL

    current_version = vendor.vendor_version()
    for css_name in ours:
        info = installer.info_do_patch(css_dir / css_name)
        if info.get("version") != current_version:
            return Estado.ATUALIZACAO_NECESSARIA

    if len(ours) < len(existing):
        return Estado.ATUALIZACAO_NECESSARIA

    if _waiting_restart(steam):
        return Estado.AGUARDANDO_REINICIO
    return Estado.SINCRONIZADA


def precisa_reparo(steam_path: "str | Path") -> bool:
    """``True`` when the skin is installed but needs to be reapplied."""
    return verificar_estado(steam_path) is Estado.ATUALIZACAO_NECESSARIA


def reparar_se_seguro(steam_path: "str | Path", perfil: Optional[dict] = None) -> bool:
    """Reapply the skin only when it can be done without data loss.

    Refuses when the target is missing, unwritable, in conflict with a
    third party, unrepairable (missing backup) or already in sync, and
    defers whenever Steam is running. Returns ``True`` when a repair ran.
    """
    steam = expand_steam_path(steam_path)
    estado = verificar_estado(steam)

    if estado in (
        Estado.NAO_ENCONTRADA,
        Estado.NAO_INSTALADA,
        Estado.PERMISSAO,
        Estado.CONFLITO_TERCEIROS,
        Estado.INCOMPATIVEL,
        Estado.SINCRONIZADA,
    ):
        logging.debug("No safe repair for state %s", estado)
        return False

    if steam_em_execucao():
        logging.info("Steam is running; deferring skin repair for %s", steam)
        return False

    if _has_foreign_header(steam):
        logging.warning("Third-party patch detected; refusing to repair %s", steam)
        return False

    perfil = perfil or {}
    try:
        return installer.instalar(
            steam,
            perfil.get("theme_slug") or DEFAULT_COLORTHEME,
            perfil.get("accent", "auto"),
            perfil.get("mode", "auto"),
            perfil.get("opcoes_avancadas"),
        )
    except installer.SkinError as error:
        logging.error("Safe repair failed for %s: %s", steam, error)
        return False
