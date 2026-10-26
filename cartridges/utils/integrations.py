# integrations.py
#
# Copyright 2026 Jolven contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Data-driven registry of every external program Jolven integrates with.

One :class:`Integracao` per program (stable ``chave``, translated
display strings, Flathub app id when one exists, native binary). The
Integrações page consumes :func:`listar_integracoes`,
:func:`obter_status` and :func:`instalar_flatpak` — nothing here touches
GTK, so the whole module imports and runs headless.

``obter_status`` follows the native-then-flatpak precedence of
``sunshine.installation_type`` and probes only ``shutil.which`` and
``flatpak info`` (via ``launchers.flatpak_installed``): no network, no
writes, safe to call from a worker thread. ``instalar_flatpak`` mirrors
``sunshine.install_flatpak``: user-level Flathub remote, then install,
stderr surfaced through :class:`RuntimeError` and never logged at info.
"""

from __future__ import annotations

import builtins
import logging
import shutil
import subprocess

from dataclasses import dataclass

from cartridges.launchers import flatpak_installed
from cartridges.utils.sunshine import (
    SUNSHINE_BINARY,
    SUNSHINE_FLATPAK_ID,
    SUNSHINE_FLATHUB_URL,
)


def _(mensagem: str) -> str:
    """Translate *mensagem* via the launcher-installed gettext, else identity.

    Defined locally (instead of assuming the ``_`` builtin like UI
    modules do) because ``CATEGORIAS`` and the registry are evaluated at
    import time — tests and tools importing this module without the
    launcher keep working, and ``xgettext`` still extracts the strings.
    """
    traduzir = getattr(builtins, "_", None)
    if callable(traduzir):
        try:
            return str(traduzir(mensagem))
        except Exception:  # pylint: disable=broad-exception-caught
            pass
    return mensagem


#: ``obter_status`` results.
STATUS_NATIVO = "nativo"
STATUS_FLATPAK = "flatpak"
STATUS_AUSENTE = "ausente"

#: Same remote ``sunshine.install_flatpak`` adds; shared on purpose so
#: both install paths always agree on the user Flathub remote.
FLATHUB_URL = SUNSHINE_FLATHUB_URL

#: Category keys -> translated labels, in display order.
CATEGORIAS: dict[str, str] = {
    "streaming": _("Streaming"),
    "launchadores": _("Launchadores"),
    "emuladores": _("Emuladores"),
    "ferramentas": _("Ferramentas"),
}


@dataclass(frozen=True)
class Integracao:
    """One external program Jolven can detect or install."""

    chave: str  #: stable id: "sunshine", "moonlight", "steam", ...
    titulo: str  #: display name (already translated)
    categoria: str  #: one of ``CATEGORIAS``
    descricao: str  #: one-line subtitle (already translated)
    app_id_flatpak: str | None  #: Flathub app id, when there is one
    binario: str | None  #: native binary for ``shutil.which``

    def __post_init__(self) -> None:
        if self.categoria not in CATEGORIAS:
            raise ValueError(f"unknown category: {self.categoria!r}")
        if not self.app_id_flatpak and not self.binario:
            raise ValueError(f"{self.chave}: needs a flatpak id or a binary")


#: Grounded on ``cartridges/importer/*_source.py``,
#: ``cartridges/utils/launcher.py`` and ``.agents/integrations.md``.
#: Entries without a Flathub id (Flatpak itself, Yuzu, Waydroid,
#: Legendary) are status-only: never offered for install from the page.
_REGISTRO: tuple[Integracao, ...] = (
    # -- streaming --
    Integracao(
        "sunshine", _("Sunshine"), "streaming",
        _("Servidor que transmite seus jogos para o Moonlight"),
        SUNSHINE_FLATPAK_ID, SUNSHINE_BINARY,
    ),
    Integracao(
        "moonlight", _("Moonlight"), "streaming",
        _("Cliente que reproduz jogos transmitidos pelo Sunshine"),
        "com.moonlight_stream.Moonlight", "moonlight",
    ),
    # -- launchadores --
    Integracao(
        "steam", _("Steam"), "launchadores",
        _("Loja, biblioteca e jogos da Valve"),
        "com.valvesoftware.Steam", "steam",
    ),
    Integracao(
        "lutris", _("Lutris"), "launchadores",
        _("Launchador aberto para jogos e aplicativos no Linux"),
        "net.lutris.Lutris", "lutris",
    ),
    Integracao(
        "heroic", _("Heroic Games Launcher"), "launchadores",
        _("Jogos da Epic, GOG e Amazon em um único launchador"),
        "com.heroicgameslauncher.hgl", "heroic",
    ),
    Integracao(
        "bottles", _("Bottles"), "launchadores",
        _("Executa jogos e aplicativos Windows usando Wine"),
        "com.usebottles.bottles", "bottles",
    ),
    Integracao(
        "itch", _("itch.io"), "launchadores",
        _("Loja e cliente de jogos independentes do itch.io"),
        "io.itch.itch", "itch",
    ),
    Integracao(
        "twintail", _("TwinTail"), "launchadores",
        _("Launchador de jogos gratuitos que rodam pelo navegador"),
        "app.twintaillauncher.ttl", "twintaillauncher",
    ),
    Integracao(
        "legendary", _("Legendary"), "launchadores",
        _("Cliente da linha de comandos para a Epic Games Store"),
        None, "legendary",
    ),
    Integracao(
        "flatpak", _("Flatpak"), "launchadores",
        _("Formato de pacotes usado para instalar os demais aplicativos"),
        None, "flatpak",
    ),
    # -- emuladores --
    Integracao(
        "retroarch", _("RetroArch"), "emuladores",
        _("Frontend de emuladores com dezenas de núcleos"),
        "org.libretro.RetroArch", "retroarch",
    ),
    Integracao(
        "dolphin", _("Dolphin"), "emuladores",
        _("Emulador de GameCube e Wii"),
        "org.DolphinEmu.dolphin-emu", "dolphin-emu",
    ),
    Integracao(
        "cemu", _("Cemu"), "emuladores",
        _("Emulador de Wii U"),
        "info.cemu.Cemu", "Cemu",
    ),
    Integracao(
        "retrodeck", _("RetroDECK"), "emuladores",
        _("Suíte de emuladores empacotada como um único aplicativo"),
        "net.retrodeck.retrodeck", "retrodeck",
    ),
    Integracao(
        "yuzu", _("Yuzu"), "emuladores",
        _("Emulador de Nintendo Switch"),
        None, "yuzu",
    ),
    Integracao(
        "waydroid", _("Waydroid"), "emuladores",
        _("Executa aplicativos e jogos do Android em contêiner"),
        None, "waydroid",
    ),
    # -- ferramentas --
    Integracao(
        "gpu-screen-recorder", _("GPU Screen Recorder"), "ferramentas",
        _("Grava jogos direto da GPU, sem pesar no desempenho"),
        "com.dec05eba.gpu_screen_recorder", "gpu-screen-recorder",
    ),
    Integracao(
        "openrgb", _("OpenRGB"), "ferramentas",
        _("Controla a iluminação RGB de memórias, placas, coolers e periféricos"),
        "org.openrgb.OpenRGB", "openrgb",
    ),
)


def listar_integracoes() -> list[Integracao]:
    """Return every known integration, in category display order."""
    return list(_REGISTRO)


def obter_status(integracao: Integracao) -> str:
    """Tell how *integracao* is installed: ``nativo``, ``flatpak`` or ``ausente``.

    The native binary wins over Flatpak, the same precedence used by
    ``sunshine.installation_type`` and ``launchers.flatpak_installed``.
    Read-only probes only (``shutil.which`` plus ``flatpak info``), no
    network and no shared state: safe to call from a worker thread.
    """
    if integracao.binario and shutil.which(integracao.binario):
        return STATUS_NATIVO
    if integracao.app_id_flatpak and flatpak_installed(
        integracao.app_id_flatpak
    ):
        return STATUS_FLATPAK
    return STATUS_AUSENTE


def instalar_flatpak(app_id: str) -> None:
    """Install *app_id* from Flathub for the current user (no sudo).

    Adds the user Flathub remote when missing, then installs the app —
    the same steps ``sunshine.install_flatpak`` performs. Raises
    :class:`RuntimeError` carrying the command's stderr on failure;
    success is silent. Installation can take minutes: run it from a
    worker, never from the GTK thread.
    """
    if not (app_id or "").strip():
        raise RuntimeError("cannot install without an app id")
    flatpak = shutil.which("flatpak")
    if not flatpak:
        raise RuntimeError("Flatpak is not available")
    steps = (
        [
            flatpak,
            "remote-add",
            "--user",
            "--if-not-exists",
            "flathub",
            FLATHUB_URL,
        ],
        [flatpak, "install", "--user", "-y", "flathub", app_id],
    )
    for command in steps:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeError(f"{app_id} install failed: {error}") from error
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise RuntimeError(
                stderr or f"{app_id} install did not complete"
            )
    logging.debug("Flatpak install finished: %s", app_id)
