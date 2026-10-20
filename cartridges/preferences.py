# preferences.py
#
# Copyright 2022-2023 redclaw
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

# pyright: reportAssignmentType=none

import logging
import math
import re
import threading
from shutil import which
from datetime import date
from pathlib import Path
from shutil import rmtree
from typing import Any, Callable, Optional

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from cartridges import shared
from cartridges.errors.friendly_error import FriendlyError
from cartridges.game import Game
from cartridges.hardware import drm_connectors, pipewire_nodes, vrr_supported
from cartridges.importer.bottles_source import BottlesSource
from cartridges.importer.desktop_source import DesktopSource
from cartridges.importer.dolphin_source import DolphinSource
from cartridges.importer.eden_source import EdenSource
from cartridges.importer.flatpak_source import FlatpakSource
from cartridges.importer.heroic_source import HeroicSource
from cartridges.importer.itch_source import ItchSource
from cartridges.importer.legendary_source import LegendarySource
from cartridges.importer.location import UnresolvableLocationError
from cartridges.importer.lutris_source import LutrisSource
from cartridges.importer.retroarch_source import RetroarchSource
from cartridges.importer.shortcuts_source import ShortcutsSource
from cartridges.importer.source import Source
from cartridges.importer.steam_source import SteamSource
from cartridges.importer.twintail_source import TwintailSource
from cartridges.importer.uzdoom_source import UzdoomSource
from cartridges.importer.waydroid_source import WaydroidSource
from cartridges.importer.yuzu_source import YuzuSource
from cartridges.store.managers.sgdb_manager import SgdbManager
from cartridges.store.managers.thegamesdb_manager import TheGamesDBManager
from cartridges.utils import backup
from cartridges.utils import global_shortcut
from cartridges.utils import session_fita
from cartridges.utils.create_dialog import create_dialog
from cartridges.utils.na_tela import entregar_na_tela


# ── Aparência: tema do aplicativo ─────────────────────────────────────────

#: Tema padrão do Jolven; único que aceita os brilhos RGB.
SLUG_PADRAO = "jolven"

#: Modos de exibição, na ordem do seletor.
MODOS = ("light", "dark", "auto")
MODO_PADRAO = "auto"

#: Cores de destaque oferecidas, na ordem do seletor. Os valores seguem a
#: paleta de destaque do libadwaita para funcionarem em tema claro e escuro.
DESTAQUES: tuple[tuple[str, str], ...] = (
    ("Azul", "#3584e4"),
    ("Verde-água", "#2190a4"),
    ("Verde", "#33d17a"),
    ("Amarelo", "#f5c211"),
    ("Laranja", "#ff7800"),
    ("Vermelho", "#e01b24"),
    ("Rosa", "#d56199"),
    ("Roxo", "#9141ac"),
    ("Cinza-azulado", "#6f8396"),
)

#: Cor usada quando o usuário abre a cor personalizada sem ter escolhido uma.
DESTAQUE_PADRAO = "#3584e4"


def _estados_steam() -> dict[str, str]:
    """Os oito estados possíveis da integração com a Steam (chave → texto).

    Derivado de ``recovery.TEXTOS_ESTADO`` (chaveado por ``Estado``) para que
    a página nunca divirja do backend: um estado novo sem rótulo aparece aqui
    automaticamente assim que for registrado lá.
    """
    from cartridges.integrations.steam_skin.recovery import (  # noqa: PLC0415
        TEXTOS_ESTADO,
    )

    return {estado.value: texto for estado, texto in TEXTOS_ESTADO.items()}


def _rgba_do_hex(hexcor: str) -> Gdk.RGBA:
    """Converte ``#RRGGBB`` em :class:`Gdk.RGBA`, com recuo seguro."""
    rgba = Gdk.RGBA()
    if not hexcor or not rgba.parse(hexcor):
        rgba.parse(DESTAQUE_PADRAO)
    return rgba


def _hex_do_rgba(rgba: Gdk.RGBA) -> str:
    """Converte :class:`Gdk.RGBA` em ``#rrggbb``."""

    def canal(valor: float) -> int:
        return round(max(0.0, min(1.0, valor)) * 255)

    return "#{:02x}{:02x}{:02x}".format(
        canal(rgba.red), canal(rgba.green), canal(rgba.blue)
    )


class _CatalogoTemas:
    """Leitura tolerante do catálogo da lane de temas.

    O módulo ``cartridges.themes`` é opcional para esta página: importamos só
    quando a página é construída e aceitamos tanto os nomes publicados
    (``CATALOGO``, ``obter_tema``, ``tema_padrao``, ``nome_do_tema``,
    ``slug_é_dark_only``) quanto os nomes atualmente presentes no módulo. Sem
    catálogo, a galeria mostra o estado de erro e o restante da página
    continua funcionando.
    """

    def __init__(self) -> None:
        self._catalog: Any = None
        self.slugs: list[str] = []
        self._carregar()

    # -- carregamento ----------------------------------------------------

    def _carregar(self) -> None:
        try:
            from cartridges.themes import catalog as catalog_module  # noqa: PLC0415
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Catálogo de temas indisponível", exc_info=True)
            return

        self._catalog = catalog_module
        brutos = (
            getattr(catalog_module, "CATALOGO", None)
            or getattr(catalog_module, "CATALOG_SLUGS", None)
            or []
        )
        slugs: list[str] = []
        for item in brutos:
            slug = item if isinstance(item, str) else getattr(item, "slug", None)
            if isinstance(slug, str) and slug and slug not in slugs:
                slugs.append(slug)
        if SLUG_PADRAO not in slugs:
            slugs.append(SLUG_PADRAO)
        self.slugs = slugs

    @property
    def disponivel(self) -> bool:
        return bool(self.slugs)

    # -- consultas -------------------------------------------------------

    def _primeiro(self, *nomes: str) -> Any:
        """Primeiro atributo presente no módulo, resolvendo callables."""
        for nome in nomes:
            valor = getattr(self._catalog, nome, None)
            if valor is None:
                continue
            if callable(valor):
                try:
                    valor = valor()
                except Exception:  # pylint: disable=broad-exception-caught
                    continue
            if valor is not None:
                return valor
        return None

    def padrao(self) -> str:
        valor = self._primeiro("DEFAULT_SLUG")
        return valor if isinstance(valor, str) and valor else SLUG_PADRAO

    def tema(self, slug: str) -> Any:
        for nome in ("obter_tema", "get_palette", "from_catalog_slug"):
            funcao = getattr(self._catalog, nome, None)
            if not callable(funcao):
                continue
            try:
                return funcao(slug)
            except Exception:  # pylint: disable=broad-exception-caught
                continue
        return None

    def nome(self, slug: str) -> str:
        funcao = getattr(self._catalog, "nome_do_tema", None)
        if callable(funcao):
            try:
                nome = funcao(slug)
            except Exception:  # pylint: disable=broad-exception-caught
                nome = None
            if isinstance(nome, str) and nome:
                return nome
        tabela = getattr(self._catalog, "NAMES_BY_SLUG", None)
        if isinstance(tabela, dict) and isinstance(tabela.get(slug), str):
            return tabela[slug]
        nome = getattr(self.tema(slug), "name", None)
        return nome if isinstance(nome, str) and nome else slug

    def dark_only(self, slug: str) -> bool:
        funcao = getattr(self._catalog, "slug_é_dark_only", None)
        if callable(funcao):
            try:
                return bool(funcao(slug))
            except Exception:  # pylint: disable=broad-exception-caught
                pass
        tabela = getattr(self._catalog, "IS_DARK_ONLY_BY_SLUG", None)
        if isinstance(tabela, dict) and slug in tabela:
            return bool(tabela[slug])
        return bool(getattr(self.tema(slug), "is_dark_only", False))

    def cores(self, slug: str) -> tuple[Optional[str], Optional[str]]:
        """(fundo, destaque) para o desenho de reserva da miniatura."""
        tema = self.tema(slug)
        fundo = getattr(tema, "bg", None)
        destaque = getattr(tema, "accent_bg", None) or getattr(tema, "accent_fg", None)
        return (
            fundo if isinstance(fundo, str) else None,
            destaque if isinstance(destaque, str) else None,
        )


# ── Aparência: integração com a Steam ────────────────────────────────────

#: Opções avançadas que a skin do Jolven realmente aplica. A árvore vendorada
#: traz ``fonts/**``, ``extras/**`` e ``windowcontrols/**`` (ver
#: ``data/vendor/adwaita-for-steam/UPSTREAM.md``) e o instalador copia esses
#: arquivos para a skin, então todas as opções finas têm efeito. Serve de
#: recuo quando o gerenciador não está disponível; com gerenciador, o que ele
#: anuncia via ``opcoes_suportadas()`` prevalece.
OPCOES_STEAM_PADRAO: frozenset[str] = frozenset(
    {
        "fonte",
        "window-controls-theme",
        "window-controls-layout",
        "rounded-corners",
        "cursor-pointer",
        "hide-whats-new",
        "sidebar-hover",
        "uncrop-covers",
        "hide-qr",
    }
)

#: Todas as opções que a página sabe exibir, na ordem do ExpanderRow.
OPCOES_STEAM: tuple[str, ...] = (
    "fonte",
    "window-controls-theme",
    "window-controls-layout",
    "rounded-corners",
    "cursor-pointer",
    "hide-whats-new",
    "sidebar-hover",
    "uncrop-covers",
    "hide-qr",
)

#: Id do widget na página → chave entendida pelo instalador da skin
#: (``cartridges/integrations/steam_skin/installer.py``). As opções sem
#: equivalente conhecido viajam com o próprio id, para uma versão futura da
#: skin poder adotá-las.
CHAVES_PERFIL_STEAM: dict[str, str] = {
    "fonte": "font",
    "window-controls-theme": "windowcontrols_theme",
    "window-controls-layout": "windowcontrols_layout",
    "rounded-corners": "rounded_corners",
    "cursor-pointer": "cursor_pointer",
    "hide-whats-new": "hide_whats_new",
    "sidebar-hover": "sidebar_hover",
    "uncrop-covers": "uncrop_covers",
    "hide-qr": "hide_qr",
}

#: Inverso de :data:`CHAVES_PERFIL_STEAM`, para aceitar capacidades anunciadas
#: pela lane em qualquer uma das duas grafias.
CHAVES_UI_POR_PERFIL: dict[str, str] = {
    perfil: ui for ui, perfil in CHAVES_PERFIL_STEAM.items()
}


@Gtk.Template(resource_path=shared.PREFIX + "/gtk/preferences.ui")
class CartridgesPreferences(Adw.PreferencesDialog):
    __gtype_name__ = "CartridgesPreferences"

    general_page: Adw.PreferencesPage = Gtk.Template.Child()
    import_page: Adw.PreferencesPage = Gtk.Template.Child()
    sgdb_page: Adw.PreferencesPage = Gtk.Template.Child()
    recorder_page: Adw.PreferencesPage = Gtk.Template.Child()

    sources_group: Adw.PreferencesGroup = Gtk.Template.Child()

    exit_after_launch_switch: Adw.SwitchRow = Gtk.Template.Child()
    cover_launches_game_switch: Adw.SwitchRow = Gtk.Template.Child()
    agrupar_duplicados_switch: Adw.SwitchRow = Gtk.Template.Child()
    language_row: Adw.ComboRow = Gtk.Template.Child()
    high_quality_images_switch: Adw.SwitchRow = Gtk.Template.Child()
    app_icon_row: Adw.ComboRow = Gtk.Template.Child()
    xbox_cloud_gaming_switch: Adw.SwitchRow = Gtk.Template.Child()
    xcloud_account_row: Adw.ActionRow = Gtk.Template.Child()
    xcloud_login_button: Gtk.Button = Gtk.Template.Child()
    xcloud_fullscreen_on_start_switch: Adw.SwitchRow = Gtk.Template.Child()

    sunshine_auto_sync_switch: Adw.SwitchRow = Gtk.Template.Child()
    sunshine_apps_path_row: Adw.EntryRow = Gtk.Template.Child()
    sunshine_sync_all_row: Adw.ActionRow = Gtk.Template.Child()
    sunshine_sync_all_button: Gtk.Button = Gtk.Template.Child()
    sunshine_host_row: Adw.EntryRow = Gtk.Template.Child()
    sunshine_port_row: Adw.EntryRow = Gtk.Template.Child()
    sunshine_username_row: Adw.EntryRow = Gtk.Template.Child()
    sunshine_password_row: Adw.PasswordEntryRow = Gtk.Template.Child()
    sunshine_status_row: Adw.ActionRow = Gtk.Template.Child()
    sunshine_test_button: Gtk.Button = Gtk.Template.Child()
    sunshine_web_button: Gtk.Button = Gtk.Template.Child()
    sunshine_start_button: Gtk.Button = Gtk.Template.Child()
    sunshine_apps_group: Adw.PreferencesGroup = Gtk.Template.Child()
    sunshine_api_sync_button: Gtk.Button = Gtk.Template.Child()
    sunshine_max_bitrate_row: Adw.EntryRow = Gtk.Template.Child()
    sunshine_min_fps_row: Adw.EntryRow = Gtk.Template.Child()
    sunshine_upnp_switch: Adw.SwitchRow = Gtk.Template.Child()
    sunshine_origin_row: Adw.EntryRow = Gtk.Template.Child()
    sunshine_encoder_row: Adw.EntryRow = Gtk.Template.Child()
    sunshine_apply_button: Gtk.Button = Gtk.Template.Child()
    sunshine_pairings_group: Adw.PreferencesGroup = Gtk.Template.Child()
    sunshine_unpair_all_button: Gtk.Button = Gtk.Template.Child()

    recorder_enabled_switch: Adw.SwitchRow = Gtk.Template.Child()
    recorder_source_row: Adw.ComboRow = Gtk.Template.Child()
    recorder_output_dir_row: Adw.EntryRow = Gtk.Template.Child()
    recorder_container_row: Adw.ComboRow = Gtk.Template.Child()
    recorder_codec_row: Adw.ComboRow = Gtk.Template.Child()
    recorder_quality_row: Adw.ComboRow = Gtk.Template.Child()
    recorder_bitrate_mode_row: Adw.ComboRow = Gtk.Template.Child()
    recorder_fps_row: Adw.SpinRow = Gtk.Template.Child()
    recorder_cursor_switch: Adw.SwitchRow = Gtk.Template.Child()
    recorder_scale_row: Adw.EntryRow = Gtk.Template.Child()
    recorder_audio_row: Adw.ComboRow = Gtk.Template.Child()
    recorder_audio_codec_row: Adw.ComboRow = Gtk.Template.Child()
    recorder_audio_bitrate_row: Adw.SpinRow = Gtk.Template.Child()
    recorder_replay_seconds_row: Adw.SpinRow = Gtk.Template.Child()
    recorder_replay_storage_row: Adw.ComboRow = Gtk.Template.Child()
    recorder_stream_url_row: Adw.EntryRow = Gtk.Template.Child()

    auto_import_switch: Adw.SwitchRow = Gtk.Template.Child()
    remove_missing_switch: Adw.SwitchRow = Gtk.Template.Child()

    atalho_global_row: Adw.ActionRow = Gtk.Template.Child()
    atalho_global_button: Gtk.Button = Gtk.Template.Child()

    steam_expander_row: Adw.ExpanderRow = Gtk.Template.Child()
    steam_data_action_row: Adw.ActionRow = Gtk.Template.Child()
    steam_data_file_chooser_button: Gtk.Button = Gtk.Template.Child()

    lutris_expander_row: Adw.ExpanderRowClass = Gtk.Template.Child()
    lutris_data_action_row: Adw.ActionRow = Gtk.Template.Child()
    lutris_data_file_chooser_button: Gtk.Button = Gtk.Template.Child()
    lutris_import_steam_switch: Adw.SwitchRow = Gtk.Template.Child()
    lutris_import_flatpak_switch: Adw.SwitchRow = Gtk.Template.Child()

    heroic_expander_row: Adw.ExpanderRow = Gtk.Template.Child()
    heroic_config_action_row: Adw.ActionRow = Gtk.Template.Child()
    heroic_config_file_chooser_button: Gtk.Button = Gtk.Template.Child()
    heroic_import_epic_switch: Adw.SwitchRow = Gtk.Template.Child()
    heroic_import_gog_switch: Adw.SwitchRow = Gtk.Template.Child()
    heroic_import_amazon_switch: Adw.SwitchRow = Gtk.Template.Child()
    heroic_import_sideload_switch: Adw.SwitchRow = Gtk.Template.Child()

    bottles_expander_row: Adw.ExpanderRow = Gtk.Template.Child()
    bottles_data_action_row: Adw.ActionRow = Gtk.Template.Child()
    bottles_data_file_chooser_button: Gtk.Button = Gtk.Template.Child()

    dolphin_expander_row: Adw.ExpanderRow = Gtk.Template.Child()
    dolphin_cache_action_row: Adw.ActionRow = Gtk.Template.Child()
    dolphin_cache_file_chooser_button: Gtk.Button = Gtk.Template.Child()

    itch_expander_row: Adw.ExpanderRow = Gtk.Template.Child()
    itch_config_action_row: Adw.ActionRow = Gtk.Template.Child()
    itch_config_file_chooser_button: Gtk.Button = Gtk.Template.Child()

    legendary_expander_row: Adw.ExpanderRow = Gtk.Template.Child()
    legendary_config_action_row: Adw.ActionRow = Gtk.Template.Child()
    legendary_config_file_chooser_button: Gtk.Button = Gtk.Template.Child()

    retroarch_expander_row: Adw.ExpanderRow = Gtk.Template.Child()
    retroarch_config_action_row: Adw.ActionRow = Gtk.Template.Child()
    retroarch_config_file_chooser_button: Gtk.Button = Gtk.Template.Child()

    waydroid_expander_row: Adw.ExpanderRow = Gtk.Template.Child()

    yuzu_expander_row: Adw.ExpanderRow = Gtk.Template.Child()
    yuzu_data_action_row: Adw.ActionRow = Gtk.Template.Child()
    yuzu_data_file_chooser_button: Gtk.Button = Gtk.Template.Child()

    eden_expander_row: Adw.ExpanderRow = Gtk.Template.Child()
    eden_data_action_row: Adw.ActionRow = Gtk.Template.Child()
    eden_data_file_chooser_button: Gtk.Button = Gtk.Template.Child()

    uzdoom_expander_row: Adw.ExpanderRow = Gtk.Template.Child()
    uzdoom_data_action_row: Adw.ActionRow = Gtk.Template.Child()
    uzdoom_data_file_chooser_button: Gtk.Button = Gtk.Template.Child()

    twintail_expander_row: Adw.ExpanderRow = Gtk.Template.Child()
    twintail_data_action_row: Adw.ActionRow = Gtk.Template.Child()
    twintail_data_file_chooser_button: Gtk.Button = Gtk.Template.Child()

    shortcuts_expander_row: Adw.ExpanderRow = Gtk.Template.Child()
    shortcuts_location_action_row: Adw.ActionRow = Gtk.Template.Child()
    shortcuts_location_button: Gtk.Button = Gtk.Template.Child()
    shortcuts_recursive_switch: Adw.SwitchRow = Gtk.Template.Child()

    flatpak_expander_row: Adw.ExpanderRow = Gtk.Template.Child()
    flatpak_system_data_action_row: Adw.ActionRow = Gtk.Template.Child()
    flatpak_system_data_file_chooser_button: Gtk.Button = Gtk.Template.Child()
    flatpak_user_data_action_row: Adw.ActionRow = Gtk.Template.Child()
    flatpak_user_data_file_chooser_button: Gtk.Button = Gtk.Template.Child()
    flatpak_import_launchers_switch: Adw.SwitchRow = Gtk.Template.Child()

    desktop_switch: Adw.SwitchRow = Gtk.Template.Child()

    sgdb_key_group: Adw.PreferencesGroup = Gtk.Template.Child()
    sgdb_key_entry_row: Adw.EntryRow = Gtk.Template.Child()
    sgdb_switch: Adw.SwitchRow = Gtk.Template.Child()
    sgdb_prefer_switch: Adw.SwitchRow = Gtk.Template.Child()
    sgdb_animated_switch: Adw.SwitchRow = Gtk.Template.Child()
    sgdb_fetch_button: Gtk.Button = Gtk.Template.Child()
    sgdb_stack: Gtk.Stack = Gtk.Template.Child()
    sgdb_spinner: Adw.Spinner = Gtk.Template.Child()
    thegamesdb_key_group: Adw.PreferencesGroup = Gtk.Template.Child()
    thegamesdb_key_entry_row: Adw.EntryRow = Gtk.Template.Child()
    thegamesdb_switch: Adw.SwitchRow = Gtk.Template.Child()
    thegamesdb_fetch_button: Gtk.Button = Gtk.Template.Child()
    thegamesdb_stack: Gtk.Stack = Gtk.Template.Child()
    thegamesdb_spinner: Adw.Spinner = Gtk.Template.Child()
    igdb_key_group: Adw.PreferencesGroup = Gtk.Template.Child()
    igdb_client_id_entry_row: Adw.EntryRow = Gtk.Template.Child()
    igdb_client_secret_entry_row: Adw.EntryRow = Gtk.Template.Child()

    danger_zone_group = Gtk.Template.Child()
    remove_all_games_button_row = Gtk.Template.Child()
    reset_button_row = Gtk.Template.Child()
    export_backup_button_row = Gtk.Template.Child()
    import_backup_button_row = Gtk.Template.Child()

    playtime_tracking_switch: Adw.SwitchRow = Gtk.Template.Child()
    show_news_button_switch: Adw.SwitchRow = Gtk.Template.Child()
    session_wallpaper_switch: Adw.SwitchRow = Gtk.Template.Child()
    wallhaven_key_entry_row: Adw.EntryRow = Gtk.Template.Child()
    wallpaper_restore_row: Adw.ActionRow = Gtk.Template.Child()
    wallpaper_restore_button: Gtk.Button = Gtk.Template.Child()
    session_fita_switch: Adw.SwitchRow = Gtk.Template.Child()
    game_mode_group: Adw.PreferencesGroup = Gtk.Template.Child()
    game_mode_use_gamemode_switch: Adw.SwitchRow = Gtk.Template.Child()
    game_mode_use_mangohud_switch: Adw.SwitchRow = Gtk.Template.Child()
    game_mode_enable_fps_limiter_switch: Adw.SwitchRow = Gtk.Template.Child()
    game_mode_enable_vrr_switch: Adw.SwitchRow = Gtk.Template.Child()
    game_mode_start_library_switch: Adw.SwitchRow = Gtk.Template.Child()
    game_mode_hide_mouse_cursor_switch: Adw.SwitchRow = Gtk.Template.Child()
    game_overlay_button_row: Adw.ComboRow = Gtk.Template.Child()
    game_mode_monitor_entry_row: Adw.ComboRow = Gtk.Template.Child()
    game_mode_audio_output_entry_row: Adw.ComboRow = Gtk.Template.Child()
    game_mode_audio_input_entry_row: Adw.ComboRow = Gtk.Template.Child()
    fita_brilho_row: Adw.SpinRow = Gtk.Template.Child()
    fita_brilho_individual_row: Adw.ActionRow = Gtk.Template.Child()
    fita_brilho_individual_button: Gtk.Button = Gtk.Template.Child()
    fita_cor_app_row: Adw.ActionRow = Gtk.Template.Child()
    fita_cor_app_reset: Gtk.Button = Gtk.Template.Child()
    fita_cor_app_menu: Gtk.MenuButton = Gtk.Template.Child()
    fita_cor_app_amostra: Gtk.DrawingArea = Gtk.Template.Child()
    fita_cor_app_seletor: Gtk.ColorChooserWidget = Gtk.Template.Child()
    fita_configurar_row: Adw.ActionRow = Gtk.Template.Child()
    fita_configurar_button: Gtk.Button = Gtk.Template.Child()
    fita_testar_row: Adw.ActionRow = Gtk.Template.Child()
    fita_testar_button: Gtk.Button = Gtk.Template.Child()

    appearance_page: Adw.PreferencesPage = Gtk.Template.Child()
    appearance_group: Adw.PreferencesGroup = Gtk.Template.Child()
    temas_flowbox: Gtk.FlowBox = Gtk.Template.Child()
    tema_galeria_stack: Gtk.Stack = Gtk.Template.Child()
    tema_galeria_spinner: Adw.Spinner = Gtk.Template.Child()
    tema_galeria_erro: Adw.StatusPage = Gtk.Template.Child()
    tema_galeria_scroll: Gtk.ScrolledWindow = Gtk.Template.Child()
    tema_selecionado_row: Adw.ActionRow = Gtk.Template.Child()
    tema_modo_row: Adw.ComboRow = Gtk.Template.Child()
    tema_destaque_row: Adw.ComboRow = Gtk.Template.Child()
    tema_cor_personalizada_row: Adw.ActionRow = Gtk.Template.Child()
    tema_cor_button: Gtk.ColorDialogButton = Gtk.Template.Child()
    tema_cor_padrao_switch: Adw.SwitchRow = Gtk.Template.Child()
    tema_glows_switch: Adw.SwitchRow = Gtk.Template.Child()
    tema_restaurar_row: Adw.ButtonRow = Gtk.Template.Child()

    steam_group: Adw.PreferencesGroup = Gtk.Template.Child()
    steam_skin_switch: Adw.SwitchRow = Gtk.Template.Child()
    steam_instalacao_row: Adw.ComboRow = Gtk.Template.Child()
    steam_estado_row: Adw.ActionRow = Gtk.Template.Child()
    steam_estado_spinner: Adw.Spinner = Gtk.Template.Child()
    steam_aplicar_row: Adw.ActionRow = Gtk.Template.Child()
    steam_aplicar_button: Gtk.Button = Gtk.Template.Child()
    steam_reparar_row: Adw.ActionRow = Gtk.Template.Child()
    steam_reparar_button: Gtk.Button = Gtk.Template.Child()
    steam_restaurar_row: Adw.ActionRow = Gtk.Template.Child()
    steam_restaurar_button: Gtk.Button = Gtk.Template.Child()
    steam_avancado_row: Adw.ExpanderRow = Gtk.Template.Child()
    steam_fonte_row: Adw.ComboRow = Gtk.Template.Child()
    steam_window_controls_theme_row: Adw.ComboRow = Gtk.Template.Child()
    steam_window_controls_layout_row: Adw.ComboRow = Gtk.Template.Child()
    steam_rounded_corners_switch: Adw.SwitchRow = Gtk.Template.Child()
    steam_cursor_pointer_switch: Adw.SwitchRow = Gtk.Template.Child()
    steam_hide_whats_new_switch: Adw.SwitchRow = Gtk.Template.Child()
    steam_sidebar_hover_switch: Adw.SwitchRow = Gtk.Template.Child()
    steam_uncrop_covers_switch: Adw.SwitchRow = Gtk.Template.Child()
    steam_hide_qr_switch: Adw.SwitchRow = Gtk.Template.Child()

    removed_games: set[Game] = set()
    warning_menu_buttons: dict = {}

    # Aparência: catálogo de temas e integração com a Steam.
    _catalogo_temas: Optional["_CatalogoTemas"] = None
    _manager_tema: Any = None
    _manager_steam: Any = None
    _manager_steam_carregado: bool = False
    _instalacoes_steam: list = []
    _steam_ocupada: bool = False
    _sync_steam_id: Optional[int] = None
    _bloqueio_ui: int = 0

    is_open = False
    _teste_em_curso: Optional[threading.Event] = None

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        # Make it so only one dialog can be open at a time
        self.__class__.is_open = True
        self.connect("closed", self._ao_fechar)

        self.file_chooser = Gtk.FileDialog()

        self.toast = Adw.Toast.new(_("All games removed"))
        self.toast.set_button_label(_("Undo"))
        self.toast.connect("button-clicked", self.undo_remove_all, None)
        self.toast.set_priority(Adw.ToastPriority.HIGH)

        (shortcut_controller := Gtk.ShortcutController()).add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("<primary>z"),
                Gtk.CallbackAction.new(self.undo_remove_all),
            )
        )
        self.add_controller(shortcut_controller)

        # General
        self.remove_all_games_button_row.connect("activated", self.remove_all_games)
        self.export_backup_button_row.connect("activated", self.export_backup)
        self.import_backup_button_row.connect("activated", self.import_backup)
        self.setup_app_icon_row()
        self.setup_language_row()

        # "Exit After Launching Games" makes no sense in the exclusive
        # Jolven Session: closing Jolven ends Gamescope and returns to the
        # login screen, so the option is completely ignored while in the
        # session (see Game.launch) and must stay hidden there.
        if shared.runtime.is_session:
            self.exit_after_launch_switch.set_visible(False)

        # Debug
        if shared.PROFILE == "development":
            self.reset_button_row.set_visible(True)
            self.reset_button_row.connect("activated", self.reset_app)

        # Sources settings
        for source_class in (
            BottlesSource,
            DolphinSource,
            EdenSource,
            FlatpakSource,
            HeroicSource,
            ItchSource,
            LegendarySource,
            LutrisSource,
            RetroarchSource,
            ShortcutsSource,
            SteamSource,
            TwintailSource,
            UzdoomSource,
            WaydroidSource,
            YuzuSource,
        ):
            source = source_class()
            if not source.is_available:
                expander_row = getattr(self, f"{source.source_id}_expander_row")
                expander_row.set_visible(False)
            else:
                self.init_source_row(source)

        # Special case for the desktop source
        if not DesktopSource().is_available:
            self.desktop_switch.set_visible(False)

        # SteamGridDB
        def sgdb_key_changed(*_args: Any) -> None:
            shared.schema.set_string("sgdb-key", self.sgdb_key_entry_row.get_text())

        self.sgdb_key_entry_row.set_text(shared.schema.get_string("sgdb-key"))
        self.sgdb_key_entry_row.connect("changed", sgdb_key_changed)

        # Sunshine
        def sunshine_apps_path_changed(*_args: Any) -> None:
            shared.schema.set_string(
                "sunshine-apps-path",
                self.sunshine_apps_path_row.get_text().strip(),
            )

        self.sunshine_apps_path_row.set_text(
            shared.schema.get_string("sunshine-apps-path")
        )
        self.sunshine_apps_path_row.connect("changed", sunshine_apps_path_changed)
        self.sunshine_sync_all_button.connect("clicked", self.sincronizar_sunshine)

        # Sunshine remoto (a senha vive no cofre do usuário: Secret Service)
        def sunshine_host_changed(*_args: Any) -> None:
            shared.schema.set_string(
                "sunshine-host", self.sunshine_host_row.get_text().strip()
            )

        def sunshine_port_changed(*_args: Any) -> None:
            try:
                porta = int(self.sunshine_port_row.get_text().strip())
            except ValueError:
                return
            if 1 <= porta <= 65535:
                shared.schema.set_int("sunshine-port", porta)

        def sunshine_username_changed(*_args: Any) -> None:
            shared.schema.set_string(
                "sunshine-username", self.sunshine_username_row.get_text().strip()
            )

        self.sunshine_host_row.set_text(shared.schema.get_string("sunshine-host"))
        self.sunshine_host_row.connect("changed", sunshine_host_changed)
        self.sunshine_port_row.set_text(str(shared.schema.get_int("sunshine-port")))
        self.sunshine_port_row.connect("changed", sunshine_port_changed)
        self.sunshine_username_row.set_text(
            shared.schema.get_string("sunshine-username")
        )
        self.sunshine_username_row.connect("changed", sunshine_username_changed)
        # A senha mora no cofre, não no GSettings: carrega numa thread (o
        # libsecret fala por D-Bus e pode pedir desbloqueio — nunca na GTK)
        # e persiste com debounce, também fora da thread GTK. A entrega só
        # preenche o campo se o usuário ainda não digitou nada, e o `set_text`
        # programático é o único suprimido — tecla durante o lookup agenda o
        # save normalmente.
        self._senha_sunshine_id: int = 0
        self._senha_sunshine_seq = 0
        self._senha_sunshine_lock = threading.Lock()
        self._senha_sunshine_aplicando = False
        self.sunshine_password_row.connect("changed", self._ao_mudar_senha_sunshine)

        def _carregar_senha() -> None:
            try:
                from cartridges.utils import sunshine_credenciais  # noqa: PLC0415

                salva = sunshine_credenciais.carregar_senha()
            except Exception:  # pylint: disable=broad-exception-caught
                salva = ""
            entregar_na_tela(self._mostrar_senha_sunshine, salva)

        threading.Thread(target=_carregar_senha, daemon=True).start()
        self.sunshine_test_button.connect("clicked", self.testar_sunshine)
        self.sunshine_web_button.connect("clicked", self.abrir_sunshine_web)
        self.sunshine_start_button.connect("clicked", self.iniciar_sunshine)
        self.sunshine_apply_button.connect("clicked", self.aplicar_sunshine_host)
        self.sunshine_api_sync_button.connect("clicked", self.exportar_sunshine_api)
        self.sunshine_unpair_all_button.connect("clicked", self.desemparelhar_todos)
        self._linhas_sunshine: list = []

        self.sgdb_key_group.set_description(
            _(
                "An API key is required to use SteamGridDB. You can generate one {}here{}."
            ).format(
                '<a href="https://www.steamgriddb.com/profile/preferences/api">', "</a>"
            )
        )

        def update_sgdb(*_args: Any) -> None:
            counter = 0
            games_len = len(shared.store)
            sgdb_manager = shared.store.managers[SgdbManager]
            sgdb_manager.reset_cancellable()

            self.sgdb_spinner.set_visible(True)
            self.sgdb_stack.set_visible_child(self.sgdb_spinner)

            self.add_toast(download_toast := Adw.Toast.new(_("Downloading covers…")))

            def update_cover_callback(manager: SgdbManager) -> None:
                nonlocal counter
                nonlocal games_len
                nonlocal download_toast

                counter += 1
                if counter != games_len:
                    return

                for error in manager.collect_errors():
                    if isinstance(error, FriendlyError):
                        create_dialog(self, error.title, error.subtitle)
                        break

                for game in shared.store:
                    game.update()

                toast = Adw.Toast.new(_("Covers updated"))
                toast.set_priority(Adw.ToastPriority.HIGH)
                download_toast.dismiss()
                self.add_toast(toast)

                self.sgdb_spinner.set_visible(False)
                self.sgdb_stack.set_visible_child(self.sgdb_fetch_button)

            for game in shared.store:
                sgdb_manager.process_game(game, {}, update_cover_callback)

        self.sgdb_fetch_button.connect("clicked", update_sgdb)

        # TheGamesDB
        def thegamesdb_key_changed(*_args: Any) -> None:
            key = self.thegamesdb_key_entry_row.get_text().strip()
            shared.schema.set_string("thegamesdb-key", key)
            self.thegamesdb_switch.set_sensitive(bool(key))
            if not key:
                shared.schema.set_boolean("thegamesdb", False)

        self.thegamesdb_key_entry_row.set_text(
            shared.schema.get_string("thegamesdb-key")
        )
        self.thegamesdb_key_entry_row.connect("changed", thegamesdb_key_changed)
        self.thegamesdb_switch.set_sensitive(
            bool(self.thegamesdb_key_entry_row.get_text().strip())
        )
        self.thegamesdb_key_group.set_description(
            _(
                "A chave permite buscar detalhes, capturas de tela e imagens. "
                "Consulte a {}página da API do TheGamesDB{}."
            ).format('<a href="https://api.thegamesdb.net/">', "</a>")
        )

        # IGDB (Client ID + Secret do Twitch; sem eles a fonte fica indisponível)
        def igdb_key_changed(*_args: Any) -> None:
            shared.schema.set_string(
                "igdb-client-id", self.igdb_client_id_entry_row.get_text().strip()
            )
            shared.schema.set_string(
                "igdb-client-secret",
                self.igdb_client_secret_entry_row.get_text().strip(),
            )

        self.igdb_client_id_entry_row.set_text(
            shared.schema.get_string("igdb-client-id")
        )
        self.igdb_client_secret_entry_row.set_text(
            shared.schema.get_string("igdb-client-secret")
        )
        self.igdb_client_id_entry_row.connect("changed", igdb_key_changed)
        self.igdb_client_secret_entry_row.connect("changed", igdb_key_changed)
        self.igdb_key_group.set_description(
            _(
                "As credenciais permitem buscar capas e capturas de tela. "
                "Consulte a {}página da API do IGDB{}."
            ).format('<a href="https://api.igdb.com/">', "</a>")
        )

        def update_thegamesdb(*_args: Any) -> None:
            games = list(shared.store)
            if not games:
                return
            manager = shared.store.managers[TheGamesDBManager]
            manager.reset_cancellable()
            remaining = len(games)
            self.thegamesdb_spinner.set_visible(True)
            self.thegamesdb_stack.set_visible_child(self.thegamesdb_spinner)
            self.add_toast(progress_toast := Adw.Toast.new(_("Buscando metadados…")))

            def updated(_manager: TheGamesDBManager, game: Game) -> None:
                nonlocal remaining
                game.save()
                game.update()
                remaining -= 1
                if remaining:
                    return
                progress_toast.dismiss()
                errors = manager.collect_errors()
                friendly = next(
                    (error for error in errors if isinstance(error, FriendlyError)),
                    None,
                )
                if friendly:
                    create_dialog(self, friendly.title, friendly.subtitle)
                elif errors:
                    create_dialog(
                        self,
                        _("Não foi possível concluir a atualização"),
                        _("Verifique a conexão e tente novamente."),
                    )
                else:
                    self.add_toast(Adw.Toast.new(_("Metadados atualizados")))
                self.thegamesdb_spinner.set_visible(False)
                self.thegamesdb_stack.set_visible_child(
                    self.thegamesdb_fetch_button
                )

            for game in games:
                manager.process_game(
                    game, {}, lambda current, item=game: updated(current, item)
                )

        self.thegamesdb_fetch_button.connect("clicked", update_thegamesdb)

        # Switches
        # As chaves ``*-show-uninstalled`` não entram aqui: viraram filtro de
        # exibição no menu lateral (Janelas laterais de ``create_source_rows``).
        self.bind_switches(
            {
                "exit-after-launch",
                "cover-launches-game",
                "agrupar-duplicados",
                "high-quality-images",
                "xbox-cloud-gaming",
                "xcloud-fullscreen-on-start",
                "sunshine-auto-sync",
                "auto-import",
                "remove-missing",
                "lutris-import-steam",
                "lutris-import-flatpak",
                "heroic-import-epic",
                "heroic-import-gog",
                "heroic-import-amazon",
                "heroic-import-sideload",
                "flatpak-import-launchers",
                "shortcuts-recursive",
                "sgdb",
                "sgdb-prefer",
                "sgdb-animated",
                "thegamesdb",
                "desktop",
                "playtime-tracking",
                "show-news-button",
                "session-wallpaper",
                "session-fita",
                "game-mode-use-gamemode",
                "game-mode-use-mangohud",
                "game-mode-enable-fps-limiter",
                "game-mode-enable-vrr",
                "game-mode-start-library",
                "game-mode-hide-mouse-cursor",
                "recorder-enabled",
                "recorder-cursor",
            }
        )
        self.agrupar_duplicados_switch.connect(
            "notify::active", lambda *_: self._reagrupar()
        )
        self.xcloud_login_button.connect("clicked", self.alternar_xcloud_login)
        self.reler_xcloud_login()
        self.atalho_global_button.connect("clicked", self.alternar_atalho_global)
        self._atalho_ativo = False
        self.atualizar_atalho_global()

        sinks, sources = pipewire_nodes()
        self.setup_device_row(
            self.game_mode_monitor_entry_row,
            "game-mode-monitor",
            drm_connectors(),
        )
        self.setup_device_row(
            self.game_mode_audio_output_entry_row,
            "game-mode-audio-output",
            sinks,
        )
        self.setup_device_row(
            self.game_mode_audio_input_entry_row,
            "game-mode-audio-input",
            sources,
        )
        has_vrr = vrr_supported()
        self.game_mode_enable_vrr_switch.set_visible(has_vrr)
        if not has_vrr:
            shared.schema.set_boolean("game-mode-enable-vrr", False)
        self.game_mode_use_gamemode_switch.set_sensitive(which("gamemoderun") is not None)
        self.game_mode_use_mangohud_switch.set_sensitive(which("mangohud") is not None)
        gamescope_available = which("gamescope") is not None
        self.game_mode_enable_fps_limiter_switch.set_sensitive(gamescope_available)
        self.setup_game_overlay_button_row()

        def set_sgdb_sensitive(widget: Adw.EntryRow) -> None:
            if not widget.get_text():
                shared.schema.set_boolean("sgdb", False)

            self.sgdb_switch.set_sensitive(widget.get_text())

        self.sgdb_key_entry_row.connect("changed", set_sgdb_sensitive)
        set_sgdb_sensitive(self.sgdb_key_entry_row)

        def wallhaven_key_changed(*_args: Any) -> None:
            shared.schema.set_string(
                "wallhaven-key", self.wallhaven_key_entry_row.get_text().strip()
            )

        self._wallhaven_key_changed_id = self.wallhaven_key_entry_row.connect(
            "changed", wallhaven_key_changed
        )
        self.reler_wallhaven()
        self.wallpaper_restore_button.connect("clicked", self.restaurar_parede)
        self.atualizar_parede()
        shared.schema.connect(
            "changed::session-wallpaper-saved", lambda *_: self.atualizar_parede()
        )
        self.setup_recorder_page()
        self.setup_fita_rows()
        self.reler_fitas()
        self.setup_appearance_page()
        self.setup_steam_group()
        # As páginas internas do AdwPreferencesDialog só entram na árvore quando
        # o diálogo é mapeado; alargamos o clamp de cada uma nesse momento.
        self.connect("map", lambda *_: self._alargar_paginas())

    #: Largura útil das páginas de Preferências. O ``AdwPreferencesDialog`` tem
    #: ``content-width: 920``, mas cada ``AdwPreferencesPage`` embute um
    #: ``AdwClamp`` com ``maximum_size = 600`` que limita o conteúdo e não é
    #: exposto ao CSS. Elevamos esse teto aqui; ``AdwClamp`` continua encolhendo
    #: em janelas estreitas (o valor é um teto, não um piso), então o layout
    #: permanece íntegro a partir de 360px.
    LARGURA_PAGINA = 856

    def _alargar_paginas(self) -> None:
        """Aumenta o ``AdwClamp`` estrutural de cada página de Preferências.

        Só toca no clamp da própria página (cadeia
        ``PreferencesPage > ScrolledWindow > Viewport > Clamp``); os clamps de
        conteúdo (``StatusPage``) e da barra superior têm outro pai e ficam
        como estão.
        """
        pilha: list[Gtk.Widget] = [self]
        while pilha:
            widget = pilha.pop()
            filho = widget.get_first_child()
            while filho is not None:
                pilha.append(filho)
                filho = filho.get_next_sibling()
            if not isinstance(widget, Adw.Clamp):
                continue
            viewport = widget.get_parent()
            scrolled = viewport.get_parent() if viewport is not None else None
            pagina = scrolled.get_parent() if scrolled is not None else None
            if not (
                isinstance(viewport, Gtk.Viewport)
                and isinstance(scrolled, Gtk.ScrolledWindow)
                and isinstance(pagina, Adw.PreferencesPage)
            ):
                continue
            try:
                widget.set_maximum_size(self.LARGURA_PAGINA)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.debug("Não foi possível alargar a página", exc_info=True)

    def alternar_xcloud_login(self, *_args: Any) -> None:
        from cartridges import xcloud_login

        if xcloud_login.has_saved_login():
            xcloud_login.clear_saved_login()
            self.reler_xcloud_login()
            return

        def finished(resultado: Any) -> None:
            self.reler_xcloud_login()

        xcloud_login.show_login_dialog(parent=self, on_finished=finished)

    def reler_xcloud_login(self) -> None:
        from cartridges import xcloud_login

        conectado = xcloud_login.has_saved_login()
        self.xcloud_account_row.set_subtitle(
            _("Conectado") if conectado else _("Não conectado")
        )
        self.xcloud_login_button.set_label(_("Sair") if conectado else _("Entrar"))

    def sincronizar_sunshine(self, *_args: Any) -> None:
        import threading

        from cartridges.utils import sunshine

        self.sunshine_sync_all_button.set_sensitive(False)
        custom = shared.schema.get_string("sunshine-apps-path")
        jogos = [game for game in shared.store if sunshine.is_eligible(game)]

        def concluir(resultado: dict) -> bool:
            total = resultado.get("added", 0) + resultado.get("updated", 0)
            self.sunshine_sync_all_button.set_sensitive(True)
            self.add_toast(
                Adw.Toast.new(
                    _("{} jogo(s) sincronizado(s) com o Sunshine").format(total)
                )
            )
            return GLib.SOURCE_REMOVE

        def falhar(mensagem: str) -> bool:
            self.sunshine_sync_all_button.set_sensitive(True)
            self.add_toast(Adw.Toast.new(_("Não foi possível sincronizar")))
            logging.error("Sunshine sync-all failed: %s", mensagem)
            return GLib.SOURCE_REMOVE

        def executar() -> None:
            try:
                resultado = sunshine.sync_library(jogos, custom)
            except Exception as error:  # pylint: disable=broad-exception-caught
                entregar_na_tela(falhar, str(error))
            else:
                entregar_na_tela(concluir, resultado)

        threading.Thread(target=executar, daemon=True).start()

    #: Espera após a última tecla antes de persistir a senha do Sunshine.
    SENHA_SUNSHINE_DEBOUNCE_MS = 750

    def _ao_fechar(self, *_args: Any) -> None:
        """Descarta o debounce pendente da senha e marca o diálogo fechado.

        Sem isso, o timeout dispararia depois do diálogo destruído e gravaria
        um texto velho no cofre.
        """
        if getattr(self, "_senha_sunshine_id", 0):
            try:
                GLib.source_remove(self._senha_sunshine_id)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.debug("Não foi possível cancelar o debounce da senha")
            self._senha_sunshine_id = 0
        self.set_is_open(False)

    def _mostrar_senha_sunshine(self, salva: str) -> bool:
        """Preenche o campo com a senha vinda do cofre (thread principal).

        Só preenche se o campo ainda estiver vazio: o que o usuário já
        digitou enquanto o lookup voava nunca é sobrescrito. O `set_text`
        programático roda sob `_senha_sunshine_aplicando`, o único trecho
        que o handler de "changed" ignora.
        """
        self._senha_sunshine_aplicando = True
        try:
            if salva and not self.sunshine_password_row.get_text():
                self.sunshine_password_row.set_text(salva)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.debug("Diálogo fechado antes da senha chegar do cofre")
        finally:
            self._senha_sunshine_aplicando = False
        return GLib.SOURCE_REMOVE

    def _ao_mudar_senha_sunshine(self, *_args: Any) -> None:
        """Reagenda o save da senha no cofre após a última tecla."""
        if getattr(self, "_senha_sunshine_aplicando", False):
            return
        if self._senha_sunshine_id:
            try:
                GLib.source_remove(self._senha_sunshine_id)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.debug("Não foi possível cancelar o debounce da senha")
            self._senha_sunshine_id = 0
        self._senha_sunshine_id = GLib.timeout_add(
            self.SENHA_SUNSHINE_DEBOUNCE_MS, self._guardar_senha_sunshine
        )

    def _guardar_senha_sunshine(self) -> bool:
        """Persiste a senha atual no cofre, fora da thread GTK.

        O texto é lido aqui (thread principal); o D-Bus do libsecret roda
        num worker que nunca toca em widget. Cada disparo carimba uma
        sequência crescente e o worker só grava se ainda for o mais recente
        (latest-wins); o lock serializa as escritas sem nunca travar a GTK,
        que só incrementa o contador.
        """
        self._senha_sunshine_id = 0
        senha = self.sunshine_password_row.get_text()
        self._senha_sunshine_seq += 1
        seq = self._senha_sunshine_seq

        def executar() -> None:
            try:
                from cartridges.utils import sunshine_credenciais  # noqa: PLC0415
            except Exception:  # pylint: disable=broad-exception-caught
                logging.debug("Save da senha do Sunshine falhou", exc_info=True)
                return
            with self._senha_sunshine_lock:
                if seq != self._senha_sunshine_seq:
                    return
                try:
                    sunshine_credenciais.salvar_senha(senha)
                except Exception:  # pylint: disable=broad-exception-caught
                    logging.debug("Save da senha do Sunshine falhou", exc_info=True)

        threading.Thread(target=executar, daemon=True).start()
        return GLib.SOURCE_REMOVE

    def _conexao_sunshine(self) -> Any:
        from cartridges.utils import sunshine_api

        try:
            porta = int(self.sunshine_port_row.get_text().strip())
        except ValueError:
            porta = 0
        return sunshine_api.SunshineConnection(
            host=self.sunshine_host_row.get_text().strip() or "localhost",
            port=porta,
            username=self.sunshine_username_row.get_text().strip(),
            password=self.sunshine_password_row.get_text(),
        )

    def _limpar_linhas_sunshine(self) -> None:
        for linha in self._linhas_sunshine:
            parent = linha.get_parent()
            if parent is not None:
                parent.remove(linha)
        self._linhas_sunshine = []

    def _confirmar(
        self, titulo: str, corpo: str, rotulo: str, ao_confirmar: Any
    ) -> None:
        dialog = Adw.AlertDialog.new(titulo, corpo)
        dialog.add_response("cancel", _("Cancelar"))
        dialog.add_response("ok", rotulo)
        dialog.set_default_response("ok")

        def resposta(_dialog: Any, codigo: str) -> None:
            if codigo == "ok":
                ao_confirmar()

        dialog.connect("response", resposta)
        dialog.present(self)

    def testar_sunshine(self, *_args: Any) -> None:
        import threading

        from cartridges.utils import sunshine_api

        conexao = self._conexao_sunshine()
        self.sunshine_test_button.set_sensitive(False)
        self.sunshine_status_row.set_subtitle(_("Verificando…"))

        def concluir(resultado: dict) -> bool:
            self.sunshine_test_button.set_sensitive(True)
            erro = resultado.get("error")
            if erro is not None:
                self.sunshine_status_row.set_subtitle(_("Não foi possível conectar"))
                self.add_toast(Adw.Toast.new(str(erro)))
                return GLib.SOURCE_REMOVE
            status = resultado["status"]
            versao = status.version or _("desconhecida")
            total = len(status.app_names)
            self.sunshine_status_row.set_subtitle(
                _("Sunshine {} · {} app(s)").format(versao, total)
            )
            self._limpar_linhas_sunshine()
            self._preencher_config_sunshine(resultado["config"])
            self._listar_apps_sunshine(conexao, status.app_names)
            self._listar_pareamentos(conexao, resultado["pairings"])
            self._listar_clientes(conexao, resultado["clients"])
            return GLib.SOURCE_REMOVE

        def executar() -> None:
            try:
                status = sunshine_api.probe(conexao)
                config = sunshine_api.fetch_config(conexao)
            except Exception as error:  # pylint: disable=broad-exception-caught
                entregar_na_tela(concluir, {"error": error, "status": None})
                return
            try:
                pareamentos = sunshine_api.get_pending_pairings(conexao)
            except Exception:  # pylint: disable=broad-exception-caught
                pareamentos = []
            try:
                clientes = sunshine_api.get_clients(conexao)
            except Exception:  # pylint: disable=broad-exception-caught
                clientes = []
            entregar_na_tela(
                concluir,
                {
                    "error": None,
                    "status": status,
                    "config": config,
                    "pairings": pareamentos,
                    "clients": clientes,
                },
            )

        threading.Thread(target=executar, daemon=True).start()

    def _preencher_config_sunshine(self, config: dict) -> None:
        self.sunshine_max_bitrate_row.set_text(str(config.get("max_bitrate", "")))
        self.sunshine_min_fps_row.set_text(str(config.get("minimum_fps_target", "")))
        self.sunshine_upnp_switch.set_active(config.get("upnp") == "enabled")
        self.sunshine_origin_row.set_text(str(config.get("origin_web_ui_allowed", "")))
        self.sunshine_encoder_row.set_text(str(config.get("encoder", "")))

    def _listar_apps_sunshine(self, conexao: Any, nomes: list) -> None:
        for nome in sorted(nomes, key=str.casefold):
            linha = Adw.ActionRow(title=nome)
            botao = Gtk.Button(label=_("Remover"), valign=Gtk.Align.CENTER)
            botao.add_css_class("destructive-action")
            botao.connect("clicked", self._remover_app_sunshine, conexao, nome)
            linha.add_suffix(botao)
            linha.set_activatable_widget(botao)
            self.sunshine_apps_group.add(linha)
            self._linhas_sunshine.append(linha)
        if not nomes:
            linha = Adw.ActionRow(title=_("Nenhum app cadastrado"))
            self.sunshine_apps_group.add(linha)
            self._linhas_sunshine.append(linha)

    def _remover_app_sunshine(
        self, _botao: Any, conexao: Any, nome: str
    ) -> None:
        import threading

        from cartridges.utils import sunshine_api

        def executar() -> None:
            try:
                sunshine_api.delete_app(conexao, nome)
            except Exception as error:  # pylint: disable=broad-exception-caught
                entregar_na_tela(
                    lambda: self.add_toast(Adw.Toast.new(str(error)))
                    or GLib.SOURCE_REMOVE
                )
            else:
                entregar_na_tela(self.testar_sunshine)

        self._confirmar(
            _("Remover do Sunshine?"),
            _("{} deixará de aparecer no Moonlight.").format(nome),
            _("Remover"),
            lambda: threading.Thread(target=executar, daemon=True).start(),
        )

    def exportar_sunshine_api(self, *_args: Any) -> None:
        import threading

        from cartridges.utils import sunshine, sunshine_api

        conexao = self._conexao_sunshine()
        jogos = [game for game in shared.store if sunshine.is_eligible(game)]
        self.sunshine_api_sync_button.set_sensitive(False)

        def concluir(resultado: dict) -> bool:
            self.sunshine_api_sync_button.set_sensitive(True)
            if (erro := resultado.get("error")) is not None:
                self.add_toast(Adw.Toast.new(str(erro)))
            else:
                self.add_toast(
                    Adw.Toast.new(
                        _("{} jogo(s) exportado(s) via API").format(
                            resultado.get("added", 0)
                        )
                    )
                )
                self.testar_sunshine()
            return GLib.SOURCE_REMOVE

        def executar() -> None:
            adicionados = 0
            try:
                existentes = {
                    app.get("name")
                    for app in sunshine_api.fetch_apps(conexao)
                    if isinstance(app, dict)
                }
            except Exception as error:  # pylint: disable=broad-exception-caught
                entregar_na_tela(concluir, {"error": error})
                return
            for jogo in jogos:
                try:
                    capa = self._capa_sunshine(conexao, jogo)
                    entrada = sunshine.build_app_entry(jogo, capa)
                    if entrada["name"] in existentes:
                        continue
                    sunshine_api.create_app(conexao, entrada)
                    adicionados += 1
                except Exception as error:  # pylint: disable=broad-exception-caught
                    logging.warning("API export skipped %s: %s", jogo.game_id, error)
            entregar_na_tela(concluir, {"added": adicionados})

        threading.Thread(target=executar, daemon=True).start()

    @staticmethod
    def _capa_sunshine(conexao: Any, jogo: Any) -> Any:
        from pathlib import Path

        from cartridges.utils import sunshine_api

        obter = getattr(jogo, "get_cover_path", None)
        if not callable(obter):
            return None
        try:
            capa = obter()
        except Exception:  # pylint: disable=broad-exception-caught
            return None
        if capa is None:
            return None
        try:
            dados = Path(str(capa)).read_bytes()
        except OSError:
            return None
        if not dados or len(dados) > 5 * 1024 * 1024:
            return None
        try:
            return sunshine_api.upload_cover(
                conexao, f"jolven-{jogo.game_id}", dados
            )
        except Exception:  # pylint: disable=broad-exception-caught
            logging.debug("Cover upload skipped for %s", jogo.game_id)
            return None

    def aplicar_sunshine_host(self, *_args: Any) -> None:
        import threading

        from cartridges.utils import sunshine_api

        conexao = self._conexao_sunshine()
        try:
            bitrate = int(self.sunshine_max_bitrate_row.get_text().strip() or "0")
            fps = int(self.sunshine_min_fps_row.get_text().strip() or "0")
        except ValueError:
            self.add_toast(Adw.Toast.new(_("Bitrate e FPS precisam ser números")))
            return
        if bitrate < 0 or fps < 0:
            self.add_toast(Adw.Toast.new(_("Bitrate e FPS precisam ser números")))
            return
        origem = self.sunshine_origin_row.get_text().strip()
        if origem and origem not in ("pc", "lan", "wan"):
            self.add_toast(Adw.Toast.new(_("Origem válida: pc, lan ou wan")))
            return
        mudancas = {
            "max_bitrate": str(bitrate),
            "minimum_fps_target": str(fps),
            "upnp": "enabled" if self.sunshine_upnp_switch.get_active() else "disabled",
        }
        if origem:
            mudancas["origin_web_ui_allowed"] = origem
        codificador = self.sunshine_encoder_row.get_text().strip()
        if codificador:
            mudancas["encoder"] = codificador

        def executar() -> None:
            try:
                sunshine_api.update_config(conexao, mudancas)
            except Exception as error:  # pylint: disable=broad-exception-caught
                entregar_na_tela(
                    lambda: self.add_toast(Adw.Toast.new(str(error)))
                    or GLib.SOURCE_REMOVE
                )
            else:
                entregar_na_tela(self._oferecer_reinicio)

        def aplicar() -> None:
            threading.Thread(target=executar, daemon=True).start()

        self._confirmar(
            _("Aplicar ajustes do host?"),
            _("A config inteira do Sunshine será regravada."),
            _("Aplicar"),
            aplicar,
        )

    def _oferecer_reinicio(self) -> bool:
        import threading

        from cartridges.utils import sunshine_api

        conexao = self._conexao_sunshine()

        def executar() -> None:
            try:
                sunshine_api.restart(conexao)
            except Exception as error:  # pylint: disable=broad-exception-caught
                entregar_na_tela(
                    lambda: self.add_toast(Adw.Toast.new(str(error)))
                    or GLib.SOURCE_REMOVE
                )
            else:
                entregar_na_tela(
                    lambda: self.add_toast(
                        Adw.Toast.new(_("Ajustes aplicados. Reiniciando…"))
                    )
                    or GLib.SOURCE_REMOVE
                )

        self._confirmar(
            _("Reiniciar o Sunshine?"),
            _("Os ajustes do host só valem após reiniciar."),
            _("Reiniciar"),
            lambda: threading.Thread(target=executar, daemon=True).start(),
        )
        return GLib.SOURCE_REMOVE

    def _listar_pareamentos(self, conexao: Any, pareamentos: list) -> None:
        for item in sorted(
            pareamentos, key=lambda p: str(p.get("name", "")).casefold()
        ):
            nome = str(item.get("name") or item.get("address") or _("Sem nome"))
            linha = Adw.ActionRow(
                title=nome, subtitle=str(item.get("address", ""))
            )
            aprovar = Gtk.Button(label=_("Aprovar"), valign=Gtk.Align.CENTER)
            aprovar.add_css_class("suggested-action")
            aprovar.connect(
                "clicked", self._aprovar_pareamento, conexao, item
            )
            recusar = Gtk.Button(label=_("Recusar"), valign=Gtk.Align.CENTER)
            recusar.connect(
                "clicked", self._recusar_pareamento, conexao, item
            )
            linha.add_suffix(aprovar)
            linha.add_suffix(recusar)
            self.sunshine_pairings_group.add(linha)
            self._linhas_sunshine.append(linha)
        if not pareamentos:
            linha = Adw.ActionRow(title=_("Nenhum pedido pendente"))
            self.sunshine_pairings_group.add(linha)
            self._linhas_sunshine.append(linha)

    def _aprovar_pareamento(
        self, _botao: Any, conexao: Any, item: dict
    ) -> None:
        import threading

        from cartridges.utils import sunshine_api

        entrada = Gtk.Entry(
            placeholder_text="PIN", max_length=32,
            input_purpose=Gtk.InputPurpose.PIN,
        )
        dialog = Adw.AlertDialog.new(
            _("Aprovar pareamento?"),
            _("Digite o PIN mostrado no Moonlight."),
        )
        dialog.add_response("cancel", _("Cancelar"))
        dialog.add_response("ok", _("Aprovar"))
        dialog.set_default_response("ok")
        dialog.set_extra_child(entrada)

        def resposta(_dialog: Any, codigo: str) -> None:
            if codigo != "ok":
                return

            def executar() -> None:
                try:
                    sunshine_api.approve_pairing(
                        conexao,
                        str(item.get("id", "")),
                        entrada.get_text(),
                        str(item.get("name", "")),
                    )
                except Exception as error:  # pylint: disable=broad-exception-caught
                    entregar_na_tela(
                        lambda: self.add_toast(Adw.Toast.new(str(error)))
                        or GLib.SOURCE_REMOVE
                    )
                else:
                    entregar_na_tela(self.testar_sunshine)

            threading.Thread(target=executar, daemon=True).start()

        dialog.connect("response", resposta)
        dialog.present(self)

    def _recusar_pareamento(
        self, _botao: Any, conexao: Any, item: dict
    ) -> None:
        import threading

        from cartridges.utils import sunshine_api

        def executar() -> None:
            try:
                sunshine_api.cancel_pairing(conexao, str(item.get("id", "")))
            except Exception as error:  # pylint: disable=broad-exception-caught
                entregar_na_tela(
                    lambda: self.add_toast(Adw.Toast.new(str(error)))
                    or GLib.SOURCE_REMOVE
                )
            else:
                entregar_na_tela(self.testar_sunshine)

        threading.Thread(target=executar, daemon=True).start()

    def _listar_clientes(self, conexao: Any, clientes: list) -> None:
        for item in clientes:
            nome = str(
                item.get("name") or item.get("uuid") or _("Sem nome")
            )
            linha = Adw.ActionRow(title=nome)
            botao = Gtk.Button(label=_("Remover"), valign=Gtk.Align.CENTER)
            botao.add_css_class("destructive-action")
            botao.connect(
                "clicked", self._remover_cliente, conexao, item
            )
            linha.add_suffix(botao)
            linha.set_activatable_widget(botao)
            self.sunshine_clients_group.add(linha)
            self._linhas_sunshine.append(linha)
        if not clientes:
            linha = Adw.ActionRow(title=_("Nenhum cliente pareado"))
            self.sunshine_clients_group.add(linha)
            self._linhas_sunshine.append(linha)

    def _remover_cliente(self, _botao: Any, conexao: Any, item: dict) -> None:
        import threading

        from cartridges.utils import sunshine_api

        def executar() -> None:
            try:
                sunshine_api.unpair_client(conexao, str(item.get("uuid", "")))
            except Exception as error:  # pylint: disable=broad-exception-caught
                entregar_na_tela(
                    lambda: self.add_toast(Adw.Toast.new(str(error)))
                    or GLib.SOURCE_REMOVE
                )
            else:
                entregar_na_tela(self.testar_sunshine)

        self._confirmar(
            _("Desemparelhar cliente?"),
            str(item.get("name") or item.get("uuid") or ""),
            _("Remover"),
            lambda: threading.Thread(target=executar, daemon=True).start(),
        )

    def desemparelhar_todos(self, *_args: Any) -> None:
        import threading

        from cartridges.utils import sunshine_api

        conexao = self._conexao_sunshine()

        def executar() -> None:
            try:
                sunshine_api.unpair_all_clients(conexao)
            except Exception as error:  # pylint: disable=broad-exception-caught
                entregar_na_tela(
                    lambda: self.add_toast(Adw.Toast.new(str(error)))
                    or GLib.SOURCE_REMOVE
                )
            else:
                entregar_na_tela(self.testar_sunshine)

        self._confirmar(
            _("Desemparelhar todos?"),
            _("Todos os Moonlights precisarão parear de novo."),
            _("Remover todos"),
            lambda: threading.Thread(target=executar, daemon=True).start(),
        )

    def abrir_sunshine_web(self, *_args: Any) -> None:
        from cartridges.utils.open_uri import open_uri

        try:
            porta = int(self.sunshine_port_row.get_text().strip())
        except ValueError:
            porta = 0
        if not 1 <= porta <= 65535:
            self.add_toast(Adw.Toast.new(_("Porta inválida")))
            return
        host = self.sunshine_host_row.get_text().strip() or "localhost"
        open_uri(f"https://{host}:{porta}/", parent=self)

    def iniciar_sunshine(self, *_args: Any) -> None:
        from cartridges.utils import sunshine

        try:
            launched = sunshine.start_server()
        except Exception as error:  # pylint: disable=broad-exception-caught
            self.add_toast(Adw.Toast.new(str(error)))
            return
        if not launched:
            self.add_toast(Adw.Toast.new(_("O Sunshine já está rodando")))
            return
        self.add_toast(Adw.Toast.new(_("Iniciando o Sunshine…")))
        GLib.timeout_add_seconds(4, self._retestar_sunshine)

    def _retestar_sunshine(self) -> bool:
        self.testar_sunshine()
        return GLib.SOURCE_REMOVE

    def atualizar_atalho_global(self) -> None:
        try:
            estado = global_shortcut.get_status()
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Não foi possível ler o atalho global")
            estado = global_shortcut.ShortcutStatus(backend=None, registered=False)
        self._atalho_ativo = estado.registered
        botao = self.atalho_global_button
        if estado.backend is None:
            self.atalho_global_row.set_subtitle(
                _("Sem suporte neste ambiente. No GNOME: Configurações > "
                  "Teclado > Atalhos personalizados.")
            )
            botao.set_label(_("Ativar"))
            botao.set_sensitive(False)
            return
        ambiente = "GNOME" if estado.backend == "gnome" else "KDE"
        botao.set_sensitive(True)
        if estado.registered:
            self.atalho_global_row.set_subtitle(
                _("Ativo no {} — Super+G abre o Jolven de qualquer lugar").format(
                    ambiente
                )
            )
            botao.set_label(_("Remover"))
        elif estado.conflict:
            self.atalho_global_row.set_subtitle(
                _("Super+G está com {} — ativar move para o Jolven ({})").format(
                    estado.conflict, ambiente
                )
            )
            botao.set_label(_("Ativar"))
        else:
            self.atalho_global_row.set_subtitle(
                _("Abre o Jolven de qualquer lugar ({})").format(ambiente)
            )
            botao.set_label(_("Ativar"))

    def alternar_atalho_global(self, *_args: Any) -> None:
        alvo = not self._atalho_ativo
        self.atalho_global_button.set_sensitive(False)
        self.atalho_global_row.set_subtitle(_("Aplicando…"))

        def trabalho() -> None:
            try:
                global_shortcut.set_enabled(alvo)
            except global_shortcut.ShortcutError as erro:
                entregar_na_tela(self._atalho_global_pronto, False, str(erro))
            except Exception as erro:  # pylint: disable=broad-exception-caught
                logging.exception("Não foi possível alternar o atalho global")
                entregar_na_tela(self._atalho_global_pronto, False, str(erro))
            else:
                entregar_na_tela(self._atalho_global_pronto, True, "")

        threading.Thread(target=trabalho, daemon=True).start()

    def _atalho_global_pronto(self, ok: bool, mensagem: str) -> bool:
        if ok:
            self.add_toast(
                Adw.Toast.new(
                    _("Atalho Super+G ativo")
                    if self._atalho_ativo is False
                    else _("Atalho Super+G removido")
                )
            )
        else:
            create_dialog(
                self,
                _("Não foi possível configurar o atalho"),
                mensagem
                or _("Verifique as permissões do ambiente e tente novamente."),
            )
        self.atualizar_atalho_global()
        return False

    def reler_wallhaven(self) -> None:
        self.wallhaven_key_entry_row.handler_block(self._wallhaven_key_changed_id)
        try:
            self.wallhaven_key_entry_row.set_text(
                shared.schema.get_string("wallhaven-key")
            )
        finally:
            self.wallhaven_key_entry_row.handler_unblock(
                self._wallhaven_key_changed_id
            )

    def atualizar_parede(self) -> None:
        tem_salvo = bool(shared.schema.get_string("session-wallpaper-saved"))
        self.wallpaper_restore_row.set_subtitle(
            _("Há um papel de parede de sessão a devolver")
            if tem_salvo
            else _("Nenhum papel de parede de sessão a devolver")
        )
        self.wallpaper_restore_row.set_sensitive(tem_salvo)

    def restaurar_parede(self, *_args: Any) -> None:
        from cartridges.utils import session_wallpaper

        session_wallpaper.restaurar()
        self.atualizar_parede()
        if shared.schema.get_string("session-wallpaper-saved"):
            self.add_toast(
                Adw.Toast.new(_("Não foi possível devolver o papel de parede"))
            )
        else:
            self.add_toast(Adw.Toast.new(_("Papel de parede restaurado")))

    def setup_fita_rows(self) -> None:
        self._fita_brilho_changed_id = self.fita_brilho_row.connect(
            "notify::value", self.mudar_brilho_padrao
        )
        self.fita_brilho_individual_button.connect(
            "clicked", self.brilho_por_dispositivo
        )
        self.fita_configurar_button.connect("clicked", self.configurar_fitas)
        self.fita_testar_button.connect("clicked", self.testar_fitas)

        self.fita_cor_app_amostra.set_draw_func(self.desenhar_cor_app)
        self._fita_cor_app_changed_id = self.fita_cor_app_seletor.connect(
            "notify::rgba", self.mudar_cor_app
        )
        self.fita_cor_app_reset.connect("clicked", self.voltar_ao_roxo)
        self.session_fita_switch.connect("notify::active", self.arrancar_fitas)

    def reler_fitas(self) -> None:
        self.fita_brilho_row.handler_block(self._fita_brilho_changed_id)
        try:
            self.fita_brilho_row.set_value(
                session_fita.por_cento(shared.schema.get_int("fita-brilho-padrao"))
            )
        finally:
            self.fita_brilho_row.handler_unblock(self._fita_brilho_changed_id)
        self.atualizar_fitas()

        self.fita_cor_app_seletor.handler_block(self._fita_cor_app_changed_id)
        try:
            self.fita_cor_app_seletor.set_property(
                "rgba", session_fita.cor_para_rgba(session_fita.cor_do_app())
            )
        finally:
            self.fita_cor_app_seletor.handler_unblock(self._fita_cor_app_changed_id)
        self.fita_cor_app_amostra.queue_draw()
        self.fita_cor_app_reset.set_visible(
            session_fita.tom_do_app() != session_fita.ROXO_DO_APP
        )

    def atualizar_fitas(self) -> None:
        configuradas = session_fita.fitas()
        self.session_fita_switch.set_sensitive(bool(configuradas))
        if configuradas:
            n = len(configuradas)
            self.session_fita_switch.set_subtitle(
                f"{n} dispositivo configurado"
                if n == 1
                else f"{n} dispositivos configurados"
            )
            return

        shared.schema.set_boolean("session-fita", False)
        self.session_fita_switch.set_subtitle(_("Nenhum dispositivo configurado"))

    def arrancar_fitas(self, row: Adw.SwitchRow, *_args: Any) -> None:
        if row.get_active():
            shared.schema.set_boolean("session-fita", True)
            session_fita.reacender()

    def mudar_brilho_padrao(self, row: Adw.SpinRow, *_args: Any) -> None:
        brilho = session_fita.de_por_cento(row.get_value())
        shared.schema.set_int("fita-brilho-padrao", brilho)
        session_fita.previa(session_fita.Cor(*session_fita.tom_do_app(), brilho))

    def brilho_por_dispositivo(self, *_args: Any) -> None:
        configuradas = session_fita.fitas()
        dialogo = Adw.Dialog(
            title=_("Brilho máximo por dispositivo"), content_width=420
        )
        cabecalho = Adw.HeaderBar(
            show_start_title_buttons=False, show_end_title_buttons=False
        )
        cancelar = Gtk.Button(label=_("Cancelar"))
        salvar = Gtk.Button(label=_("Salvar"), css_classes=["suggested-action"])
        cabecalho.pack_start(cancelar)
        cabecalho.pack_end(salvar)

        grupo = Adw.PreferencesGroup(
            description=_(
                "Brilho máximo de cada dispositivo, em porcentagem. O brilho "
                "definido nas Preferências e em cada jogo é aplicado "
                "proporcionalmente sobre estes valores."
            )
        )
        linhas: dict[str, Adw.SpinRow] = {}

        def mostrar(*_args: Any) -> None:
            session_fita.previa(
                session_fita.Cor(*session_fita.tom_do_app(), session_fita.BRILHO_CHEIO),
                {id_: round(linha.get_value()) for id_, linha in linhas.items()},
            )

        for fita in configuradas:
            linha = Adw.SpinRow.new_with_range(1, 100, 1)
            linha.set_title(fita.nome)
            linha.set_value(fita.brilho)
            linha.connect("notify::value", mostrar)
            grupo.add(linha)
            linhas[fita.id] = linha

        pagina = Adw.PreferencesPage()
        pagina.add(grupo)
        vista = Adw.ToolbarView(content=pagina)
        vista.add_top_bar(cabecalho)
        dialogo.set_child(vista)

        def gravar(*_args: Any) -> None:
            session_fita.gravar_fitas(
                [
                    fita._replace(brilho=round(linhas[fita.id].get_value()))
                    if fita.id in linhas
                    else fita
                    for fita in session_fita.fitas()
                ]
            )
            dialogo.close()

        cancelar.connect("clicked", lambda *_: dialogo.close())
        salvar.connect("clicked", gravar)
        dialogo.connect("closed", lambda *_: session_fita.previa(session_fita.cor_do_app()))
        dialogo.present(self)
        mostrar()

    def desenhar_cor_app(
        self, _area: Any, contexto: Any, largura: int, altura: int
    ) -> None:
        cor = self.fita_cor_app_seletor.props.rgba
        contexto.set_source_rgb(cor.red, cor.green, cor.blue)
        raio = min(largura, altura) / 2
        contexto.arc(largura / 2, altura / 2, raio, 0, 2 * math.pi)
        contexto.fill()

    def mudar_cor_app(self, seletor: Gtk.ColorChooserWidget, *_args: Any) -> None:
        cor = session_fita.rgba_para_cor(
            seletor.props.rgba, session_fita.brilho_padrao()
        )
        session_fita.salvar_tom_do_app(cor.matiz, cor.saturacao)
        self.fita_cor_app_amostra.queue_draw()
        self.fita_cor_app_reset.set_visible(
            session_fita.tom_do_app() != session_fita.ROXO_DO_APP
        )
        session_fita.previa(session_fita.cor_do_app())

    def voltar_ao_roxo(self, *_args: Any) -> None:
        self.fita_cor_app_seletor.set_property(
            "rgba",
            session_fita.cor_para_rgba(
                session_fita.Cor(*session_fita.ROXO_DO_APP, session_fita.brilho_padrao())
            ),
        )
        session_fita.redefinir_tom_do_app()
        self.fita_cor_app_reset.set_visible(False)

    def configurar_fitas(self, *_args: Any) -> None:
        from cartridges.fita_wizard import FitaWizard  # noqa: PLC0415

        assistente = FitaWizard()
        assistente.connect("closed", lambda *_: self.fitas_configuradas())
        assistente.present(self)

    def fitas_configuradas(self) -> None:
        self.atualizar_fitas()
        if session_fita.ligada():
            session_fita.reacender()

    def testar_fitas(self, *_args: Any) -> None:
        if self._teste_em_curso is not None:
            self._teste_em_curso.set()
            return

        parar = threading.Event()
        self._teste_em_curso = parar
        session_fita.retomar()

        def tarefa() -> None:
            cor = session_fita.cor_do_app()
            mudas = []
            for fita in session_fita.fitas():
                if parar.is_set():
                    break
                if not session_fita.aplicar(
                    fita, True, session_fita.hsv_hex(session_fita.na_fita(cor, fita))
                ):
                    mudas.append(fita.nome)
            entregar_na_tela(pronto, mudas, parar.is_set())

        def pronto(mudas: list[str], cancelado: bool) -> bool:
            self._teste_em_curso = None
            if not self.__class__.is_open:
                return False
            self.fita_testar_button.set_icon_name("media-playback-start-symbolic")
            if cancelado:
                self.fita_testar_row.set_subtitle(_("Teste interrompido"))
            else:
                self.fita_testar_row.set_subtitle(
                    _(
                        "Sem resposta: {}. Se o dispositivo estiver ligado, o "
                        "endereço dele na rede pode ter mudado; configure a "
                        "iluminação inteligente novamente."
                    ).format(", ".join(mudas))
                    if mudas
                    else _("Teste concluído")
                )
            return False

        threading.Thread(target=tarefa, daemon=True).start()

    def set_is_open(self, is_open: bool) -> None:
        self.__class__.is_open = is_open

    @staticmethod
    def _reagrupar(*_args: Any) -> None:
        for game in shared.store:
            game.update()

    def get_switch(self, setting: str) -> Any:
        return getattr(self, f'{setting.replace("-", "_")}_switch')

    def bind_switches(self, settings: set[str]) -> None:
        for setting in settings:
            shared.schema.bind(
                setting,
                self.get_switch(setting),
                "active",
                Gio.SettingsBindFlags.DEFAULT,
            )

    @staticmethod
    def setup_device_row(row: Adw.ComboRow, setting: str, values: list[str]) -> None:
        choices = [_('System default'), *values]
        row.set_model(Gtk.StringList.new(choices))
        saved = shared.schema.get_string(setting)
        if saved and saved not in values:
            shared.schema.set_string(setting, "")
            saved = ""
        row.set_selected(choices.index(saved) if saved in choices else 0)
        row.set_visible(len(values) > 1)

        def selected_changed(widget: Adw.ComboRow, *_args: Any) -> None:
            selected = widget.get_selected()
            shared.schema.set_string(
                setting, values[selected - 1] if 0 < selected <= len(values) else ""
            )

        row.connect("notify::selected", selected_changed)

    def setup_app_icon_row(self) -> None:
        """Seletor do ícone do aplicativo (oficial + alternativas)."""
        from cartridges.utils import app_icon  # noqa: PLC0415

        labels = {
            "jolven-dpad": _("Jolven D-pad (padrão)"),
            "jolven-portal": _("Jolven Portal"),
        }
        self.app_icon_row.set_model(Gtk.StringList.new(list(labels.values())))
        saved = shared.schema.get_string("app-icon")
        if saved not in app_icon.CHOICES:
            shared.schema.set_string("app-icon", app_icon.DEFAULT)
            saved = app_icon.DEFAULT
        self.app_icon_row.set_selected(app_icon.CHOICES.index(saved))

        def selected_changed(widget: Adw.ComboRow, *_args: Any) -> None:
            choice = app_icon.CHOICES[widget.get_selected()]
            shared.schema.set_string("app-icon", choice)
            app_icon.apply(choice)
            self.add_toast(
                Adw.Toast.new(
                    _("Ícone atualizado. Saia e entre de novo se o menu não mudar.")
                )
            )

        self.app_icon_row.connect("notify::selected", selected_changed)

    # ── Aparência: tema do aplicativo ─────────────────────────────────────

    def setup_appearance_page(self) -> None:
        """Prepara a galeria de temas, o modo, o destaque e os brilhos."""
        self._catalogo_temas = _CatalogoTemas()
        self._montar_galeria()
        self._ligar_modo()
        self._ligar_destaque()
        self.tema_glows_switch.connect("notify::active", self._alternar_glows)
        self.tema_restaurar_row.connect("activated", self.restaurar_aparencia)

        self._ligar_tema_manager()

        shared.schema.connect("changed::theme-slug", lambda *_: self._refletir_tema())
        shared.schema.connect("changed::theme-mode", lambda *_: self._refletir_modo())
        shared.schema.connect(
            "changed::theme-accent-custom", lambda *_: self._refletir_destaque()
        )
        try:
            Adw.StyleManager.get_default().connect(
                "notify::dark", lambda *_: self._atualizar_disponibilidade_temas()
            )
        except Exception:  # pylint: disable=broad-exception-caught
            logging.debug("StyleManager indisponível para acompanhar o modo")

        self.appearance_page.connect("map", self._focar_galeria)
        self._refletir_tema()
        self._refletir_modo()
        self._refletir_destaque()

    # -- ThemeManager -----------------------------------------------------

    def _ligar_tema_manager(self) -> None:
        """Liga o ThemeManager ao schema uma única vez, se ele existir."""
        try:
            from cartridges.themes.manager import ThemeManager  # noqa: PLC0415

            self._manager_tema = ThemeManager.instance()
            self._manager_tema.bind_to_schema(shared.schema)
        except Exception:  # pylint: disable=broad-exception-caught
            self._manager_tema = None
            logging.warning("ThemeManager indisponível; a prévia fica no schema")

    def _aplicar_tema(self, slug: str) -> None:
        """Aplica o tema na hora, sem esperar o debounce do schema."""
        manager = self._manager_tema
        funcao = getattr(manager, "set_palette", None) if manager else None
        if not callable(funcao):
            return
        try:
            funcao(slug)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Falha ao aplicar o tema %s", slug)

    def _aplicar_modo(self, modo: str) -> None:
        manager = self._manager_tema
        funcao = getattr(manager, "set_mode", None) if manager else None
        if not callable(funcao):
            return
        try:
            funcao(modo)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.debug("set_mode indisponível", exc_info=True)

    def _aplicar_glows(self) -> None:
        manager = self._manager_tema
        funcao = getattr(manager, "set_glows", None) if manager else None
        if not callable(funcao):
            return
        try:
            funcao(self._glows_ativos())
        except Exception:  # pylint: disable=broad-exception-caught
            logging.debug("set_glows indisponível", exc_info=True)

    def _aplicar_destaque(self) -> None:
        """Repassa a cor personalizada ao gerenciador, quando ele aceitar."""
        manager = self._manager_tema
        funcao = None
        for nome in ("set_acento_custom", "set_accent"):
            candidato = getattr(manager, nome, None) if manager else None
            if callable(candidato):
                funcao = candidato
                break
        if funcao is None:
            return
        try:
            funcao(shared.schema.get_string("theme-accent-custom"))
        except Exception:  # pylint: disable=broad-exception-caught
            logging.debug("alteração do destaque indisponível", exc_info=True)

    # -- galeria ----------------------------------------------------------

    def _montar_galeria(self) -> None:
        """Preenche a galeria a partir do catálogo, com estados de erro."""
        catalogo = self._catalogo_temas
        self.temas_flowbox.remove_all()
        if catalogo is None or not catalogo.disponivel:
            self.tema_galeria_stack.set_visible_child(self.tema_galeria_erro)
            self.tema_selecionado_row.set_subtitle(self._slug_atual())
            return

        for slug in catalogo.slugs:
            self.temas_flowbox.append(self._criar_miniatura(slug))

        self.temas_flowbox.connect("child-activated", self._escolher_tema)
        self.tema_galeria_stack.set_visible_child(self.tema_galeria_scroll)

    def _criar_miniatura(self, slug: str) -> Gtk.FlowBoxChild:
        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for margem in ("set_margin_top", "set_margin_bottom"):
            getattr(caixa, margem)(6)
        for margem in ("set_margin_start", "set_margin_end"):
            getattr(caixa, margem)(8)
        caixa.append(self._figura_do_tema(slug))

        rotulo = Gtk.Label(label=self._nome_do_tema(slug), wrap=True, max_width_chars=20)
        rotulo.set_justify(Gtk.Justification.CENTER)
        caixa.append(rotulo)

        filho = Gtk.FlowBoxChild(child=caixa)
        filho.add_css_class("card")
        filho.set_size_request(200, -1)
        filho.slug = slug  # type: ignore[attr-defined]
        return filho

    def _figura_do_tema(self, slug: str) -> Gtk.Widget:
        """Miniatura do tema; usa o recurso e recua para um desenho local."""
        try:
            textura = Gdk.Texture.new_from_resource(
                f"{shared.PREFIX}/themes/previews/{slug}.svg"
            )
        except Exception:  # pylint: disable=broad-exception-caught
            textura = None
        if textura is not None:
            figura = Gtk.Picture.new_for_paintable(textura)
            figura.set_content_fit(Gtk.ContentFit.CONTAIN)
            figura.set_can_shrink(True)
            figura.set_size_request(188, 118)
            figura.set_halign(Gtk.Align.CENTER)
            return figura

        fundo, destaque = (
            self._catalogo_temas.cores(slug)
            if self._catalogo_temas is not None
            else (None, None)
        )
        area = Gtk.DrawingArea()
        area.set_content_width(188)
        area.set_content_height(118)
        area.set_halign(Gtk.Align.CENTER)
        area.set_draw_func(
            self._desenhar_miniatura,
            fundo or "#1e1e2e",
            destaque or DESTAQUE_PADRAO,
        )
        return area

    @staticmethod
    def _desenhar_miniatura(
        _area: Gtk.DrawingArea,
        contexto: Any,
        largura: int,
        altura: int,
        fundo: str,
        destaque: str,
    ) -> None:
        """Desenho de reserva: janela, barra superior e botão de destaque."""
        cor_fundo = _rgba_do_hex(fundo)
        cor_destaque = _rgba_do_hex(destaque)
        contexto.set_source_rgb(cor_fundo.red, cor_fundo.green, cor_fundo.blue)
        contexto.rectangle(0, 0, largura, altura)
        contexto.fill()
        contexto.set_source_rgba(
            cor_destaque.red, cor_destaque.green, cor_destaque.blue, 0.9
        )
        contexto.rectangle(0, 0, largura, max(6, altura * 0.14))
        contexto.fill()
        contexto.rectangle(6, altura - 16, max(18, largura * 0.3), 10)
        contexto.fill()

    def _filhos_da_galeria(self) -> list[Gtk.FlowBoxChild]:
        filhos: list[Gtk.FlowBoxChild] = []
        filho = self.temas_flowbox.get_first_child()
        while filho is not None:
            if isinstance(filho, Gtk.FlowBoxChild):
                filhos.append(filho)
            filho = filho.get_next_sibling()
        return filhos

    def _escolher_tema(
        self, _caixa: Gtk.FlowBox, filho: Gtk.FlowBoxChild
    ) -> None:
        slug = getattr(filho, "slug", None)
        if not isinstance(slug, str):
            return
        if self._bloqueado_no_modo(slug):
            self.add_toast(
                Adw.Toast.new(
                    _("Este tema só funciona no modo escuro. Mude o Modo para Escuro.")
                )
            )
            return
        shared.schema.set_string("theme-slug", slug)
        self._refletir_tema()
        self._aplicar_tema(slug)
        self._agendar_sync_steam()
        filho.grab_focus()

    def _focar_galeria(self, *_args: Any) -> None:
        """Foco inicial da página: o tema em uso."""
        for filho in self._filhos_da_galeria():
            if getattr(filho, "slug", None) == self._slug_atual():
                filho.grab_focus()
                return
        self.tema_modo_row.grab_focus()

    # -- modo -------------------------------------------------------------

    def _ligar_modo(self) -> None:
        self.tema_modo_row.set_model(
            Gtk.StringList.new([_("Claro"), _("Escuro"), _("Automático")])
        )
        self.tema_modo_row.connect("notify::selected", self._modo_escolhido)

    def _modo_escolhido(self, row: Adw.ComboRow, *_args: Any) -> None:
        if self._bloqueio_ui:
            return
        indice = row.get_selected()
        if not 0 <= indice < len(MODOS):
            return
        modo = MODOS[indice]
        shared.schema.set_string("theme-mode", modo)
        self._aplicar_modo(modo)
        self._atualizar_disponibilidade_temas()
        self._agendar_sync_steam()

    def _refletir_modo(self) -> None:
        with self._sem_reentrada():
            self.tema_modo_row.set_selected(MODOS.index(self._modo_atual()))
        self._atualizar_disponibilidade_temas()

    # -- destaque ---------------------------------------------------------

    def _ligar_destaque(self) -> None:
        self.tema_destaque_row.set_model(
            Gtk.StringList.new(
                [_("Padrão do tema")]
                + [_(nome) for nome, _hex in DESTAQUES]
                + [_("Personalizado")]
            )
        )
        self.tema_destaque_row.connect("notify::selected", self._destaque_escolhido)
        self.tema_cor_button.connect("notify::rgba", self._cor_personalizada_escolhida)
        self.tema_cor_padrao_switch.connect(
            "notify::active", self._alternar_cor_padrao
        )

    def _destaque_escolhido(self, row: Adw.ComboRow, *_args: Any) -> None:
        if self._bloqueio_ui:
            return
        indice = row.get_selected()
        if indice == 0:
            self._gravar_destaque("")
            return
        if 1 <= indice <= len(DESTAQUES):
            self._gravar_destaque(DESTAQUES[indice - 1][1])
            return
        # "Personalizado": revela o seletor e parte da cor atual.
        atual = shared.schema.get_string("theme-accent-custom").strip()
        self._gravar_destaque(atual or _hex_do_rgba(self.tema_cor_button.get_rgba()))
        self.tema_cor_personalizada_row.set_visible(True)
        self.tema_cor_button.grab_focus()

    def _gravar_destaque(self, hexcor: str) -> None:
        """Grava a cor escolhida e sincroniza os controles dependentes."""
        shared.schema.set_string("theme-accent-custom", hexcor)
        self._aplicar_destaque()
        # Qualquer mudança de destaque (inclusive voltar ao "Padrão", que
        # grava "") altera o acento efetivo da Steam, então sempre re-sincro-
        # niza a skin com debounce; o agendamento em si decide se há o que
        # regravar a partir da assinatura do perfil.
        self._agendar_sync_steam()

    def _cor_personalizada_escolhida(
        self, botao: Gtk.ColorDialogButton, *_args: Any
    ) -> None:
        if self._bloqueio_ui:
            return
        hexcor = _hex_do_rgba(botao.get_rgba())
        if hexcor == shared.schema.get_string("theme-accent-custom"):
            return
        self._gravar_destaque(hexcor)
        with self._sem_reentrada():
            self.tema_destaque_row.set_selected(len(DESTAQUES) + 1)
            self.tema_cor_padrao_switch.set_active(False)
        self.tema_cor_personalizada_row.set_visible(True)

    def _alternar_cor_padrao(self, row: Adw.SwitchRow, *_args: Any) -> None:
        if self._bloqueio_ui:
            return
        if row.get_active():
            self._gravar_destaque("")
            with self._sem_reentrada():
                self.tema_destaque_row.set_selected(0)
            self.tema_cor_personalizada_row.set_visible(False)
            return
        atual = shared.schema.get_string("theme-accent-custom").strip()
        with self._sem_reentrada():
            self.tema_destaque_row.set_selected(len(DESTAQUES) + 1)
        self._gravar_destaque(atual or _hex_do_rgba(self.tema_cor_button.get_rgba()))
        self.tema_cor_personalizada_row.set_visible(True)
        self.tema_cor_button.grab_focus()

    def _refletir_destaque(self) -> None:
        hexcor = shared.schema.get_string("theme-accent-custom").strip()
        personalizado = bool(hexcor)
        indice = 0
        if personalizado:
            indice = len(DESTAQUES) + 1
            for posicao, (_nome, valor) in enumerate(DESTAQUES, start=1):
                if valor.casefold() == hexcor.casefold():
                    indice = posicao
                    break
        with self._sem_reentrada():
            self.tema_destaque_row.set_selected(indice)
            self.tema_cor_padrao_switch.set_active(not personalizado)
            if personalizado:
                self.tema_cor_button.set_rgba(_rgba_do_hex(hexcor))
        self.tema_cor_personalizada_row.set_visible(indice == len(DESTAQUES) + 1)

    # -- brilhos e restauração --------------------------------------------

    def _alternar_glows(self, row: Adw.SwitchRow, *_args: Any) -> None:
        if self._bloqueio_ui:
            return
        self._aplicar_glows()
        if row.get_active() and self._slug_atual() == SLUG_PADRAO:
            self._agendar_sync_steam()

    def restaurar_aparencia(self, *_args: Any) -> None:
        """Volta ao tema Jolven, modo automático e destaque padrão."""
        shared.schema.set_string("theme-slug", SLUG_PADRAO)
        shared.schema.set_string("theme-mode", MODO_PADRAO)
        shared.schema.set_string("theme-accent-custom", "")
        with self._sem_reentrada():
            self.tema_glows_switch.set_active(False)
        self._refletir_tema()
        self._refletir_modo()
        self._refletir_destaque()
        self._aplicar_tema(SLUG_PADRAO)
        self._aplicar_modo(MODO_PADRAO)
        self._aplicar_glows()
        self.tema_restaurar_row.grab_focus()
        self.add_toast(Adw.Toast.new(_("Aparência restaurada ao padrão")))
        self._agendar_sync_steam()

    # -- estado derivado do tema ------------------------------------------

    def _sem_reentrada(self) -> Any:
        """Evita que a atualização programática dos widgets volte ao schema."""

        class _Guarda:
            def __init__(self, dono: "CartridgesPreferences") -> None:
                self._dono = dono

            def __enter__(self) -> None:
                self._dono._bloqueio_ui += 1

            def __exit__(self, *_exc: Any) -> None:
                self._dono._bloqueio_ui -= 1

        return _Guarda(self)

    def _nome_do_tema(self, slug: str) -> str:
        if self._catalogo_temas is None:
            return slug
        return self._catalogo_temas.nome(slug)

    def _slug_atual(self) -> str:
        slug = shared.schema.get_string("theme-slug")
        catalogo = self._catalogo_temas
        if catalogo is not None and catalogo.disponivel and slug not in catalogo.slugs:
            return catalogo.padrao()
        if not slug:
            return catalogo.padrao() if catalogo is not None else SLUG_PADRAO
        return slug

    def _modo_atual(self) -> str:
        modo = shared.schema.get_string("theme-mode")
        return modo if modo in MODOS else MODO_PADRAO

    def _modo_escuro_efetivo(self) -> bool:
        modo = self._modo_atual()
        if modo == "dark":
            return True
        if modo == "light":
            return False
        try:
            return bool(Adw.StyleManager.get_default().get_dark())
        except Exception:  # pylint: disable=broad-exception-caught
            return True

    def _bloqueado_no_modo(self, slug: str) -> bool:
        catalogo = self._catalogo_temas
        return bool(
            catalogo is not None
            and catalogo.disponivel
            and catalogo.dark_only(slug)
            and not self._modo_escuro_efetivo()
        )

    def _glows_ativos(self) -> bool:
        return (
            self.tema_glows_switch.get_active()
            and self._slug_atual() == SLUG_PADRAO
        )

    def _refletir_tema(self) -> None:
        slug = self._slug_atual()
        self.tema_selecionado_row.set_subtitle(self._nome_do_tema(slug))
        self.tema_selecionado_row.set_tooltip_text(slug)
        with self._sem_reentrada():
            self.tema_glows_switch.set_visible(slug == SLUG_PADRAO)
            if slug != SLUG_PADRAO:
                self.tema_glows_switch.set_active(False)
            self.temas_flowbox.unselect_all()
        for filho in self._filhos_da_galeria():
            if getattr(filho, "slug", None) == slug:
                self.temas_flowbox.select_child(filho)
                break
        self._atualizar_disponibilidade_temas()

    def _atualizar_disponibilidade_temas(self) -> None:
        """Marca os temas que só funcionam no modo escuro."""
        escuro = self._modo_escuro_efetivo()
        catalogo = self._catalogo_temas
        for filho in self._filhos_da_galeria():
            slug = getattr(filho, "slug", None)
            if not isinstance(slug, str):
                continue
            nome = self._nome_do_tema(slug)
            bloqueado = bool(
                catalogo is not None
                and catalogo.disponivel
                and catalogo.dark_only(slug)
                and not escuro
            )
            filho.set_sensitive(not bloqueado)
            filho.set_tooltip_text(
                _("{} — só funciona no modo escuro").format(nome)
                if bloqueado
                else nome
            )

    # ── Aparência: integração com a Steam ─────────────────────────────────

    def setup_steam_group(self) -> None:
        """Liga o grupo da Steam; ausência da Steam nunca quebra a página."""
        # Ligação só de leitura (schema -> switch): a gravação fica a cargo do
        # manipulador. Assim, ligar/desligar o switch por código (ao habilitar
        # ou bloquear controles enquanto a Steam é procurada) nunca reescreve a
        # preferência guardada pelo usuário.
        with self._sem_reentrada():
            shared.schema.bind(
                "steam-skin-enabled",
                self.steam_skin_switch,
                "active",
                Gio.SettingsBindFlags.GET,
            )
        self.steam_skin_switch.connect("notify::active", self._alternar_skin_steam)
        self.steam_instalacao_row.connect("notify::selected", self._escolher_instalacao)
        self.steam_aplicar_button.connect("clicked", self._aplicar_skin_steam)
        self.steam_reparar_button.connect("clicked", self._reparar_skin_steam)
        self.steam_restaurar_button.connect("clicked", self._restaurar_skin_steam)
        self._configurar_opcoes_avancadas()
        self._ajustar_alvos_de_toque()
        self._definir_controles_steam(ativos=False)
        self._detectar_steam()

    # -- manager tolerante -------------------------------------------------

    def _steam_manager(self) -> Any:
        if self._manager_steam_carregado:
            return self._manager_steam
        self._manager_steam_carregado = True
        try:
            from cartridges.integrations.steam_skin.manager import (  # noqa: PLC0415
                SteamSkinManager,
            )

            criador = getattr(SteamSkinManager, "instance", None)
            self._manager_steam = criador() if callable(criador) else SteamSkinManager()
        except Exception:  # pylint: disable=broad-exception-caught
            self._manager_steam = None
            logging.warning("SteamSkinManager indisponível", exc_info=True)
        return self._manager_steam

    # -- opções avançadas -------------------------------------------------

    FONTES = ("adwaita", "cantarell", "system")
    CONTROLES_TEMA = ("theme", "light", "dark")
    CONTROLES_LAYOUT = ("default", "left", "right")

    def _linhas_avancadas(self) -> dict[str, Gtk.Widget]:
        return {
            "fonte": self.steam_fonte_row,
            "window-controls-theme": self.steam_window_controls_theme_row,
            "window-controls-layout": self.steam_window_controls_layout_row,
            "rounded-corners": self.steam_rounded_corners_switch,
            "cursor-pointer": self.steam_cursor_pointer_switch,
            "hide-whats-new": self.steam_hide_whats_new_switch,
            "sidebar-hover": self.steam_sidebar_hover_switch,
            "uncrop-covers": self.steam_uncrop_covers_switch,
            "hide-qr": self.steam_hide_qr_switch,
        }

    def _configurar_opcoes_avancadas(self) -> None:
        self.steam_fonte_row.set_model(
            Gtk.StringList.new(
                [_("Padrão do Adwaita"), _("Cantarell"), _("Fonte do sistema")]
            )
        )
        self.steam_fonte_row.set_selected(0)
        self.steam_window_controls_theme_row.set_model(
            Gtk.StringList.new([_("Seguir o tema"), _("Claro"), _("Escuro")])
        )
        self.steam_window_controls_theme_row.set_selected(0)
        self.steam_window_controls_layout_row.set_model(
            Gtk.StringList.new([_("Automático"), _("Todos à esquerda"), _("Todos à direita")])
        )
        self.steam_window_controls_layout_row.set_selected(0)
        # Cantos arredondados são o padrão do Adwaita (e do upstream sem
        # extras): o interruptor começa ligado para não mudar a aparência de
        # quem nunca mexeu nas opções.
        self.steam_rounded_corners_switch.set_active(True)
        self._atualizar_opcoes_disponiveis()

    def _opcoes_suportadas(self) -> set[str]:
        """Opções que a skin aceita, preferindo o que o gerenciador reporta.

        Aceita tanto os ids usados na página (``fonte``) quanto as chaves do
        instalador (``font``); sem informação do gerenciador, vale o conjunto
        padrão — que espelha a árvore vendorada atual.
        """
        manager = self._steam_manager()
        if manager is not None:
            for nome in ("opcoes_suportadas", "capacidades", "supported_options"):
                valor = getattr(manager, nome, None)
                if callable(valor):
                    try:
                        valor = valor()
                    except Exception:  # pylint: disable=broad-exception-caught
                        valor = None
                if isinstance(valor, (set, frozenset, list, tuple)):
                    return self._normalizar_chaves(valor)
        return set(OPCOES_STEAM_PADRAO)

    @staticmethod
    def _normalizar_chaves(valor: Any) -> set[str]:
        """Converte chaves anunciadas em ids usados pela página."""
        resultado: set[str] = set()
        for item in valor:
            chave = str(item)
            if chave in CHAVES_PERFIL_STEAM:
                resultado.add(chave)
            elif chave in CHAVES_UI_POR_PERFIL:
                resultado.add(CHAVES_UI_POR_PERFIL[chave])
        return resultado

    def _atualizar_opcoes_disponiveis(self) -> None:
        suportadas = self._opcoes_suportadas()
        for chave, linha in self._linhas_avancadas().items():
            disponivel = chave in suportadas
            linha.set_sensitive(disponivel)
            if disponivel:
                linha.remove_css_class("dim-label")
                continue
            linha.add_css_class("dim-label")
            if isinstance(linha, (Adw.SwitchRow, Adw.ComboRow)):
                linha.set_subtitle(_("Indisponível nesta versão da skin"))
        if not suportadas:
            self.steam_avancado_row.set_subtitle(
                _("Esta versão da skin não oferece ajustes finos")
            )

    def _valor_combo(
        self, row: Adw.ComboRow, valores: tuple[str, ...], padrao: str
    ) -> str:
        indice = row.get_selected()
        return valores[indice] if 0 <= indice < len(valores) else padrao

    def _opcoes_avancadas(self) -> dict[str, Any]:
        """Opções avançadas no formato do instalador, só as suportadas."""
        valores: dict[str, Any] = {
            "fonte": self._valor_combo(self.steam_fonte_row, self.FONTES, "adwaita"),
            "window-controls-theme": self._valor_combo(
                self.steam_window_controls_theme_row, self.CONTROLES_TEMA, "theme"
            ),
            "window-controls-layout": self._valor_combo(
                self.steam_window_controls_layout_row, self.CONTROLES_LAYOUT, "default"
            ),
            "rounded-corners": self.steam_rounded_corners_switch.get_active(),
            "cursor-pointer": self.steam_cursor_pointer_switch.get_active(),
            "hide-whats-new": self.steam_hide_whats_new_switch.get_active(),
            "sidebar-hover": self.steam_sidebar_hover_switch.get_active(),
            "uncrop-covers": self.steam_uncrop_covers_switch.get_active(),
            "hide-qr": self.steam_hide_qr_switch.get_active(),
        }
        suportadas = self._opcoes_suportadas()
        opcoes = {
            CHAVES_PERFIL_STEAM[chave]: valores[chave]
            for chave in OPCOES_STEAM
            if chave in suportadas
        }
        # A instalação escolhida entra junto (chave que o instalador ignora)
        # para que a assinatura de diferença do SteamSkinManager note a troca
        # de instalação e reaplique a skin no destino novo.
        instalacao = self._instalacao_escolhida()
        if instalacao is not None:
            opcoes["install_path"] = str(instalacao.path)
        return opcoes

    # -- detecção e estado ------------------------------------------------

    def _detectar_steam(self) -> None:
        """Procura instalações da Steam fora da thread principal."""
        self.steam_estado_spinner.set_visible(True)
        self.steam_estado_row.set_subtitle(_("Verificando a Steam…"))

        def trabalho() -> None:
            try:
                from cartridges.integrations.steam_skin.detector import (  # noqa: PLC0415
                    detect_all,
                )

                instalacoes: Any = list(detect_all())
            except Exception:  # pylint: disable=broad-exception-caught
                logging.warning("Detector de Steam indisponível", exc_info=True)
                instalacoes = None
            entregar_na_tela(self._steam_detectada, instalacoes)

        threading.Thread(target=trabalho, daemon=True).start()

    def _steam_detectada(self, instalacoes: Any) -> bool:
        self.steam_estado_spinner.set_visible(False)
        if instalacoes is None:
            self.steam_estado_row.set_subtitle(_("Integração com a Steam indisponível"))
            self._instalacoes_steam = []
            self._definir_controles_steam(ativos=False)
            return GLib.SOURCE_REMOVE

        acessiveis = [item for item in instalacoes if getattr(item, "accessible", False)]
        self._instalacoes_steam = acessiveis
        if not acessiveis:
            self.steam_estado_row.set_subtitle(_("Steam não encontrada"))
            self.steam_instalacao_row.set_visible(False)
            self.steam_avancado_row.set_enable_expansion(False)
            self._definir_controles_steam(ativos=False)
            return GLib.SOURCE_REMOVE

        salvo = shared.schema.get_string("steam-install-path")
        indice = 0
        for posicao, item in enumerate(acessiveis):
            if str(item.path) == salvo:
                indice = posicao
                break
        self.steam_instalacao_row.set_model(
            Gtk.StringList.new([self._rotulo_instalacao(item) for item in acessiveis])
        )
        self.steam_instalacao_row.set_visible(len(acessiveis) > 1)
        with self._sem_reentrada():
            self.steam_instalacao_row.set_selected(indice)
        if not salvo:
            shared.schema.set_string(
                "steam-install-path", str(acessiveis[indice].path)
            )
        self.steam_avancado_row.set_enable_expansion(True)
        self._definir_controles_steam(ativos=True)
        self._atualizar_estado_steam()
        return GLib.SOURCE_REMOVE

    def _rotulo_instalacao(self, instalacao: Any) -> str:
        tipos = {
            "native": _("Nativo"),
            "flatpak": _("Flatpak"),
            "snap": _("Snap"),
            "custom": _("Personalizado"),
        }
        tipo = tipos.get(str(getattr(instalacao, "kind", "")), _("Steam"))
        return f"{tipo} · {instalacao.path}"

    def _instalacao_escolhida(self) -> Any:
        if not self._instalacoes_steam:
            return None
        indice = self.steam_instalacao_row.get_selected()
        if 0 <= indice < len(self._instalacoes_steam):
            return self._instalacoes_steam[indice]
        return self._instalacoes_steam[0]

    def _escolher_instalacao(self, row: Adw.ComboRow, *_args: Any) -> None:
        if self._bloqueio_ui:
            return
        indice = row.get_selected()
        if not 0 <= indice < len(self._instalacoes_steam):
            return
        shared.schema.set_string(
            "steam-install-path", str(self._instalacoes_steam[indice].path)
        )
        self._atualizar_estado_steam()
        self._agendar_sync_steam()

    def _definir_controles_steam(self, ativos: bool) -> None:
        """Habilita a skin e as ações conforme a Steam e o gerenciador.

        Só mexe em sensibilidade: o switch continua refletindo a preferência
        guardada, para não gravar nada no schema sem ação do usuário.
        """
        tem_manager = self._steam_manager() is not None
        self.steam_skin_switch.set_sensitive(ativos and tem_manager)
        for row in (self.steam_aplicar_row, self.steam_reparar_row, self.steam_restaurar_row):
            row.set_sensitive(ativos and tem_manager and not self._steam_ocupada)
        self.steam_avancado_row.set_sensitive(ativos and tem_manager)

    def _atualizar_estado_steam(self, *_args: Any) -> None:
        """Lê o estado da skin fora da thread principal."""
        manager = self._steam_manager()
        if manager is None:
            self.steam_estado_row.set_subtitle(_("Integração com a Steam indisponível"))
            return
        self.steam_estado_spinner.set_visible(True)

        def trabalho() -> None:
            try:
                estado = manager.estado()
            except Exception as erro:  # pylint: disable=broad-exception-caught
                logging.warning("Falha ao ler o estado da skin: %s", erro)
                entregar_na_tela(self._estado_steam_pronto, None, True)
            else:
                entregar_na_tela(self._estado_steam_pronto, estado, False)

        threading.Thread(target=trabalho, daemon=True).start()

    def _estado_steam_pronto(self, estado: Any, falhou: bool) -> bool:
        self.steam_estado_spinner.set_visible(False)
        if falhou:
            self.steam_estado_row.set_subtitle(_("Não foi possível verificar a Steam"))
            return GLib.SOURCE_REMOVE
        self.steam_estado_row.set_subtitle(self._texto_do_estado(estado))
        return GLib.SOURCE_REMOVE

    def _texto_do_estado(self, estado: Any) -> str:
        from cartridges.integrations.steam_skin.recovery import (  # noqa: PLC0415
            texto_do_estado,
        )

        return texto_do_estado(estado)

    # -- perfil compartilhado e sincronização ------------------------------

    def _perfil_steam(self) -> dict:
        """Perfil tema+destaque+opções no formato entendido pela lane.

        O ``SteamSkinManager`` lê ``theme_slug``, ``accent_custom``/``accent``,
        ``mode`` e as opções finas aninhadas em ``opcoes_avancadas``.
        """
        base: dict = {}
        manager = self._manager_tema
        funcao = getattr(manager, "perfil_compartilhado", None) if manager else None
        if callable(funcao):
            try:
                valor = funcao()
            except Exception:  # pylint: disable=broad-exception-caught
                valor = None
            if isinstance(valor, dict):
                base = dict(valor)
        base.setdefault("theme_slug", self._slug_atual())
        base.setdefault("mode", self._modo_atual())
        base.setdefault("accent_custom", shared.schema.get_string("theme-accent-custom"))
        base.setdefault("accent", self._accent_do_tema())
        base.setdefault("glows", self._glows_ativos())
        base["opcoes_avancadas"] = self._opcoes_avancadas()
        return base

    def _accent_do_tema(self) -> str:
        """Destaque da paleta do tema atual, usado quando não há cor própria."""
        catalogo = self._catalogo_temas
        if catalogo is None:
            return ""
        _fundo, destaque = catalogo.cores(self._slug_atual())
        return destaque or ""

    def _agendar_sync_steam(self) -> None:
        """Debounce: só sincroniza a skin depois que o usuário para de mexer."""
        if self._sync_steam_id is not None:
            GLib.source_remove(self._sync_steam_id)
        self._sync_steam_id = GLib.timeout_add(700, self._sincronizar_steam)

    def _sincronizar_steam(self) -> bool:
        self._sync_steam_id = None
        if not shared.schema.get_boolean("steam-skin-enabled"):
            return GLib.SOURCE_REMOVE
        manager = self._steam_manager()
        if manager is None:
            return GLib.SOURCE_REMOVE
        perfil = self._perfil_steam()

        def trabalho() -> None:
            try:
                manager.sincronizar_se_habilitado(perfil)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.warning("Falha ao sincronizar a skin da Steam", exc_info=True)
            else:
                entregar_na_tela(self._atualizar_estado_steam)

        threading.Thread(target=trabalho, daemon=True).start()
        return GLib.SOURCE_REMOVE

    # -- ações da skin ----------------------------------------------------

    def _alternar_skin_steam(self, row: Adw.SwitchRow, *_args: Any) -> None:
        if self._bloqueio_ui:
            return
        ativo = row.get_active()
        shared.schema.set_boolean("steam-skin-enabled", ativo)
        self._executar_acao_steam("aplicar" if ativo else "restaurar")

    def _aplicar_skin_steam(self, *_args: Any) -> None:
        self._executar_acao_steam("aplicar")

    def _reparar_skin_steam(self, *_args: Any) -> None:
        self._executar_acao_steam("reparar")

    def _restaurar_skin_steam(self, *_args: Any) -> None:
        self._executar_acao_steam("restaurar")

    def _executar_acao_steam(self, acao: str) -> None:
        manager = self._steam_manager()
        if manager is None or self._steam_ocupada:
            if manager is None:
                self.add_toast(
                    Adw.Toast.new(_("Integração com a Steam indisponível"))
                )
            return
        self._steam_ocupada = True
        self.steam_estado_spinner.set_visible(True)
        self._definir_controles_steam(ativos=bool(self._instalacoes_steam))
        mensagens = {
            "aplicar": _("Aplicando o tema à Steam…"),
            "reparar": _("Reparando a skin da Steam…"),
            "restaurar": _("Restaurando a aparência original da Steam…"),
        }
        self.steam_estado_row.set_subtitle(mensagens.get(acao, _("Trabalhando…")))
        perfil = self._perfil_steam()

        def trabalho() -> None:
            try:
                if acao == "restaurar":
                    manager.restaurar_original()
                elif acao == "reparar":
                    # Reparar é uma ação explícita do usuário: reconstrói a
                    # skin mesmo com o toggle desligado.
                    reparar = getattr(manager, "reparar", None)
                    if callable(reparar):
                        reparar(perfil)
                    else:
                        manager.sincronizar_se_habilitado(perfil)
                else:
                    manager.aplicar_perfil(perfil)
            except Exception as erro:  # pylint: disable=broad-exception-caught
                logging.warning("Ação da skin da Steam falhou (%s): %s", acao, erro)
                entregar_na_tela(self._acao_steam_pronta, acao, True)
            else:
                entregar_na_tela(self._acao_steam_pronta, acao, False)

        threading.Thread(target=trabalho, daemon=True).start()

    def _acao_steam_pronta(self, acao: str, falhou: bool) -> bool:
        self._steam_ocupada = False
        self.steam_estado_spinner.set_visible(False)
        self._definir_controles_steam(ativos=bool(self._instalacoes_steam))
        if falhou:
            self.add_toast(
                Adw.Toast.new(_("Não foi possível concluir a ação. Tente de novo."))
            )
        else:
            concluidas = {
                "aplicar": _("Tema aplicado à Steam"),
                "reparar": _("Skin da Steam reparada"),
                "restaurar": _("Aparência original da Steam devolvida"),
            }
            self.add_toast(Adw.Toast.new(concluidas.get(acao, _("Pronto"))))
        botoes = {
            "aplicar": self.steam_aplicar_button,
            "reparar": self.steam_reparar_button,
            "restaurar": self.steam_restaurar_button,
        }
        botao = botoes.get(acao)
        if botao is not None:
            botao.grab_focus()
        self._atualizar_estado_steam()
        return GLib.SOURCE_REMOVE

    def _ajustar_alvos_de_toque(self) -> None:
        """Na sessão o controle é o ponteiro: alvos de ~44 px."""
        if not shared.runtime.is_session:
            return
        for botao in (
            self.steam_aplicar_button,
            self.steam_reparar_button,
            self.steam_restaurar_button,
        ):
            botao.set_size_request(-1, 44)
        self.tema_cor_button.set_size_request(44, 44)

    # (código gettext, nome no próprio idioma). Os nomes não passam por
    # gettext de propósito: o autônimo é igual em todo locale.
    LANGUAGES = [
        ("ar", "العربية"),
        ("be", "Беларуская"),
        ("ca", "Català"),
        ("cs", "Čeština"),
        ("de", "Deutsch"),
        ("el", "Ελληνικά"),
        ("en_GB", "English (UK)"),
        ("es", "Español"),
        ("eu", "Euskara"),
        ("fa", "فارسی"),
        ("fi", "Suomi"),
        ("fr", "Français"),
        ("hi", "हिन्दी"),
        ("hr", "Hrvatski"),
        ("hu", "Magyar"),
        ("ia", "Interlingua"),
        ("ie", "Interlingue"),
        ("it", "Italiano"),
        ("ja", "日本語"),
        ("ka", "ქართული"),
        ("kk", "Қазақша"),
        ("ko", "한국어"),
        ("kw", "Kernewek"),
        ("nb_NO", "Norsk bokmål"),
        ("nl", "Nederlands"),
        ("nn", "Norsk nynorsk"),
        ("pl", "Polski"),
        ("pt", "Português"),
        ("pt_BR", "Português (Brasil)"),
        ("ro", "Română"),
        ("ru", "Русский"),
        ("sv", "Svenska"),
        ("ta", "தமிழ்"),
        ("te", "తెలుగు"),
        ("tr", "Türkçe"),
        ("uk", "Українська"),
        ("vi", "Tiếng Việt"),
        ("zh_Hans", "简体中文"),
    ]

    def setup_language_row(self) -> None:
        """Seletor de idioma: detecção automática ou catálogo fixo.

        O valor é lido pelo launcher (jolven.in) antes do gettext.install,
        por isso a troca só vale após reiniciar o aplicativo.
        """
        codes = [code for code, _name in self.LANGUAGES]
        self.language_row.set_model(
            Gtk.StringList.new(
                [_("Automatic detection"), *[name for _code, name in self.LANGUAGES]]
            )
        )
        saved = shared.schema.get_string("language")
        if saved != "auto" and saved not in codes:
            shared.schema.set_string("language", "auto")
            saved = "auto"
        self.language_row.set_selected(0 if saved == "auto" else codes.index(saved) + 1)

        def selected_changed(widget: Adw.ComboRow, *_args: Any) -> None:
            selected = widget.get_selected()
            shared.schema.set_string(
                "language", "auto" if selected == 0 else codes[selected - 1]
            )
            self.add_toast(
                Adw.Toast.new(_("Restart Jolven to apply the new language"))
            )

        self.language_row.connect("notify::selected", selected_changed)

    def setup_game_overlay_button_row(self) -> None:
        choices = ("mode", "home", "both")
        self.game_overlay_button_row.set_model(
            Gtk.StringList.new(
                [
                    _("Button Mode"),
                    _("Button Home"),
                    _("Both buttons"),
                ]
            )
        )
        saved = shared.schema.get_string("game-overlay-button")
        self.game_overlay_button_row.set_selected(
            choices.index(saved) if saved in choices else choices.index("both")
        )

        def selected_changed(widget: Adw.ComboRow, *_args: Any) -> None:
            selected = widget.get_selected()
            if selected < len(choices):
                shared.schema.set_string("game-overlay-button", choices[selected])

        self.game_overlay_button_row.connect("notify::selected", selected_changed)

    @staticmethod
    def _setup_recorder_combo(
        row: Adw.ComboRow, setting: str, options: list[tuple[str, str]]
    ) -> None:
        values = [value for value, _label in options]
        row.set_model(Gtk.StringList.new([label for _value, label in options]))
        saved = shared.schema.get_string(setting)
        row.set_selected(values.index(saved) if saved in values else 0)

        def selected_changed(widget: Adw.ComboRow, *_args: Any) -> None:
            selected = widget.get_selected()
            if 0 <= selected < len(values):
                shared.schema.set_string(setting, values[selected])

        row.connect("notify::selected", selected_changed)

    @staticmethod
    def _setup_recorder_spin(row: Adw.SpinRow, setting: str) -> None:
        row.set_value(shared.schema.get_int(setting))

        def value_changed(widget: Adw.SpinRow, *_args: Any) -> None:
            shared.schema.set_int(setting, int(widget.get_value()))

        row.connect("notify::value", value_changed)

    def setup_recorder_page(self) -> None:
        self._setup_recorder_combo(
            self.recorder_source_row,
            "recorder-source",
            [
                ("portal", _("Portal (escolher a cada gravação)")),
                ("monitor", _("Monitor inteiro")),
                ("window", _("Janela em foco")),
            ],
        )
        self._setup_recorder_combo(
            self.recorder_container_row,
            "recorder-container",
            [
                ("mp4", _("MP4")),
                ("mkv", _("Matroska (MKV)")),
            ],
        )
        self._setup_recorder_combo(
            self.recorder_codec_row,
            "recorder-codec",
            [
                ("auto", _("Automático")),
                ("h264", _("H.264")),
                ("hevc", _("H.265 (HEVC)")),
                ("av1", _("AV1")),
                ("vp8", _("VP8")),
                ("vp9", _("VP9")),
            ],
        )
        self._setup_recorder_combo(
            self.recorder_quality_row,
            "recorder-quality",
            [
                ("low", _("Baixa")),
                ("medium", _("Média")),
                ("high", _("Alta")),
                ("very_high", _("Muito alta")),
                ("ultra", _("Ultra")),
            ],
        )
        self._setup_recorder_combo(
            self.recorder_bitrate_mode_row,
            "recorder-bitrate-mode",
            [
                ("auto", _("Automático")),
                ("cbr", _("Taxa constante (CBR)")),
                ("vbr", _("Taxa variável (VBR)")),
            ],
        )
        self._setup_recorder_spin(self.recorder_fps_row, "recorder-fps")

        def recorder_scale_changed(*_args: Any) -> None:
            shared.schema.set_string(
                "recorder-scale", self.recorder_scale_row.get_text().strip()
            )

        self.recorder_scale_row.set_text(shared.schema.get_string("recorder-scale"))
        self.recorder_scale_row.connect("changed", recorder_scale_changed)

        self._setup_recorder_combo(
            self.recorder_audio_row,
            "recorder-audio",
            [
                ("default_output", _("Saída padrão")),
                ("default_input", _("Entrada (microfone)")),
                ("both", _("Saída e entrada")),
                ("none", _("Sem áudio")),
            ],
        )
        self._setup_recorder_combo(
            self.recorder_audio_codec_row,
            "recorder-audio-codec",
            [
                ("opus", _("Opus")),
                ("aac", _("AAC")),
                ("flac", _("FLAC")),
            ],
        )
        self._setup_recorder_spin(
            self.recorder_audio_bitrate_row, "recorder-audio-bitrate"
        )
        self._setup_recorder_spin(
            self.recorder_replay_seconds_row, "recorder-replay-seconds"
        )
        self._setup_recorder_combo(
            self.recorder_replay_storage_row,
            "recorder-replay-storage",
            [
                ("ram", _("Memória RAM")),
                ("disk", _("Disco")),
            ],
        )

        def recorder_output_dir_changed(*_args: Any) -> None:
            shared.schema.set_string(
                "recorder-output-dir", self.recorder_output_dir_row.get_text().strip()
            )

        self.recorder_output_dir_row.set_text(
            shared.schema.get_string("recorder-output-dir")
        )
        self.recorder_output_dir_row.connect("changed", recorder_output_dir_changed)

        def recorder_stream_url_changed(*_args: Any) -> None:
            shared.schema.set_string(
                "recorder-stream-url", self.recorder_stream_url_row.get_text().strip()
            )

        self.recorder_stream_url_row.set_text(
            shared.schema.get_string("recorder-stream-url")
        )
        self.recorder_stream_url_row.connect("changed", recorder_stream_url_changed)

    def choose_folder(
        self, _widget: Any, callback: Callable, callback_data: Optional[str] = None
    ) -> None:
        self.file_chooser.select_folder(shared.win, None, callback, callback_data)

    def undo_remove_all(self, *_args: Any) -> bool:
        shared.win.get_application().state = shared.AppState.UNDO_REMOVE_ALL_GAMES
        for game in self.removed_games:
            game.removed = False
            game.save()
            game.update()

        self.removed_games = set()
        self.toast.dismiss()
        shared.win.get_application().state = shared.AppState.DEFAULT
        shared.win.create_source_rows()

        return True

    def remove_all_games(self, *_args: Any) -> None:
        shared.win.get_application().state = shared.AppState.REMOVE_ALL_GAMES
        for game in shared.store:
            if not game.removed:
                self.removed_games.add(game)
                game.removed = True
                game.save()
                game.update()

        if shared.win.navigation_view.get_visible_page() == shared.win.details_page:
            shared.win.navigation_view.pop()

        self.add_toast(self.toast)
        shared.win.get_application().state = shared.AppState.DEFAULT
        shared.win.create_source_rows()

    def _backup_filters(self) -> Gio.ListStore:
        backup_filter = Gtk.FileFilter(name=_("Backup do Jolven"))
        backup_filter.add_suffix("zip")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(backup_filter)
        return filters

    def export_backup(self, *_args: Any) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_initial_name(f"jolven-backup-{date.today().isoformat()}.zip")
        dialog.set_filters(self._backup_filters())

        def finish(file_dialog: Gtk.FileDialog, result: Gio.Task) -> None:
            try:
                path = Path(file_dialog.save_finish(result).get_path())
            except GLib.Error:
                return
            settings = backup.ler_configuracoes()
            progress = Adw.Toast(title=_("Exportando backup…"), timeout=0)
            self.add_toast(progress)

            def work() -> None:
                try:
                    backup.exportar(path, settings)
                except Exception as error:  # pylint: disable=broad-exception-caught
                    logging.exception("Não foi possível exportar o backup")
                    entregar_na_tela(self._export_done, progress, str(error))
                else:
                    entregar_na_tela(self._export_done, progress, None)

            threading.Thread(target=work, daemon=True).start()

        dialog.save(shared.win, None, finish)

    def _export_done(self, progress: Adw.Toast, error: Optional[str]) -> bool:
        progress.dismiss()
        if error:
            create_dialog(
                self,
                _("Não foi possível exportar"),
                _(
                    "Não foi possível gravar o arquivo. Verifique se a pasta "
                    "de destino está acessível e se há espaço livre em disco."
                ),
            )
        else:
            self.add_toast(Adw.Toast.new(_("Backup exportado")))
        return False

    def import_backup(self, *_args: Any) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_filters(self._backup_filters())

        def finish(file_dialog: Gtk.FileDialog, result: Gio.Task) -> None:
            try:
                path = Path(file_dialog.open_finish(result).get_path())
            except GLib.Error:
                return
            self._restore_backup(path)

        dialog.open(shared.win, None, finish)

    def _restore_backup(self, path: Path) -> None:
        def on_response(_dialog: Any, response: str) -> None:
            if response == "restore":
                self._schedule_restore(path)

        dialog = create_dialog(
            self,
            _("Restaurar este backup?"),
            _("Tem certeza que deseja restaurar este backup? Esta ação é irreversível."),
            "restore",
            _("Restaurar"),
        )
        dialog.set_response_appearance("restore", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", on_response)

    def _schedule_restore(self, path: Path) -> None:
        progress = Adw.Toast(title=_("Preparando a restauração…"), timeout=0)
        self.add_toast(progress)

        def work() -> None:
            try:
                backup.validar(path)
                backup.agendar(path)
            except backup.BackupInvalido:
                entregar_na_tela(self._restore_invalid, progress)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("Não foi possível agendar a restauração do backup")
                entregar_na_tela(self._restore_failed, progress)
            else:
                entregar_na_tela(self._restart_to_restore)

        threading.Thread(target=work, daemon=True).start()

    def _restore_invalid(self, progress: Adw.Toast) -> bool:
        progress.dismiss()
        create_dialog(
            self,
            _("Backup inválido"),
            _("O arquivo não é um backup válido do Jolven."),
        )
        return False

    def _restore_failed(self, progress: Adw.Toast) -> bool:
        progress.dismiss()
        create_dialog(
            self,
            _("Não foi possível restaurar"),
            _("Não foi possível restaurar o backup. Tente novamente."),
        )
        return False

    def _restart_to_restore(self) -> bool:
        app = shared.win.get_application()
        app.reiniciar = True
        app.quit()
        return False

    def reset_app(self, *_args: Any) -> None:
        for dirname in ("jolven", "cartridges"):
            rmtree(shared.data_dir / dirname, True)
            rmtree(shared.config_dir / dirname, True)
            rmtree(shared.cache_dir / dirname, True)

        for key in (
            (settings_schema_source := Gio.SettingsSchemaSource.get_default())
            .lookup(shared.APP_ID, True)
            .list_keys()
        ):
            shared.schema.reset(key)
        for key in settings_schema_source.lookup(
            shared.APP_ID + ".State", True
        ).list_keys():
            shared.state_schema.reset(key)

        shared.win.get_application().quit()

    def update_source_action_row_paths(self, source: Source) -> None:
        """Set the dir subtitle for a source's action rows"""
        for location_name, location in source.locations._asdict().items():
            # Get the action row to subtitle
            action_row = getattr(
                self, f"{source.source_id}_{location_name}_action_row", None
            )
            if not action_row:
                continue

            subtitle = str(Path(shared.schema.get_string(location.schema_key)))

            # Remove the path prefix if picked via Flatpak portal
            subtitle = re.sub("/run/user/\\d*/doc/.*/", "", subtitle)

            # Replace the home directory with "~"
            subtitle = re.sub(f"^{str(shared.home)}", "~", subtitle)

            action_row.set_subtitle(subtitle)

    def resolve_locations(self, source: Source) -> None:
        """Resolve locations and add a warning if location cannot be found"""

        for location_name, location in source.locations._asdict().items():
            action_row = getattr(
                self, f"{source.source_id}_{location_name}_action_row", None
            )
            if not action_row:
                continue

            try:
                location.resolve()

            except UnresolvableLocationError:
                title = _("Installation Not Found")
                description = _("Select a valid directory")
                format_start = '<span rise="12pt"><b><big>'
                format_end = "</big></b></span>\n"

                popover = Gtk.Popover(
                    focusable=True,
                    child=(
                        Gtk.Label(
                            label=format_start + title + format_end + description,
                            use_markup=True,
                            wrap=True,
                            max_width_chars=50,
                            halign=Gtk.Align.CENTER,
                            valign=Gtk.Align.CENTER,
                            justify=Gtk.Justification.CENTER,
                            margin_top=9,
                            margin_bottom=9,
                            margin_start=12,
                            margin_end=12,
                        )
                    ),
                )

                popover.update_property(
                    (Gtk.AccessibleProperty.LABEL,), (title + description,)
                )

                def set_a11y_label(widget: Gtk.Popover) -> None:
                    self.set_focus(widget)

                popover.connect("show", set_a11y_label)

                menu_button = Gtk.MenuButton(
                    icon_name="dialog-warning-symbolic",
                    valign=Gtk.Align.CENTER,
                    popover=popover,
                    tooltip_text=_("Warning"),
                )
                menu_button.add_css_class("warning")

                action_row.add_prefix(menu_button)
                self.warning_menu_buttons[source.source_id] = menu_button

    def init_source_row(self, source: Source) -> None:
        """Initialize a preference row for a source class"""

        def set_dir(_widget: Any, result: Gio.Task, location_name: str) -> None:
            """Callback called when a dir picker button is clicked"""
            try:
                path = Path(self.file_chooser.select_folder_finish(result).get_path())
            except GLib.Error:
                return

            # Good picked location
            location = source.locations._asdict()[location_name]
            if location.check_candidate(path):
                shared.schema.set_string(location.schema_key, str(path))
                self.update_source_action_row_paths(source)
                if self.warning_menu_buttons.get(source.source_id):
                    action_row = getattr(
                        self, f"{source.source_id}_{location_name}_action_row", None
                    )
                    action_row.remove(  # type: ignore
                        self.warning_menu_buttons[source.source_id]
                    )
                    self.warning_menu_buttons.pop(source.source_id)
                logging.debug("User-set value for %s is %s", location.schema_key, path)

            # Bad picked location, inform user
            else:
                title = _("Invalid Directory")
                dialog = create_dialog(
                    self,
                    title,
                    location.invalid_subtitle.format(source.name),
                    "choose_folder",
                    _("Set Location"),
                )

                def on_response(widget: Any, response: str) -> None:
                    if response == "choose_folder":
                        self.choose_folder(widget, set_dir, location_name)

                dialog.connect("response", on_response)

        # Bind expander row activation to source being enabled
        expander_row = getattr(self, f"{source.source_id}_expander_row")
        shared.schema.bind(
            source.source_id,
            expander_row,
            "enable-expansion",
            Gio.SettingsBindFlags.DEFAULT,
        )

        # Connect dir picker buttons
        for location_name in source.locations._asdict():
            button = getattr(
                self, f"{source.source_id}_{location_name}_file_chooser_button", None
            )
            if button is None:
                # Shorter chooser button id used by the shortcuts row.
                button = getattr(
                    self, f"{source.source_id}_{location_name}_button", None
                )
            if button is not None:
                button.connect("clicked", self.choose_folder, set_dir, location_name)

        # Set the source row subtitles
        self.resolve_locations(source)
        self.update_source_action_row_paths(source)
