# window.py
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

import hashlib
import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from cartridges import shared
from cartridges.botao_tarefas import BotaoTarefas
from cartridges.controller import (
    GAMEPAD_CONFIRM_HOLD_SECONDS,
    GAMEPAD_TILE_FOCUS_CLASS,
    GAMEPAD_TILE_FOCUS_RGB_CLASS,
    confirm_hold_exceeded,
    detect_controller_layout,
    focus_class,
    name_for_button,
    should_confine_gamepad,
)
from cartridges.gamepad_visual import GamepadVisual
from cartridges.game import Game, STATUS_LABELS, status_label
from cartridges.game_cover import GameCover
from cartridges.integrations_page import IntegrationsPage
from cartridges.lighting_page import LightingPage
from cartridges.onscreen_keyboard import OnscreenKeyboardDialog
from cartridges.session_history import SessionHistoryDialog
from cartridges.utils import agrupamento, launcher, restauracao, session_log, session_wallpaper, tarefas
from cartridges.utils.animated_flow_box import AnimatedFlowBox
from cartridges.utils.format_playtime import format_playtime, format_stopwatch
from cartridges.utils.install_size import format_size
from cartridges.utils.download import download_bytes
from cartridges.utils.library_background import resolver_fundo
from cartridges.utils.na_tela import entregar_na_tela
from cartridges.utils.news_checker import (
    disabled_sources,
    set_source_enabled,
    ui_language,
)
from cartridges.utils.news_feed import NewsPost, all_sources
from cartridges.utils.open_uri import open_uri
from cartridges.utils.relative_date import relative_date
from cartridges.utils.spring_scroll import attach as attach_spring_scroll
from cartridges.utils.toast_queue import ToastQueue
from cartridges.uzdoom_mods_dialog import UzdoomModsDialog
from cartridges.zerados_picker import ZeradosPicker
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango


_NEWS_THUMB_SIZE = 64
_NEWS_THUMB_BYTES = 2 * 1024 * 1024
_NEWS_THUMB_CACHE_MAX = 200

# A tela de Novidades é um portal com três degraus: o carrossel de destaques,
# a grade de cards menores e, no fim, a lista com tudo. A grade começa onde o
# carrossel termina, então a mesma notícia nunca aparece duas vezes na mesma
# tela.
_NEWS_HIGHLIGHTS = 5
_NEWS_RECENT = 10

# A página do herói ocupa a faixa inteira do carrossel (hexpand): o
# Adw.Carousel centraliza página mais estreita que ele — sem expandir, a
# folga (largura - página)/2 vira espaço morto nas pontas e o card seguinte
# aparece cortado na borda. O card preenche a página por dentro, e a
# largura natural do título fica com folga para o card em largura total.
# A altura continua fixa (22 px de borda+padding + 170 de imagem + 10 de
# espaçamento + 84 de texto: 2 linhas de título + metadados); a imagem
# absorve o que sobrar quando o título sai em uma linha só.
_NEWS_HERO_IMAGE = 170
_NEWS_HERO_TITLE_CHARS = 60
_NEWS_HERO_HEIGHT = 286

# Idem para os cards da grade. A grade só encaixa mais de um card por linha
# quando a largura *natural* do card é pequena: FlowBox quebra linha pelo
# tamanho natural do filho, e um Gtk.Picture devolve a largura da foto (às
# vezes 800 px). Por isso a moldura da imagem tem tamanho fixo (Gtk.Overlay
# mede pelo filho de trás) e o título tem teto de caracteres (max-width-chars)
# — sem esses dois, o card nunca encolhe e a grade vira coluna única.
_NEWS_CARD_WIDTH = 264
_NEWS_CARD_IMAGE = 120
_NEWS_CARD_TITLE_CHARS = 18

_RECORDER_SOURCES = {
    "portal": "portal",
    "monitor": "screen",
    "window": "focused",
}
_RECORDER_AUDIO_SOURCES = {
    "default_output": ("default_output",),
    "default_input": ("default_input",),
    "both": ("default_output", "default_input"),
    "none": (),
}
_ALLOWED_STREAM_SCHEMES = frozenset({"rtmp", "srt", "http", "https"})


def can_edit_notes(game: Game) -> bool:
    if game.zerado:
        return False
    return game.status == "playing" or bool((game.notes or "").strip())


# Gamepad home helpers (should_confine_gamepad, confirm_hold_exceeded,
# focus_class e constantes) vivem em ``cartridges.controller`` — módulo sem
# GTK, testável sem display — e são reexportados aqui para o `main.py`.
@Gtk.Template(resource_path=shared.PREFIX + "/gtk/window.ui")
class CartridgesWindow(Adw.ApplicationWindow):
    __gtype_name__ = "CartridgesWindow"

    overlay_split_view: Adw.OverlaySplitView = Gtk.Template.Child()
    navigation_view: Adw.NavigationView = Gtk.Template.Child()
    game_mode_home_page: Adw.NavigationPage = Gtk.Template.Child()
    game_mode_avatar: Adw.Avatar = Gtk.Template.Child()
    game_mode_welcome_label: Gtk.Label = Gtk.Template.Child()
    game_mode_continue_button: Gtk.Button = Gtk.Template.Child()
    game_mode_library_button: Gtk.Button = Gtk.Template.Child()
    sidebar_navigation_page: Adw.NavigationPage = Gtk.Template.Child()
    sidebar: Gtk.ListBox = Gtk.Template.Child()
    toast_overlay: Adw.ToastOverlay = Gtk.Template.Child()
    session_overlay: Gtk.Overlay = Gtk.Template.Child()
    session_blocker: Gtk.Box = Gtk.Template.Child()
    session_blocker_label: Gtk.Label = Gtk.Template.Child()
    session_blocker_button: Gtk.Button = Gtk.Template.Child()
    session_return_button: Gtk.Button = Gtk.Template.Child()
    gpu_screen_recorder_button: Gtk.Button = Gtk.Template.Child()
    session_blocker_notes_button: Gtk.MenuButton = Gtk.Template.Child()
    session_blocker_notes_popover: Gtk.Popover = Gtk.Template.Child()
    session_blocker_notes_view: Gtk.TextView = Gtk.Template.Child()
    session_blocker_timer: Gtk.Label = Gtk.Template.Child()
    primary_menu_button: Gtk.MenuButton = Gtk.Template.Child()
    show_sidebar_button: Gtk.Button = Gtk.Template.Child()
    details_view: Gtk.Overlay = Gtk.Template.Child()
    library_page: Adw.NavigationPage = Gtk.Template.Child()
    library_view: Adw.ToolbarView = Gtk.Template.Child()
    library: AnimatedFlowBox = Gtk.Template.Child()
    scrolledwindow: Gtk.ScrolledWindow = Gtk.Template.Child()
    library_overlay: Gtk.Overlay = Gtk.Template.Child()
    library_background_stack: Gtk.Stack = Gtk.Template.Child()
    library_background_a: Gtk.Picture = Gtk.Template.Child()
    library_background_b: Gtk.Picture = Gtk.Template.Child()
    notice_empty: Adw.StatusPage = Gtk.Template.Child()
    notice_no_results: Adw.StatusPage = Gtk.Template.Child()
    search_bar: Gtk.SearchBar = Gtk.Template.Child()
    search_entry: Gtk.SearchEntry = Gtk.Template.Child()
    search_button: Gtk.ToggleButton = Gtk.Template.Child()
    game_mode_keyboard_button: Gtk.Button = Gtk.Template.Child()
    launchers_bar: Gtk.Box = Gtk.Template.Child()
    launchers_box: Gtk.Box = Gtk.Template.Child()

    gamepad_test_page: Adw.NavigationPage = Gtk.Template.Child()
    gamepad_test_device_label: Gtk.Label = Gtk.Template.Child()
    gamepad_test_layout_label: Gtk.Label = Gtk.Template.Child()
    gamepad_visual_slot: Gtk.Box = Gtk.Template.Child()
    gamepad_test_event_label: Gtk.Label = Gtk.Template.Child()
    gamepad_test_buttons: Gtk.FlowBox = Gtk.Template.Child()
    gamepad_test_axis_0: Gtk.Label = Gtk.Template.Child()
    gamepad_test_axis_1: Gtk.Label = Gtk.Template.Child()
    gamepad_test_axis_2: Gtk.Label = Gtk.Template.Child()
    gamepad_test_axis_3: Gtk.Label = Gtk.Template.Child()
    gamepad_test_axis_4: Gtk.Label = Gtk.Template.Child()
    gamepad_test_axis_5: Gtk.Label = Gtk.Template.Child()
    gamepad_test_hat_label: Gtk.Label = Gtk.Template.Child()

    details_page: Adw.NavigationPage = Gtk.Template.Child()
    details_view_toolbar_view: Adw.ToolbarView = Gtk.Template.Child()
    details_view_cover: Gtk.Picture = Gtk.Template.Child()
    details_view_spinner: Adw.Spinner = Gtk.Template.Child()
    details_view_title: Gtk.Label = Gtk.Template.Child()
    details_view_blurred_cover: Gtk.Picture = Gtk.Template.Child()
    details_view_play_button: Gtk.Button = Gtk.Template.Child()
    details_view_play_menu_button: Gtk.MenuButton = Gtk.Template.Child()
    details_view_developer: Gtk.Label = Gtk.Template.Child()
    details_view_metadata: Gtk.Label = Gtk.Template.Child()
    details_view_description: Gtk.Label = Gtk.Template.Child()
    details_view_screenshots_group: Gtk.Box = Gtk.Template.Child()
    details_view_screenshots: Gtk.Box = Gtk.Template.Child()
    details_view_added: Gtk.ShortcutLabel = Gtk.Template.Child()
    details_view_last_played: Gtk.Label = Gtk.Template.Child()
    details_view_size: Gtk.Label = Gtk.Template.Child()
    details_view_update_notice: Gtk.Button = Gtk.Template.Child()
    details_view_playtime: Gtk.Label = Gtk.Template.Child()
    details_view_status_button: Gtk.MenuButton = Gtk.Template.Child()
    details_view_notes_box: Gtk.Box = Gtk.Template.Child()
    details_view_notes: Gtk.Label = Gtk.Template.Child()
    details_view_notes_button: Gtk.MenuButton = Gtk.Template.Child()
    details_view_notes_popover: Gtk.Popover = Gtk.Template.Child()
    details_view_notes_view: Gtk.TextView = Gtk.Template.Child()
    details_view_delete_button: Gtk.Button = Gtk.Template.Child()
    details_view_hide_button: Gtk.Button = Gtk.Template.Child()
    details_view_uzdoom_mods_button: Gtk.Button = Gtk.Template.Child()

    hidden_library_page: Adw.NavigationPage = Gtk.Template.Child()
    hidden_primary_menu_button: Gtk.MenuButton = Gtk.Template.Child()
    hidden_library: Gtk.FlowBox = Gtk.Template.Child()
    hidden_library_view: Adw.ToolbarView = Gtk.Template.Child()
    hidden_scrolledwindow: Gtk.ScrolledWindow = Gtk.Template.Child()
    hidden_library_overlay: Gtk.Overlay = Gtk.Template.Child()
    hidden_notice_empty: Adw.StatusPage = Gtk.Template.Child()
    hidden_notice_no_results: Adw.StatusPage = Gtk.Template.Child()
    hidden_search_bar: Gtk.SearchBar = Gtk.Template.Child()
    hidden_search_entry: Gtk.SearchEntry = Gtk.Template.Child()
    hidden_search_button: Gtk.ToggleButton = Gtk.Template.Child()
    hidden_game_mode_keyboard_button: Gtk.Button = Gtk.Template.Child()

    zerados_library_page: Adw.NavigationPage = Gtk.Template.Child()
    zerados_primary_menu_button: Gtk.MenuButton = Gtk.Template.Child()
    zerados_library: AnimatedFlowBox = Gtk.Template.Child()
    zerados_scrolledwindow: Gtk.ScrolledWindow = Gtk.Template.Child()
    zerados_library_overlay: Gtk.Overlay = Gtk.Template.Child()
    zerados_notice_empty: Adw.StatusPage = Gtk.Template.Child()
    zerados_notice_no_results: Adw.StatusPage = Gtk.Template.Child()

    news_button: Gtk.Button = Gtk.Template.Child()
    news_badge: Gtk.Box = Gtk.Template.Child()
    news_page: Adw.NavigationPage = Gtk.Template.Child()
    news_stack: Gtk.Stack = Gtk.Template.Child()
    news_list: Gtk.ListBox = Gtk.Template.Child()
    news_scrolledwindow: Gtk.ScrolledWindow = Gtk.Template.Child()
    news_refresh_button: Gtk.Button = Gtk.Template.Child()
    news_retry_button: Gtk.Button = Gtk.Template.Child()
    news_status: Adw.StatusPage = Gtk.Template.Child()
    news_sources_button: Gtk.MenuButton = Gtk.Template.Child()
    news_highlights_section: Gtk.Box = Gtk.Template.Child()
    news_highlights_title: Gtk.Label = Gtk.Template.Child()
    news_highlights_carousel: Adw.Carousel = Gtk.Template.Child()
    news_highlights_indicator: Adw.CarouselIndicatorDots = Gtk.Template.Child()
    news_recent_section: Gtk.Box = Gtk.Template.Child()
    news_recent_title: Gtk.Label = Gtk.Template.Child()
    news_recent_flowbox: Gtk.FlowBox = Gtk.Template.Child()
    news_list_section: Gtk.Box = Gtk.Template.Child()
    news_list_title: Gtk.Label = Gtk.Template.Child()
    library_refresh_button: Gtk.Button = Gtk.Template.Child()
    library_refresh_spinner: Adw.Spinner = Gtk.Template.Child()

    game_covers: dict = {}
    toasts: dict = {}
    toast_queue: ToastQueue
    active_game: Game
    news_checker: Optional[Any] = None
    _news_handler_ids: list = []
    _news_refresh_toast: Optional[Adw.Toast] = None
    _news_refresh_requested = False
    _news_source_actions: list = []
    _library_refreshing = False
    _xcloud_refresh_toast: Optional[Adw.Toast] = None
    session_game: Optional[Game] = None
    session_timer_id: int = 0
    _game_overlay_open = False
    _recorder_service: Optional[Any] = None
    _recorder_busy = False
    _recorder_recording = False
    botao_tarefas: BotaoTarefas
    _playtime_clickable = False
    details_view_game_cover: Optional[GameCover] = None
    _details_images_generation: int = 0
    _fundo_biblioteca_geracao: int = 0
    _fundo_biblioteca_jogo: Optional[str] = None
    _fundo_biblioteca_lado: bool = False
    sort_state: str = "last_played"
    active_source_filters: set[str]
    known_source_filters: set[str]
    source_rows: dict
    # Gamepad home/library navigation state. Class-level defaults so the
    # pure helpers and focus tracking stay safe even before __init__ runs.
    _gamepad_nav_active: bool = False
    _gamepad_focus_widget: Optional[Gtk.Widget] = None
    _gamepad_focus_handler: int = 0

    def add_toast(self, toast: Adw.Toast) -> None:
        self.toast_queue.add(toast)

    def _get_disabled_source_filters(self) -> set[str]:
        try:
            return set(shared.schema.get_strv("disabled-source-filters"))
        except Exception:  # pylint: disable=broad-exception-caught
            return set()

    def _save_disabled_source_filters(self) -> None:
        try:
            previous = self._get_disabled_source_filters()
            disabled = (previous | (self.known_source_filters - self.active_source_filters)) - self.active_source_filters
            shared.schema.set_strv("disabled-source-filters", sorted(disabled))
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    def create_source_rows(self) -> None:
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())

        counts: dict[str, int] = {}
        for game in shared.store:
            if game.removed or game.hidden or game.blacklisted:
                continue
            if game.base_source == "xcloud" and not shared.schema.get_boolean(
                "xbox-cloud-gaming"
            ):
                continue
            filter_id = self._source_filter_id(game)
            counts[filter_id] = counts.get(filter_id, 0) + 1

        self.known_source_filters.update(counts)
        disabled = self._get_disabled_source_filters()
        self.active_source_filters = set(counts) - disabled

        while row := self.sidebar.get_row_at_index(1):
            self.sidebar.remove(row)
        self.source_rows.clear()

        def sort_key(item: tuple[str, int]) -> tuple:
            source_id, games_no = item
            priority = {
                "imported": 0,
                "xcloud_gamepass": 1,
                "xcloud_free": 2,
                "xcloud_owned": 3,
            }.get(source_id, 4)
            return (priority, -games_no, self._source_filter_name(source_id).casefold())

        for source_id, games_no in sorted(counts.items(), key=sort_key):
            content = Gtk.Box(
                margin_top=12,
                margin_bottom=12,
                margin_start=6,
                margin_end=6,
                spacing=12,
            )
            content.append(self._source_filter_image(source_id, theme))
            content.append(
                Gtk.Label(
                    label=self._source_filter_name(source_id),
                    halign=Gtk.Align.START,
                    wrap=True,
                    wrap_mode=Pango.WrapMode.CHAR,
                )
            )
            content.append(
                count_label := Gtk.Label(
                    label=str(games_no),
                    hexpand=True,
                    halign=Gtk.Align.END,
                )
            )
            count_label.add_css_class("dim-label")

            button = Gtk.ToggleButton(
                active=source_id in self.active_source_filters,
                child=content,
                hexpand=True,
                css_classes=["flat", "source-filter-toggle"],
                tooltip_text=_("Left click toggles • Right click shows only this"),
            )
            button.connect("toggled", self._source_filter_toggled, source_id)
            right = Gtk.GestureClick.new()
            right.set_button(3)
            right.connect("released", self._on_source_filter_right_click, source_id)
            button.add_controller(right)

            self.sidebar.append(button)
            self.source_rows[button] = (source_id, games_no)

        header = self.sidebar.get_row_at_index(0)
        if header is not None:
            header.set_visible(bool(counts))
        self._update_source_filter_title()
        self.library.invalidate_filter()
        self.set_library_child()
        self.atualizar_launchers()

    @staticmethod
    def _source_filter_id(game: Game) -> str:
        if game.base_source != "xcloud":
            return game.base_source
        if game.source in ("xcloud_free", "xcloud_gamepass", "xcloud_owned"):
            return game.source
        return "xcloud_gamepass"

    def _source_filter_name(self, source_id: str) -> str:
        names = {
            "xcloud_free": _("Xbox Cloud Gaming — Grátis"),
            "xcloud_gamepass": _("Xbox Cloud Gaming — Game Pass"),
            "xcloud_owned": _("Xbox Cloud Gaming — Comprados"),
        }
        return names.get(source_id, self.get_application().get_source_name(source_id))

    def _source_filter_image(
        self, source_id: str, theme: Gtk.IconTheme
    ) -> Gtk.Image:
        if source_id.startswith("xcloud_"):
            image = Gtk.Image.new_from_resource(shared.PREFIX + "/xbox-cloud.png")
            image.set_pixel_size(18)
            return image
        if source_id == "imported":
            return Gtk.Image.new_from_icon_name("list-add-symbolic")
        return Gtk.Image.new_from_icon_name(
            self._icone_disponivel(
                theme,
                launcher.nomes_de_icone_da_fonte(source_id),
            )
        )

    def _membro_visivel_na_biblioteca(self, member: Game) -> bool:
        """Um membro sustenta o card se a fonte está no filtro."""
        return self._source_filter_id(member) in self.active_source_filters

    def _source_filter_toggled(
        self, button: Gtk.ToggleButton, source_id: str
    ) -> None:
        if button.get_active():
            self.active_source_filters.add(source_id)
        else:
            self.active_source_filters.discard(source_id)
        self._save_disabled_source_filters()
        self._update_source_filter_title()
        self.library.invalidate_filter()
        self.set_library_child()

    def _on_source_filter_right_click(
        self,
        _gesture: Gtk.GestureClick,
        _n_press: int,
        _x: float,
        _y: float,
        source_id: str,
    ) -> None:
        """Botão direito isola a plataforma: só ela fica marcada."""
        self._isolate_source_filter(source_id)

    def _isolate_source_filter(self, source_id: str) -> None:
        available = {sid for sid, _count in self.source_rows.values()}
        if source_id not in available:
            return
        if self.active_source_filters == {source_id}:
            return
        self.active_source_filters = {source_id}
        for button, (current_id, _count) in self.source_rows.items():
            is_target = current_id == source_id
            if button.get_active() != is_target:
                button.set_active(is_target)
        self._save_disabled_source_filters()
        self._update_source_filter_title()
        self.library.invalidate_filter()
        self.set_library_child()

    def _update_source_filter_title(self) -> None:
        available = {source_id for source_id, _count in self.source_rows.values()}
        selected = self.active_source_filters & available
        if not available:
            title = _("Biblioteca")
        elif len(selected) == 1:
            title = self._source_filter_name(next(iter(selected)))
        elif selected == available and available:
            title = _("Biblioteca")
        else:
            title = _("{} plataformas").format(len(selected))
        self.library_page.set_title(title)

    def enable_source_filter(self, source_id: str) -> None:
        """Garante que uma plataforma fique visível sem apagar as demais."""
        self.active_source_filters.add(source_id)
        self._save_disabled_source_filters()
        for button, (current_id, _count) in self.source_rows.items():
            if current_id == source_id:
                button.set_active(True)
                break
        self._update_source_filter_title()
        self.library.invalidate_filter()
        self.set_library_child()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.active_source_filters = set()
        self.known_source_filters = set()
        self.source_rows = {}

        # Página Integrações (`app.integrations`): criada na primeira abertura.
        self.integracoes_page: Optional[IntegrationsPage] = None

        # Página de perfis de iluminação: criada na primeira abertura.
        self.lighting_page: Optional[LightingPage] = None

        self._news_thumb_cache: dict[str, Gdk.Texture] = {}
        self._news_thumb_pending: dict[str, list[Gtk.Picture]] = {}
        # Uma ação por fonte, recriadas a cada montagem do menu: as fontes
        # dependem do idioma da interface.
        self._news_source_actions: list[Gio.SimpleAction] = []
        # Os cards do carrossel, guardados para poder removê-los do carrossel
        # quando a página é reconstruída.
        self._news_hero_pages: list[Gtk.Widget] = []

        self.game_mode_home_page.set_visible(shared.runtime.is_game_mode)
        if not shared.runtime.is_game_mode:
            # The landing page is the template's initial navigation root.
            # Hiding it is not enough: leaving it below the library makes
            # HeaderBar expose a Back button that pops to an invisible page.
            self.navigation_view.replace([self.library_page])
        elif shared.schema.get_boolean("game-mode-start-library"):
            self.navigation_view.push(self.library_page)

        self.details_view.set_measure_overlay(self.details_view_toolbar_view, True)
        self.details_view.set_clip_overlay(self.details_view_toolbar_view, False)

        self.library.set_filter_func(self.filter_func)
        self.hidden_library.set_filter_func(self.filter_func)
        self.zerados_library.set_filter_func(self.filter_func)

        self.library.set_sort_func(self.sort_func)
        self.hidden_library.set_sort_func(self.sort_func)
        self.zerados_library.set_sort_func(self.sort_func)
        self.zerados_library.set_max_children_per_line(999)

        attach_spring_scroll(
            self.scrolledwindow, self.hidden_scrolledwindow, self.zerados_scrolledwindow
        )

        self.toast_queue = ToastQueue(self.toast_overlay)

        self.botao_tarefas = BotaoTarefas(self)
        self.session_overlay.add_overlay(self.botao_tarefas)
        tarefas.lista.connect("items-changed", self.botao_tarefas.ao_mudar_lista)
        self.navigation_view.connect("notify::visible-page", self.botao_tarefas.reavaliar)
        self.connect("notify::visible-dialog", self.botao_tarefas.reavaliar)
        self.session_blocker_button.connect("clicked", self.on_session_blocker_clicked)
        self.session_return_button.connect("clicked", self.return_to_game)
        self.gpu_screen_recorder_button.connect(
            "clicked", self.open_gpu_screen_recorder
        )
        self._recorder_replay_gesture = Gtk.GestureClick()
        self._recorder_replay_gesture.set_button(Gdk.BUTTON_SECONDARY)
        self._recorder_replay_gesture.connect("pressed", self.on_save_recorder_replay)
        self.gpu_screen_recorder_button.add_controller(self._recorder_replay_gesture)
        self.session_blocker_notes_popover.connect(
            "notify::visible", self.on_session_notes_popover_toggled
        )

        add_zerado = Gio.SimpleAction.new("add_zerado", None)
        add_zerado.connect("activate", lambda *_: ZeradosPicker().present(self))
        self.add_action(add_zerado)

        launch_via = Gio.SimpleAction.new("launch_via", GLib.VariantType.new("s"))
        launch_via.connect("activate", self.on_launch_via_action)
        self.add_action(launch_via)

        desagrupar = Gio.SimpleAction.new("desagrupar", GLib.VariantType.new("s"))
        desagrupar.connect("activate", self.on_desagrupar_action)
        self.add_action(desagrupar)

        reagrupar = Gio.SimpleAction.new("reagrupar", GLib.VariantType.new("s"))
        reagrupar.connect("activate", self.on_reagrupar_action)
        self.add_action(reagrupar)

        toggle_launcher = Gio.SimpleAction.new(
            "toggle_launcher", GLib.VariantType.new("s")
        )
        toggle_launcher.connect("activate", self.on_toggle_launcher_action)
        self.add_action(toggle_launcher)

        set_status = Gio.SimpleAction.new("set_status", GLib.VariantType.new("s"))
        set_status.connect("activate", self.on_set_status_action)
        self.add_action(set_status)

        delete_game = Gio.SimpleAction.new("delete_game", None)
        delete_game.connect("activate", self.on_delete_game_action)
        self.add_action(delete_game)

        uzdoom_mods = Gio.SimpleAction.new("uzdoom_mods", None)
        uzdoom_mods.connect("activate", self.on_uzdoom_mods_action)
        self.add_action(uzdoom_mods)

        shared.schema.bind(
            "show-news-button",
            self.news_button,
            "visible",
            Gio.SettingsBindFlags.GET,
        )
        shared.schema.connect(
            "changed::xbox-cloud-gaming", self._xcloud_enabled_changed
        )
        self.news_refresh_button.connect("clicked", self.on_news_refresh_clicked)
        self.news_retry_button.connect("clicked", self.on_news_refresh_clicked)
        self.library_refresh_button.connect(
            "clicked", self._on_library_refresh_clicked
        )

        self.set_library_child()

        self.notice_empty.set_icon_name(shared.APP_ID + "-symbolic")

        self.overlay_split_view.set_show_sidebar(
            shared.state_schema.get_boolean("show-sidebar")
        )

        if shared.PROFILE == "development":
            self.add_css_class("devel")

        # Connect search entries
        self.search_bar.connect_entry(self.search_entry)
        self.hidden_search_bar.connect_entry(self.hidden_search_entry)

        # Connect signals
        self.search_entry.connect("search-changed", self.search_changed, False)
        self.hidden_search_entry.connect("search-changed", self.search_changed, True)

        for button, entry in (
            (self.game_mode_keyboard_button, self.search_entry),
            (self.hidden_game_mode_keyboard_button, self.hidden_search_entry),
        ):
            # Controller input is supported in both the desktop and Gaming
            # Mode interfaces, so controller-only text entry must be too.
            button.set_visible(True)
            button.connect("clicked", self.show_gamepad_keyboard, entry)

        self.search_entry.connect("activate", self.show_details_page_search)
        self.hidden_search_entry.connect("activate", self.show_details_page_search)
        self.details_view_update_notice.connect(
            "clicked", self.on_update_notice_clicked
        )
        self.details_view_notes_popover.connect(
            "notify::visible", self.on_notes_popover_toggled
        )
        click = Gtk.GestureClick.new()
        click.connect("released", self.on_playtime_activated)
        self.details_view_playtime.add_controller(click)

        self.navigation_view.connect("popped", self.set_show_hidden)
        self.navigation_view.connect("pushed", self.set_show_hidden)
        self.navigation_view.connect("popped", self._schedule_library_refocus)
        self.navigation_view.connect("pushed", self._schedule_library_refocus)
        self.navigation_view.connect(
            "notify::visible-page", self._schedule_library_refocus
        )

        for grade in (self.library, self.hidden_library, self.zerados_library):
            grade.connect("child-activated", self.on_library_child_activated)

        self._gamepad_button_widgets = {}
        for code in (304, 305, 307, 308, 310, 311, 314, 315, 316, 317, 318):
            label = Gtk.Label(
                label=name_for_button(code),
                width_request=92,
                height_request=44,
                css_classes=["gamepad-input"],
            )
            self._gamepad_button_widgets[code] = label
            self.gamepad_test_buttons.append(label)

        self._gamepad_visual = None
        try:
            self._gamepad_visual = GamepadVisual()
            self.gamepad_visual_slot.append(self._gamepad_visual)
        except Exception:  # A falha do visual não pode quebrar a janela.
            logging.exception("Could not build the gamepad visual")
            self._gamepad_visual = None

        style_manager = Adw.StyleManager.get_default()
        style_manager.connect("notify::dark", self.set_details_view_opacity)
        style_manager.connect("notify::high-contrast", self.set_details_view_opacity)

        # Allow for a custom number of rows for the library
        if shared.schema.get_uint("library-rows"):
            shared.schema.bind(
                "library-rows",
                self.library,
                "max-children-per-line",
                Gio.SettingsBindFlags.DEFAULT,
            )
            shared.schema.bind(
                "library-rows",
                self.hidden_library,
                "max-children-per-line",
                Gio.SettingsBindFlags.DEFAULT,
            )
        else:
            self.library.set_max_children_per_line(10)
            self.hidden_library.set_max_children_per_line(10)

    def configure_user_profile(self, profile: Any) -> None:
        self.game_mode_welcome_label.set_label(
            _("Welcome, {}").format(profile.display_name)
        )
        self.game_mode_avatar.set_text(profile.display_name)
        if profile.avatar is not None:
            try:
                self.game_mode_avatar.set_custom_image(
                    Gdk.Texture.new_from_filename(str(profile.avatar))
                )
            except GLib.Error:
                pass

    def update_game_mode_home(self) -> None:
        games = [
            game
            for game in shared.store
            if not game.removed and game.executable and game.last_played > 0
        ]
        recent = max(games, key=lambda game: game.last_played, default=None)
        self.game_mode_continue_button.set_sensitive(recent is not None)
        self.game_mode_continue_button.set_tooltip_text(
            recent.name if recent is not None else _("No recently played game")
        )

    def focus_game_mode_home(self) -> None:
        if self.navigation_view.get_visible_page() == self.game_mode_home_page:
            (
                self.game_mode_continue_button
                if self.game_mode_continue_button.get_sensitive()
                else self.game_mode_library_button
            ).grab_focus()

    def on_open_library_action(self, *_args: Any) -> None:
        if self.navigation_view.get_visible_page() != self.library_page:
            self.navigation_view.push(self.library_page)
        GLib.idle_add(self.focus_first_library_tile)

    def gamepad_back(self) -> None:
        dialog = self.get_visible_dialog()
        if dialog is not None:
            dialog.close()
        elif self._game_overlay_open and self.session_game is not None:
            self.return_to_game()
        elif self.navigation_view.get_visible_page() not in (
            self.game_mode_home_page,
            self.library_page,
        ):
            self.navigation_view.pop()
        elif (
            shared.runtime.is_game_mode
            and self.navigation_view.get_visible_page() == self.library_page
        ):
            self.navigation_view.pop()

    @property
    def gamepad_test_active(self) -> bool:
        return self.navigation_view.get_visible_page() == self.gamepad_test_page

    def on_open_gamepad_test_action(self, *_args: Any) -> None:
        if not self.gamepad_test_active:
            self.navigation_view.push(self.gamepad_test_page)

    def close_gamepad_test(self) -> None:
        if self.gamepad_test_active:
            self.navigation_view.pop()

    def set_gamepad_devices(self, names: list[str]) -> None:
        self.gamepad_test_device_label.set_label(
            _("Conectado: {}").format(", ".join(names))
            if names
            else _("Nenhum gamepad conectado")
        )
        layout = (
            detect_controller_layout(names[0]).value if names else "generic"
        )
        badge = {
            "xbox": _("Controle Xbox"),
            "playstation": _("Controle PlayStation"),
            "generic": _("Controle genérico"),
        }.get(layout, _("Controle genérico"))
        if not names:
            badge = _("Layout não identificado")
        try:
            self.gamepad_test_layout_label.set_label(badge)
        except AttributeError:
            pass
        if self._gamepad_visual is not None:
            try:
                self._gamepad_visual.set_layout(layout)
            except Exception:
                logging.exception("Could not apply the gamepad layout")

    def update_gamepad_button(self, button: int, pressed: bool) -> None:
        name = name_for_button(button)
        self.gamepad_test_event_label.set_label(
            _("{} pressionado").format(name)
            if pressed
            else _("{} solto").format(name)
        )
        label = self._gamepad_button_widgets.get(button)
        if label is None:
            label = Gtk.Label(
                label=name,
                width_request=92,
                height_request=44,
                css_classes=["gamepad-input"],
            )
            self._gamepad_button_widgets[button] = label
            self.gamepad_test_buttons.append(label)
        if pressed:
            label.add_css_class("active")
        else:
            label.remove_css_class("active")
        if self._gamepad_visual is not None:
            try:
                self._gamepad_visual.set_button_pressed(button, pressed)
            except Exception:
                logging.exception("Could not update the gamepad visual")

    def update_gamepad_axis(self, axis: int, value: float) -> None:
        self.gamepad_test_event_label.set_label(
            _("Eixo {}: {:.2f}").format(axis, value)
        )
        label = getattr(self, f"gamepad_test_axis_{axis}", None)
        if label is not None:
            label.set_label(f"{value:+.2f}")
        if self._gamepad_visual is not None:
            try:
                self._gamepad_visual.set_axis(axis, value)
            except Exception:
                logging.exception("Could not update the gamepad visual")

    def update_gamepad_trigger(self, trigger: str, pressed: bool) -> None:
        """Reflect digital trigger events in the trigger axis rows."""
        value = 1.0 if pressed else 0.0
        axis = 2 if trigger == "LT" else 5
        getattr(self, f"gamepad_test_axis_{axis}").set_label(f"{value:.2f}")
        self.gamepad_test_event_label.set_label(
            _("{}: {:.2f}").format(trigger, value)
        )
        if self._gamepad_visual is not None:
            try:
                self._gamepad_visual.set_trigger(trigger, pressed)
            except Exception:
                logging.exception("Could not update the gamepad visual")

    def update_gamepad_hat(self, axis: int, value: int) -> None:
        directions = {
            15: _("esquerda"),
            16: _("cima"),
            17: _("direita"),
            18: _("baixo"),
        }
        direction = (
            _("centralizado")
            if value == 0
            else directions.get(axis + value, str(value))
        )
        self.gamepad_test_hat_label.set_label(
            _("Direcional {}: {}").format(axis, direction)
        )
        self.gamepad_test_event_label.set_label(
            _("Direcional: {}").format(direction)
        )
        if self._gamepad_visual is not None:
            try:
                self._gamepad_visual.set_hat(axis, value)
            except Exception:
                logging.exception("Could not update the gamepad visual")

    def gamepad_search(self) -> None:
        """Go to the library if needed and open the on-screen keyboard.

        Physical keyboard search keeps using ``on_toggle_search_action``
        directly; this gamepad path always ends with the keyboard dialog
        focused on the visible search entry.
        """
        page = self.navigation_view.get_visible_page()
        if page not in (self.library_page, self.hidden_library_page):
            if page == self.game_mode_home_page:
                self.navigation_view.push(self.library_page)
            else:
                self.navigation_view.pop_to_page(self.library_page)
        page = self.navigation_view.get_visible_page()
        if page == self.hidden_library_page:
            search_bar = self.hidden_search_bar
            search_entry = self.hidden_search_entry
        else:
            if page != self.library_page:
                self.navigation_view.pop_to_page(self.library_page)
            search_bar = self.search_bar
            search_entry = self.search_entry
        if not search_bar.get_search_mode():
            search_bar.set_search_mode(True)
        search_entry.set_text("")
        try:
            self.set_focus(search_entry)
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        self.show_gamepad_keyboard(None, search_entry)

    @staticmethod
    def _game_from_widget(widget: Gtk.Widget | None) -> Game | None:
        while widget is not None:
            if isinstance(widget, Game):
                return widget
            if isinstance(widget, Gtk.FlowBoxChild) and isinstance(
                widget.get_child(), Game
            ):
                return widget.get_child()
            widget = widget.get_parent()
        return None

    def _game_from_focus(self) -> Game | None:
        return self._game_from_widget(self.get_focus())

    def _focus_in_library_chrome(self) -> bool:
        widget = self.get_focus()
        while widget is not None:
            if widget in (
                self.search_entry,
                self.hidden_search_entry,
                self.launchers_bar,
                self.sidebar,
            ):
                return True
            widget = widget.get_parent()
        return False

    def get_visible_library(self) -> Gtk.FlowBox | None:
        page = self.navigation_view.get_visible_page()
        if page == self.library_page:
            return self.library
        if page == self.hidden_library_page:
            return self.hidden_library
        if page == self.zerados_library_page:
            return self.zerados_library
        return None

    def focus_first_library_tile(self) -> bool:
        grade = self.get_visible_library()
        if grade is None:
            return GLib.SOURCE_REMOVE
        index = 0
        while child := grade.get_child_at_index(index):
            index += 1
            if not child.get_visible():
                continue
            child.grab_focus()
            if isinstance(child.get_child(), Game):
                self.atualizar_fundo_biblioteca(child.get_child())
            return GLib.SOURCE_REMOVE
        if first_launcher := self.launchers_box.get_first_child():
            first_launcher.grab_focus()
        return GLib.SOURCE_REMOVE

    def _gamepad_sidebar_open(self) -> bool:
        """Whether the sidebar (overlay_split_view) is currently open."""
        try:
            return bool(self.overlay_split_view.get_show_sidebar())
        except Exception:  # pylint: disable=broad-exception-caught
            return False

    def _gamepad_library_page_id(self) -> str:
        """Id of the visible library page, or ``""`` when off-library."""
        try:
            page = self.navigation_view.get_visible_page()
        except Exception:  # pylint: disable=broad-exception-caught
            return ""
        if page == self.library_page:
            return "library"
        if page == self.hidden_library_page:
            return "hidden"
        if page == self.zerados_library_page:
            return "zerados"
        return ""

    def _is_library_page(self) -> bool:
        return self._gamepad_library_page_id() != ""

    def _gamepad_focus_classes(self) -> tuple:
        return (GAMEPAD_TILE_FOCUS_RGB_CLASS, GAMEPAD_TILE_FOCUS_CLASS)

    def _gamepad_glows_active(self) -> bool:
        try:
            app = self.get_application()
            manager = getattr(app, "theme_manager", None)
            return bool(getattr(manager, "glows", False))
        except Exception:  # pylint: disable=broad-exception-caught
            return False

    def _launcher_button_from_widget(
        self, widget: Gtk.Widget | None
    ) -> Optional[Gtk.Button]:
        while widget is not None:
            if isinstance(widget, Gtk.Button) and getattr(
                widget, "_jolven_launcher_game", None
            ) is not None:
                return widget
            try:
                if widget is self.launchers_box:
                    return None
            except AttributeError:
                return None
            widget = widget.get_parent()
        return None

    def _launcher_from_focus(self) -> tuple:
        """Focused launcher ``(button, game)`` or ``(None, None)``."""
        button = self._launcher_button_from_widget(self.get_focus())
        if button is None:
            return (None, None)
        return (button, getattr(button, "_jolven_launcher_game", None))

    def _gamepad_clear_focus_highlight(self) -> None:
        widget = getattr(self, "_gamepad_focus_widget", None)
        if widget is not None:
            for css in self._gamepad_focus_classes():
                try:
                    widget.remove_css_class(css)
                except Exception:  # pylint: disable=broad-exception-caught
                    pass
        handler = getattr(self, "_gamepad_focus_handler", 0)
        self._gamepad_focus_widget = None
        self._gamepad_focus_handler = 0
        if handler and widget is not None:
            try:
                widget.disconnect(handler)
            except Exception:  # pylint: disable=broad-exception-caught
                pass

    def _gamepad_on_focus_lost(self, widget: Gtk.Widget, _pspec: Any) -> None:
        try:
            has_focus = bool(widget.has_focus())
        except Exception:  # pylint: disable=broad-exception-caught
            has_focus = False
        if not has_focus and widget is getattr(self, "_gamepad_focus_widget", None):
            self._gamepad_clear_focus_highlight()

    def _gamepad_track_focus(self) -> None:
        """Re-apply the gamepad focus ring to the focused tile/launcher."""
        self._gamepad_clear_focus_highlight()
        if not getattr(self, "_gamepad_nav_active", False):
            return
        try:
            if self.get_visible_dialog() is not None:
                return
            if self.gamepad_test_active:
                return
        except Exception:  # pylint: disable=broad-exception-caught
            return
        if not self._is_library_page():
            return
        focus = self.get_focus()
        target = None
        if self._game_from_widget(focus) is not None:
            target = focus
        else:
            button, game = self._launcher_from_focus()
            if button is not None and game is not None:
                target = button
        if target is None:
            return
        try:
            target.add_css_class(focus_class(self._gamepad_glows_active()))
        except Exception:  # pylint: disable=broad-exception-caught
            return
        self._gamepad_focus_widget = target
        try:
            self._gamepad_focus_handler = target.connect(
                "notify::has-focus", self._gamepad_on_focus_lost
            )
        except Exception:  # pylint: disable=broad-exception-caught
            self._gamepad_focus_handler = 0

    def gamepad_navigate(self, direction: Gtk.DirectionType) -> None:
        self._gamepad_nav_active = True
        if self.get_visible_dialog() is not None:
            self.child_focus(direction)
            self._gamepad_track_focus()
            return
        try:
            busy = self.gamepad_test_active
        except Exception:  # pylint: disable=broad-exception-caught
            busy = False
        if busy:
            self.child_focus(direction)
            self._gamepad_track_focus()
            return
        if not should_confine_gamepad(
            self._gamepad_sidebar_open(), self._gamepad_library_page_id()
        ):
            moved = self.child_focus(direction)
            if (game := self._game_from_focus()) is not None:
                self.atualizar_fundo_biblioteca(game)
            elif not moved and self.get_visible_library() is not None:
                self.focus_first_library_tile()
            self._gamepad_track_focus()
            return
        previous = self.get_focus()
        self.child_focus(direction)
        game = self._game_from_focus()
        _button, launcher_game = self._launcher_from_focus()
        if game is not None or launcher_game is not None:
            if game is not None:
                self.atualizar_fundo_biblioteca(game)
            self._gamepad_track_focus()
            return
        # Focus escaped to the sidebar/search/header or got lost:
        # send it back to the previous tile/launcher when possible.
        restored = False
        if previous is not None and (
            self._game_from_widget(previous) is not None
            or self._launcher_button_from_widget(previous) is not None
        ):
            try:
                previous.grab_focus()
                restored = True
            except Exception:  # pylint: disable=broad-exception-caught
                restored = False
        if not restored:
            self.focus_first_library_tile()
        elif (game := self._game_from_focus()) is not None:
            self.atualizar_fundo_biblioteca(game)
        self._gamepad_track_focus()

    def gamepad_confirm(self) -> None:
        """Tap on confirm (legacy entry point): open, never launch."""
        self.gamepad_confirm_tap()

    def gamepad_confirm_tap(self) -> None:
        """Single tap: open the focused game, launch a focused launcher."""
        if (game := self._game_from_focus()) is not None:
            self.show_details_page(game)
            return
        button, launcher_game = self._launcher_from_focus()
        if launcher_game is not None:
            try:
                self.on_launcher_clicked(button, launcher_game)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("Could not launch from the gamepad")
            return
        if (focus := self.get_focus()) is not None:
            try:
                focus.activate()
            except Exception:  # pylint: disable=broad-exception-caught
                pass

    def gamepad_confirm_pressed(self) -> bool:
        """Whether main.py must arm the hold-to-launch timer.

        Returns True only when a game tile or launcher is focused and no
        dialog, tester, xCloud input or game overlay owns the input. Every
        other focus keeps the immediate tap behaviour.
        """
        try:
            if self.gamepad_test_active:
                return False
            if self._game_overlay_open and self.session_game is not None:
                return False
            if self.get_visible_dialog() is not None:
                return False
        except Exception:  # pylint: disable=broad-exception-caught
            return False
        if self._game_from_focus() is not None:
            return True
        _button, launcher_game = self._launcher_from_focus()
        return launcher_game is not None

    def gamepad_confirm_hold(self) -> None:
        """Hold threshold reached: launch the focused game directly."""
        try:
            if self.gamepad_test_active:
                return
            if self._game_overlay_open and self.session_game is not None:
                return
            if self.get_visible_dialog() is not None:
                return
        except Exception:  # pylint: disable=broad-exception-caught
            return
        if (game := self._game_from_focus()) is not None:
            try:
                self.launch_library_game(game)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("Could not launch the game from the gamepad")
            return
        button, launcher_game = self._launcher_from_focus()
        if launcher_game is not None:
            try:
                self.on_launcher_clicked(button, launcher_game)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("Could not launch from the gamepad")

    def gamepad_confirm_released(self, held: bool) -> None:
        """Release after a press: tap opens, hold already launched."""
        if held:
            return
        self.gamepad_confirm_tap()

    def on_library_child_activated(
        self, _flowbox: Gtk.FlowBox, child: Gtk.FlowBoxChild
    ) -> None:
        if isinstance(child.get_child(), Game):
            self.show_details_page(child.get_child())

    def _schedule_library_refocus(self, *_args: Any) -> None:
        GLib.idle_add(self._refocus_library_if_needed)

    def _refocus_library_if_needed(self) -> bool:
        page = self.navigation_view.get_visible_page()
        if page == self.game_mode_home_page:
            self.focus_game_mode_home()
        elif self.get_visible_library() is not None:
            if (
                self._game_from_focus() is None
                and not self._focus_in_library_chrome()
            ):
                self.focus_first_library_tile()
        else:
            self._gamepad_nav_active = False
            self._gamepad_clear_focus_highlight()
        return GLib.SOURCE_REMOVE

    def gamepad_game_menu(self) -> None:
        if (game := self._game_from_focus()) is not None:
            try:
                game.menu_revealer.set_reveal_child(True)
                game.menu_button.popup()
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("Could not open the game menu")
            return
        button, launcher_game = self._launcher_from_focus()
        if button is not None and launcher_game is not None:
            try:
                self.on_launcher_menu(None, 0, 0.0, 0.0, launcher_game, button)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("Could not open the launcher menu")

    def gamepad_main_menu(self) -> None:
        page = self.navigation_view.get_visible_page()
        if page == self.library_page:
            button = self.primary_menu_button
        elif page == self.hidden_library_page:
            button = self.hidden_primary_menu_button
        elif page == self.zerados_library_page:
            button = self.zerados_primary_menu_button
        else:
            # Off-library: keep the minimal fallback (a no-op outside the
            # library pages) without touching pages, sidebar, tester,
            # xCloud or the game overlay.
            GLib.idle_add(self.on_open_menu_action)
            return
        try:
            button.popup()
        except Exception:  # pylint: disable=broad-exception-caught
            return
        try:
            button.grab_focus()
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        GLib.idle_add(self._focus_app_menu_popover, button)

    def _focus_app_menu_popover(self, button: Gtk.MenuButton) -> bool:
        try:
            popover = button.get_popover()
            if popover is not None:
                popover.grab_focus()
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        return GLib.SOURCE_REMOVE

    def gamepad_toggle_sidebar(self) -> None:
        self.on_show_sidebar_action()
        try:
            if self._gamepad_sidebar_open():
                self._gamepad_nav_active = False
                self._gamepad_clear_focus_highlight()
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    def show_gamepad_keyboard(
        self, _button: Gtk.Button, entry: Gtk.SearchEntry
    ) -> None:
        """Show the full on-screen keyboard for controller-only entry."""
        dialog = OnscreenKeyboardDialog(entry)
        dialog.present(self)
        GLib.idle_add(dialog.focus_first_key)

    def search_changed(self, _widget: Any, hidden: bool) -> None:
        # Refresh search filter on keystroke in search box
        (self.hidden_library if hidden else self.library).invalidate_filter()
        self.set_library_child()

    def _refresh_library_filters(self) -> None:
        self.library.invalidate_filter()
        self.hidden_library.invalidate_filter()
        self.zerados_library.invalidate_filter()
        self.set_library_child()

    def set_library_child(self) -> None:
        child, hidden_child, zerados_child = (
            self.notice_empty,
            self.hidden_notice_empty,
            self.zerados_notice_empty,
        )

        for game in shared.store:
            if game.blacklisted or restauracao.e_pendente(game.game_id):
                continue
            if game.base_source == "xcloud" and not shared.schema.get_boolean(
                "xbox-cloud-gaming"
            ):
                continue
            if game.is_launcher and not game.hidden:
                continue
            if game.removed:
                if not game.zerado:
                    continue
                if game.filtered and zerados_child:
                    zerados_child = self.zerados_notice_no_results
                    continue
                zerados_child = None
            elif game.hidden:
                if game.filtered and hidden_child:
                    hidden_child = self.hidden_notice_no_results
                    continue
                hidden_child = None
            else:
                if game.filtered and child:
                    child = self.notice_no_results
                    continue
                child = None

        def remove_from_overlay(widget: Gtk.Widget) -> None:
            if isinstance(widget.get_parent(), Gtk.Overlay):
                widget.get_parent().remove_overlay(widget)

        if child:
            self.library_overlay.add_overlay(child)
        else:
            remove_from_overlay(self.notice_empty)
            remove_from_overlay(self.notice_no_results)

        if hidden_child:
            self.hidden_library_overlay.add_overlay(hidden_child)
        else:
            remove_from_overlay(self.hidden_notice_empty)
            remove_from_overlay(self.hidden_notice_no_results)

        for notice in (self.zerados_notice_empty, self.zerados_notice_no_results):
            if notice is not zerados_child:
                remove_from_overlay(notice)
        if zerados_child:
            self.zerados_library_overlay.add_overlay(zerados_child)

    def filter_func(self, child: Gtk.Widget) -> bool:
        game = child.get_child()
        if restauracao.e_pendente(game.game_id):
            return False
        parent = child.get_parent()
        em_zerados = parent is self.zerados_library if parent else game.zerado
        text = (
            ""
            if em_zerados
            else (
                (
                    self.hidden_search_entry
                    if self.navigation_view.get_visible_page()
                    == self.hidden_library_page
                    else self.search_entry
                )
                .get_text()
                .lower()
            )
        )

        members = [game] if em_zerados else agrupamento.membros(game)

        def casa(member: Game) -> bool:
            return (
                text in member.name.lower()
                or (text in member.developer.lower() if member.developer else False)
                or (text in member.publisher.lower() if member.publisher else False)
                or (text in member.notes.lower() if member.notes else False)
            )

        filtered = text != "" and not any(casa(member) for member in members)

        if not filtered and not em_zerados:
            if not any(
                self._membro_visivel_na_biblioteca(member) for member in members
            ):
                filtered = True

        game.filtered = filtered

        return not filtered

    def set_active_game(self, _widget: Any, _pspec: Any, game: Game) -> None:
        self.active_game = game

    def _atualizar_botao_jogar_detalhes(self, game: Game) -> None:
        """Mostra a seta de launchers ao lado do Jogar se o jogo é agrupado.

        Sem grupo, a seta fica oculta e o botão Jogar é exatamente o de
        antes (``app.launch_game`` lança o primário: preferido ou último
        jogado). Com grupo, a seta abre as variantes via ``win.launch_via``,
        que salva o preferido e lança a variante escolhida.
        """
        try:
            members = agrupamento.membros(game)
        except Exception:  # pylint: disable=broad-except
            members = [game]
        if len(members) < 2:
            self.details_view_play_menu_button.set_visible(False)
            self.details_view_play_menu_button.set_menu_model(None)
            return
        try:
            primario = agrupamento.primario(members)
        except Exception:  # pylint: disable=broad-except
            primario = game
        vias = Gio.Menu()
        ordenados = sorted(
            members, key=lambda m: (m.game_id != primario.game_id, (m.name or "").casefold())
        )
        for member in ordenados:
            try:
                fonte = self.get_application().get_source_name(member.source)
            except Exception:  # pylint: disable=broad-except
                fonte = member.source
            rotulo = str(fonte or member.source)
            if member.game_id == primario.game_id:
                # The variable is the launcher/source name of the default variant
                rotulo = _("{} (last played)").format(rotulo)
            item = Gio.MenuItem.new(rotulo, None)
            item.set_action_and_target_value(
                "win.launch_via", GLib.Variant("s", member.game_id)
            )
            vias.append_item(item)
        menu = Gio.Menu()
        # The variable is the section title listing the launchers
        menu.append_section(_("Jogar via"), vias)
        self.details_view_play_menu_button.set_menu_model(menu)
        self.details_view_play_menu_button.set_visible(True)

    def show_details_page(self, game: Game) -> None:
        self.active_game = game
        self._atualizar_botao_jogar_detalhes(game)
        self.details_view_play_button.set_icon_name("")
        self.details_view_play_button.set_label(_("Play"))
        self.details_view_play_button.set_tooltip_text(None)

        self.details_view_cover.set_opacity(int(not game.loading))
        self.details_view_spinner.set_visible(game.loading)

        self.details_view_developer.set_label(game.developer or "")
        self.details_view_developer.set_visible(bool(game.developer))

        metadata = []
        if game.tgdb_platform:
            metadata.append(_("Plataforma: {}").format(game.tgdb_platform))
        if game.release_date:
            metadata.append(_("Lançamento: {}").format(game.release_date))
        if game.publisher:
            metadata.append(_("Publicadora: {}").format(game.publisher))
        if game.genre:
            metadata.append(_("Gênero: {}").format(game.genre))
        if game.tgdb_players:
            metadata.append(_("Jogadores: {}").format(game.tgdb_players))
        if game.tgdb_age_rating:
            metadata.append(_("Classificação: {}").format(game.tgdb_age_rating))
        if game.tgdb_coop:
            metadata.append(_("Cooperativo: {}").format(game.tgdb_coop))
        self.details_view_metadata.set_label("  •  ".join(metadata))
        self.details_view_metadata.set_visible(bool(metadata))

        description = (game.description or "").strip()
        self.details_view_description.set_label(description)
        self.details_view_description.set_visible(bool(description))
        self._load_details_screenshots(game)

        icon, text = "view-conceal-symbolic", _("Hide")
        if game.hidden:
            icon, text = "view-reveal-symbolic", _("Unhide")

        self.details_view_hide_button.set_icon_name(icon)
        self.details_view_hide_button.set_tooltip_text(text)

        # Only the Doom-family games have mods to choose from.
        self.details_view_uzdoom_mods_button.set_visible(
            game.base_source == "uzdoom"
        )

        if self.details_view_game_cover:
            self.details_view_game_cover.pictures.remove(self.details_view_cover)

        self.details_view_game_cover = game.game_cover
        self.details_view_game_cover.add_picture(self.details_view_cover)

        self.details_view_blurred_cover.set_paintable(
            self.details_view_game_cover.get_blurred()
        )

        self.details_view_title.set_label(game.name)
        self.details_page.set_title(game.name)

        date = relative_date(game.added)
        self.details_view_added.set_label(
            # The variable is the date when the game was added
            _("Added: {}").format(date)
        )
        last_played_date = (
            relative_date(game.last_played) if game.last_played else _("Never")
        )
        self.details_view_last_played.set_label(
            # The variable is the date when the game was last played
            _("Last played: {}").format(last_played_date)
        )
        self.update_details_notice(game)
        self.update_install_size_label(game)
        self.update_status_button(game)
        self.update_notes_block(game)
        self.update_playtime_label(game)

        if self.navigation_view.get_visible_page() != self.details_page:
            self.navigation_view.push(self.details_page)
            self.set_focus(self.details_view_play_button)

        self.set_details_view_opacity()

    def _load_details_screenshots(self, game: Game) -> None:
        """Populate cached TheGamesDB screenshots without blocking GTK."""
        self._details_images_generation += 1
        generation = self._details_images_generation
        while child := self.details_view_screenshots.get_first_child():
            self.details_view_screenshots.remove(child)

        urls = list(game.tgdb_screenshots or [])[:6]
        self.details_view_screenshots_group.set_visible(bool(urls))
        if not urls:
            return

        cache_dir = shared.cache_dir / "jolven" / "thegamesdb" / game.game_id

        def worker() -> None:
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                return
            for url in urls:
                suffix = Path(urlparse(url).path).suffix.lower()
                if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
                    suffix = ".jpg"
                filename = hashlib.sha256(url.encode("utf-8")).hexdigest() + suffix
                path = cache_dir / filename
                try:
                    if not path.is_file():
                        path.write_bytes(download_bytes(url, timeout=20))
                except Exception as error:  # pylint: disable=broad-except
                    logging.info("Could not load TheGamesDB screenshot: %s", error)
                    continue
                GLib.idle_add(self._add_details_screenshot, path, game, generation)

        threading.Thread(target=worker, daemon=True).start()

    def _add_details_screenshot(
        self, path: Path, game: Game, generation: int
    ) -> bool:
        if generation != self._details_images_generation or self.active_game is not game:
            return GLib.SOURCE_REMOVE
        try:
            texture = Gdk.Texture.new_from_filename(str(path))
        except GLib.Error as error:
            logging.info("Invalid TheGamesDB screenshot: %s", error)
            path.unlink(missing_ok=True)
            return GLib.SOURCE_REMOVE
        picture = Gtk.Picture(paintable=texture)
        picture.set_content_fit(Gtk.ContentFit.COVER)
        picture.set_size_request(240, 135)
        picture.set_overflow(Gtk.Overflow.HIDDEN)
        picture.add_css_class("card")
        self.details_view_screenshots.append(picture)
        return GLib.SOURCE_REMOVE

    def atualizar_fundo_biblioteca(self, game: Game) -> None:
        """Troca o fundo da grade para a arte do jogo em foco, sem bloquear.

        Resolve fora da UI (rede: IGDB → TheGamesDB → wallhaven) e aplica na
        volta com guarda de geração: se o foco já mudou, o resultado vencido
        é descartado. Em caso de falha, não faz nada — o fundo fica como está.
        """
        self._fundo_biblioteca_geracao += 1
        geracao = self._fundo_biblioteca_geracao
        self._fundo_biblioteca_jogo = game.game_id

        def worker() -> None:
            try:
                caminho = resolver_fundo(game)
            except Exception as erro:  # pylint: disable=broad-except
                logging.info("Não foi possível resolver o fundo: %s", erro)
                return
            if caminho is None:
                return
            GLib.idle_add(
                self._aplicar_fundo_biblioteca, str(caminho), game.game_id, geracao
            )

        threading.Thread(target=worker, daemon=True).start()

    def _aplicar_fundo_biblioteca(
        self, caminho: str, game_id: str, geracao: int
    ) -> bool:
        if (
            geracao != self._fundo_biblioteca_geracao
            or self._fundo_biblioteca_jogo != game_id
        ):
            return GLib.SOURCE_REMOVE
        try:
            textura = Gdk.Texture.new_from_filename(caminho)
        except GLib.Error as erro:
            logging.info("Fundo da biblioteca inválido: %s", erro)
            Path(caminho).unlink(missing_ok=True)
            return GLib.SOURCE_REMOVE
        self._mostrar_fundo_biblioteca(textura)
        return GLib.SOURCE_REMOVE

    def _mostrar_fundo_biblioteca(self, textura: Optional[Gdk.Texture]) -> None:
        """Aplica ``textura`` com fade, alternando as duas faces do Stack.

        A face escondida recebe a imagem nova e vira a visível: o
        ``transition-type: crossfade`` do Stack dissolve uma na outra. Com
        ``None``, dissolve para o vazio.
        """
        self._fundo_biblioteca_lado = not self._fundo_biblioteca_lado
        escondida = (
            self.library_background_b
            if self._fundo_biblioteca_lado
            else self.library_background_a
        )
        escondida.set_paintable(textura)
        self.library_background_stack.set_visible_child(escondida)

    def limpar_fundo_biblioteca(self, game: Optional[Game] = None) -> None:
        """Volta o fundo da grade ao vazio quando o foco sai do tile."""
        if game is not None and game.game_id != self._fundo_biblioteca_jogo:
            return
        self._fundo_biblioteca_geracao += 1
        self._fundo_biblioteca_jogo = None
        self._mostrar_fundo_biblioteca(None)

    def set_details_view_opacity(self, *_args: Any) -> None:
        if self.navigation_view.get_visible_page() != self.details_page:
            return

        if (
            style_manager := Adw.StyleManager.get_default()
        ).get_high_contrast() or not style_manager.get_system_supports_color_schemes():
            self.details_view_blurred_cover.set_opacity(0.3)
            return

        self.details_view_blurred_cover.set_opacity(
            1 - self.details_view_game_cover.luminance[0]  # type: ignore
            if style_manager.get_dark()
            else self.details_view_game_cover.luminance[1]  # type: ignore
        )

    def sort_func(self, child1: Gtk.Widget, child2: Gtk.Widget) -> int:
        var, order = "name", True

        if self.sort_state in ("newest", "oldest"):
            var, order = "added", self.sort_state == "newest"
        elif self.sort_state == "last_played":
            var = "last_played"
        elif self.sort_state == "install_size":
            val1 = child1.get_child().install_size or 0
            val2 = child2.get_child().install_size or 0
            if val1 != val2:
                return -1 if val1 > val2 else 1
            var, order = "name", False
        elif self.sort_state == "a-z":
            order = False

        def get_value(index: int) -> str:
            return (
                str(getattr((child1.get_child(), child2.get_child())[index], var))
                .lower()
                .removeprefix("the ")
            )

        if var != "name" and get_value(0) == get_value(1):
            var, order = "name", False

        return ((get_value(0) > get_value(1)) ^ order) * 2 - 1

    def set_show_hidden(self, navigation_view: Adw.NavigationView, *_args: Any) -> None:
        self.lookup_action("show_hidden").set_enabled(
            navigation_view.get_visible_page() == self.library_page
        )

    def on_show_sidebar_action(self, *_args: Any) -> None:
        shared.state_schema.set_boolean(
            "show-sidebar", (value := not self.overlay_split_view.get_show_sidebar())
        )
        self.overlay_split_view.set_show_sidebar(value)

    def on_go_to_parent_action(self, *_args: Any) -> None:
        if self.navigation_view.get_visible_page() == self.details_page:
            self.navigation_view.pop()

    def on_go_home_action(self, *_args: Any) -> None:
        self.navigation_view.pop_to_page(self.library_page)

    def on_show_hidden_action(self, *_args: Any) -> None:
        if self.navigation_view.get_visible_page() == self.hidden_library_page:
            return

        self.navigation_view.push(self.hidden_library_page)

    def on_show_zerados_action(self, *_args: Any) -> None:
        if self.navigation_view.get_visible_page() == self.zerados_library_page:
            return

        self.navigation_view.push(self.zerados_library_page)

    def open_integrations(self, *_args: Any) -> None:
        """Abre a página Integrações, criando-a na primeira vez."""
        if self.integracoes_page is None:
            self.integracoes_page = IntegrationsPage()
        if self.navigation_view.get_visible_page() == self.integracoes_page:
            return
        self.integracoes_page.atualizar()
        self.navigation_view.push(self.integracoes_page)

    def open_lighting(self, *_args: Any) -> None:
        """Abre a página Perfis de iluminação, criando-a na primeira vez."""
        if self.lighting_page is None:
            self.lighting_page = LightingPage()
        if self.navigation_view.get_visible_page() == self.lighting_page:
            return
        self.lighting_page.atualizar()
        self.navigation_view.push(self.lighting_page)

    def attach_news_checker(self, checker: Any) -> None:
        self.news_checker = checker
        self._news_handler_ids = [
            checker.connect("posts-changed", self.on_news_posts_changed),
            checker.connect("poll-finished", self.on_news_poll_finished),
            checker.connect("unseen-changed", self.on_news_unseen_changed),
        ]
        self.news_badge.set_visible(checker.has_unseen)
        self.rebuild_news_sources_menu()
        self.rebuild_news_view()
        self.update_news_view()

    def detach_news_checker(self) -> None:
        if (checker := self.news_checker) is not None:
            for handler_id in self._news_handler_ids:
                if checker.handler_is_connected(handler_id):
                    checker.disconnect(handler_id)
        self._news_handler_ids = []
        self.news_checker = None

    def on_news_unseen_changed(self, _checker: Any, unseen: bool) -> None:
        self.news_badge.set_visible(unseen)

    def on_news_posts_changed(self, *_args: Any) -> None:
        self.rebuild_news_view()
        self.update_news_view()
        if (
            self.navigation_view.get_visible_page() == self.news_page
            and self.news_checker is not None
        ):
            self.news_checker.mark_seen()

    def on_news_poll_finished(self, _checker: Any, success: bool) -> None:
        self.update_news_view()
        if not self._news_refresh_requested:
            return
        self._news_refresh_requested = False
        self.dismiss_news_refresh_toast()
        self.toast_queue.add(
            Adw.Toast.new(
                _("Novidades atualizadas")
                if success
                else _("Não foi possível atualizar as novidades")
            )
        )

    def on_news_refresh_clicked(self, *_args: Any) -> None:
        if (checker := self.news_checker) is None:
            return
        self._news_refresh_requested = True
        self.dismiss_news_refresh_toast()
        toast = Adw.Toast.new(_("Atualizando novidades…"))
        toast.set_timeout(0)
        self._news_refresh_toast = toast
        self.toast_queue.add(toast)
        checker.check_async()
        self.update_news_view()

    def dismiss_news_refresh_toast(self) -> None:
        if self._news_refresh_toast is not None:
            self.toast_queue.dismiss(self._news_refresh_toast)
            self._news_refresh_toast = None

    def on_show_news_action(self, *_args: Any) -> None:
        if self.navigation_view.get_visible_page() == self.news_page:
            return
        # As fontes dependem do idioma da interface, e o idioma pode mudar
        # com o app aberto: o menu é refeito a cada entrada na página.
        self.rebuild_news_sources_menu()
        if (checker := self.news_checker) is not None:
            checker.mark_seen()
            if not checker.posts:
                checker.check_async()
        self.update_news_view()
        self.navigation_view.push(self.news_page)

    def update_news_view(self) -> None:
        checker = self.news_checker
        if checker is not None and checker.posts:
            name = "list"
        elif checker is not None and checker.loading:
            name = "loading"
        else:
            name = "empty"
        self.news_stack.set_visible_child_name(name)
        if name == "empty":
            self.update_news_empty_state()

    def update_news_empty_state(self) -> None:
        """Distingue "não há nada" de "não deu para carregar".

        Sem fonte nenhuma ligada a página está vazia por escolha do usuário,
        não por falha de rede — e a mensagem precisa dizer isso.
        """
        sources = set(all_sources(ui_language()))
        if sources and sources <= set(disabled_sources()):
            self.news_status.set_title(_("Nenhuma fonte selecionada"))
            self.news_status.set_description(
                _("Ative uma fonte no menu de fontes para ver as novidades.")
            )
            self.news_retry_button.set_visible(False)
        else:
            self.news_status.set_title(_("Sem novidades"))
            self.news_status.set_description(
                _("Não foi possível carregar as novidades.")
            )
            self.news_retry_button.set_visible(True)

    def rebuild_news_view(self) -> None:
        """Reconstrói os três degraus da página de Novidades.

        O carrossel fica com as novidades mais recentes, a grade com as que
        vêm logo depois, e a lista do fim continua guardando todas — a mesma
        lista de sempre.
        """
        posts = self.news_checker.posts if self.news_checker is not None else ()
        self.rebuild_news_highlights(posts[:_NEWS_HIGHLIGHTS])
        self.rebuild_news_cards(
            posts[_NEWS_HIGHLIGHTS : _NEWS_HIGHLIGHTS + _NEWS_RECENT]
        )
        self.rebuild_news_list()

    def rebuild_news_highlights(self, posts: tuple[NewsPost, ...]) -> None:
        """Enche o carrossel de destaques com as novidades mais recentes."""
        carousel = self.news_highlights_carousel
        for page in self._news_hero_pages:
            carousel.remove(page)
        self._news_hero_pages.clear()
        for post in posts:
            page = self.build_news_hero_card(post)
            self._news_hero_pages.append(page)
            carousel.append(page)
        self.news_highlights_section.set_visible(bool(posts))

    def rebuild_news_cards(self, posts: tuple[NewsPost, ...]) -> None:
        """Enche a grade de cards menores com as novidades seguintes."""
        flowbox = self.news_recent_flowbox
        while child := flowbox.get_first_child():
            flowbox.remove(child)
        for post in posts:
            flowbox.append(self.build_news_card(post))
        self.news_recent_section.set_visible(bool(posts))

    def rebuild_news_list(self) -> None:
        while child := self.news_list.get_first_child():
            self.news_list.remove(child)
        if self.news_checker is None:
            return
        for post in self.news_checker.posts:
            self.news_list.append(self.build_news_row(post))
        self.news_scrolledwindow.get_vadjustment().set_value(0)

    def build_news_hero_card(self, post: NewsPost) -> Gtk.Widget:
        """Um destaque: a imagem em cima, o título e a assinatura embaixo.

        O retorno é a *página* do carrossel, com hexpand para ocupar a
        faixa inteira — ver `_NEWS_HERO_HEIGHT` para o porquê da altura fixa.
        """
        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
        )
        media = self.build_news_media(post, height=_NEWS_HERO_IMAGE)
        # O título ocupa 1 ou 2 linhas; a imagem absorve a diferença para o
        # card preencher a altura fixa da página sem sobrar buraco embaixo.
        media.set_vexpand(True)
        content.append(media)
        content.append(
            self.build_news_card_text(
                post,
                max_title_lines=2,
                max_title_chars=_NEWS_HERO_TITLE_CHARS,
            )
        )
        card = self.build_news_card_root(post, content, "news-hero-card")
        card.set_hexpand(True)
        card.set_vexpand(True)
        page = Gtk.Box(hexpand=True, height_request=_NEWS_HERO_HEIGHT)
        page.append(card)
        return page

    def build_news_card(self, post: NewsPost) -> Gtk.Widget:
        """Um card pequeno: miniatura à esquerda, título e assinatura à direita."""
        content = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=10,
            width_request=_NEWS_CARD_WIDTH,
        )
        content.append(
            self.build_news_media(
                post, height=_NEWS_CARD_IMAGE, width=_NEWS_CARD_IMAGE
            )
        )
        content.append(
            self.build_news_card_text(
                post,
                max_title_lines=2,
                max_title_chars=_NEWS_CARD_TITLE_CHARS,
            )
        )
        return self.build_news_card_root(post, content, "news-card")

    def build_news_card_text(
        self, post: NewsPost, max_title_lines: int, max_title_chars: int
    ) -> Gtk.Box:
        """O bloco de texto de um card: o título e a linha de metadados.

        `max_title_chars` limita a *largura natural* do bloco. Sem esse teto o
        Gtk.Label devolve a largura do texto inteiro, o card não encolhe e a
        grade FlowBox passa a colocar um card por linha — ver as constantes
        `_NEWS_CARD_*` e `_NEWS_HERO_*`.
        """
        text = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=4,
            hexpand=True,
        )
        text.append(
            Gtk.Label(
                label=post.title,
                wrap=True,
                # Quebra só em espaços: o padrão (WORD_CHAR) parte a palavra
                # ao meio quando ela não cabe na linha, o que deixa o título
                # cortado no meio de uma palavra.
                wrap_mode=Pango.WrapMode.WORD,
                xalign=0,
                ellipsize=Pango.EllipsizeMode.END,
                lines=max_title_lines,
                max_width_chars=max_title_chars,
                css_classes=["news-card-title", "title-4"],
            )
        )
        text.append(
            Gtk.Label(
                label=self.build_news_meta(post),
                xalign=0,
                ellipsize=Pango.EllipsizeMode.END,
                lines=1,
                max_width_chars=max_title_chars,
                css_classes=["news-card-meta", "caption"],
            )
        )
        return text

    def build_news_media(
        self, post: NewsPost, height: int, width: int = 0
    ) -> Gtk.Widget:
        """A área de imagem de um card, com um marcador quando não há imagem.

        A moldura tem tamanho fixo e a foto entra como camada por cima. O
        Gtk.Overlay mede pelo filho de trás, então a foto — cuja largura
        natural é a da imagem baixada, por vezes enorme — nunca infla o card.
        """
        frame = Gtk.Box(
            width_request=width or height,
            height_request=height,
        )
        overlay = Gtk.Overlay(child=frame)
        # A classe pinta o fundo e o arredondamento; o recorte é programático
        # porque o CSS do GTK não aceita "overflow".
        overlay.add_css_class("news-card-image")
        overlay.set_overflow(Gtk.Overflow.HIDDEN)
        if post.image:
            picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
            overlay.add_overlay(picture)
            self._queue_news_thumbnail(picture, post.image)
        else:
            overlay.add_overlay(
                Gtk.Image(
                    icon_name="image-missing-symbolic",
                    pixel_size=48 if height > 100 else 32,
                    css_classes=["dim-label"],
                    halign=Gtk.Align.CENTER,
                    valign=Gtk.Align.CENTER,
                )
            )
        return overlay

    def build_news_card_root(
        self, post: NewsPost, content: Gtk.Widget, style_class: str
    ) -> Gtk.Widget:
        """Envolve o conteúdo de um card num botão que abre a notícia."""
        if not post.url:
            # Sem link não há o que abrir: o card fica só como texto.
            root = Gtk.Box(css_classes=[style_class])
            root.append(content)
            return root
        button = Gtk.Button(
            child=content,
            css_classes=["flat", style_class],
        )
        button.connect("clicked", self.on_news_row_activated, post.url)
        return button

    @staticmethod
    def build_news_meta(post: NewsPost) -> str:
        """A linha de metadados de uma notícia: fonte, data e categoria."""
        return " · ".join(
            part
            for part in (
                post.source,
                relative_date(post.timestamp) if post.timestamp else "",
                post.category,
            )
            if part
        )

    def rebuild_news_sources_menu(self) -> None:
        """Refaz o menu que liga e desliga as fontes de novidades.

        As fontes dependem do idioma da interface — a TrinityWeb só existe em
        pt-BR —, então o menu é refeito a cada entrada na página em vez de
        ficar congelado desde a construção da janela.
        """
        for action in self._news_source_actions:
            self.remove_action(action.get_name())
        self._news_source_actions.clear()

        disabled = set(disabled_sources())
        section = Gio.Menu()
        for source in all_sources(ui_language()):
            name = f"news-source-{self._news_source_slug(source)}"
            action = Gio.SimpleAction.new_stateful(
                name,
                None,
                GLib.Variant.new_boolean(source not in disabled),
            )
            action.connect("change-state", self.on_news_source_changed, source)
            self.add_action(action)
            self._news_source_actions.append(action)
            # O rótulo da fonte é nome próprio, mostrado como veio. A ação
            # vai qualificada: o muxer do GTK só resolve "grupo.ação" —
            # sem o "win." a linha nasce insensível e o clique não chega.
            section.append(source, f"win.{name}")

        menu = Gio.Menu()
        menu.append_section(_("Fontes"), section)
        self.news_sources_button.set_menu_model(menu)

    @staticmethod
    def _news_source_slug(source: str) -> str:
        """Um nome de ação seguro para o rótulo de uma fonte."""
        slug = "".join(
            char
            if char.isascii() and char.isalnum()
            else "-"
            for char in source.lower()
        )
        return slug.strip("-") or "fonte"

    def on_news_source_changed(
        self, action: Gio.SimpleAction, state: GLib.Variant, source: str
    ) -> None:
        """Uma fonte foi ligada ou desligada: guarda a escolha e refresca a página."""
        enabled = state.get_boolean()
        # Aceitar o novo estado é o que mantém a marca do menu em dia.
        action.set_state(state)
        set_source_enabled(source, enabled)

        checker = self.news_checker
        if checker is None:
            self.rebuild_news_view()
            self.update_news_view()
            return
        # Refiltrar joga fora as notícias da fonte que acabou de ser desligada
        # e reconstrói a página pelo sinal.
        checker.refilter()
        if enabled:
            # Uma fonte que acabou de ser ligada nunca foi consultada.
            checker.check_async()

    def build_news_row(self, post: NewsPost) -> Gtk.ListBoxRow:
        children: list[Gtk.Widget] = []
        if post.summary:
            children.append(self.build_news_summary_row(post.summary))
        if post.url:
            open_row = Adw.ActionRow(activatable=True)
            open_row.set_use_markup(False)
            open_row.set_title(_("Abrir no navegador"))
            open_row.add_suffix(
                Gtk.Image(
                    icon_name="adw-external-link-symbolic",
                    valign=Gtk.Align.CENTER,
                    css_classes=["dim-label"],
                )
            )
            open_row.connect("activated", self.on_news_row_activated, post.url)
            children.append(open_row)
        row = Adw.ExpanderRow() if children else Adw.ActionRow()
        row.set_use_markup(False)
        row.set_title(post.title)
        row.set_title_lines(0)
        if subtitle := self.build_news_meta(post):
            row.set_subtitle(subtitle)
            row.set_subtitle_lines(0)
        if post.image:
            thumbnail = Gtk.Picture(
                width_request=_NEWS_THUMB_SIZE,
                height_request=_NEWS_THUMB_SIZE,
                content_fit=Gtk.ContentFit.COVER,
                valign=Gtk.Align.CENTER,
            )
            thumbnail.add_css_class("card")
            row.add_prefix(thumbnail)
            self._queue_news_thumbnail(thumbnail, post.image)
        for child in children:
            row.add_row(child)
        return row

    def _queue_news_thumbnail(self, picture: Gtk.Picture, url: str) -> None:
        """Paint `picture` with the cached thumbnail, or download it off-thread."""
        if cached := self._news_thumb_cache.get(url):
            picture.set_paintable(cached)
            return
        pending = self._news_thumb_pending.setdefault(url, [])
        pending.append(picture)
        if len(pending) > 1:
            return
        threading.Thread(
            target=self._fetch_news_thumbnail, args=(url,), daemon=True
        ).start()

    def _fetch_news_thumbnail(self, url: str) -> None:
        data: Optional[bytes] = None
        try:
            data = download_bytes(url, timeout=10, max_bytes=_NEWS_THUMB_BYTES)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.debug("News thumbnail failed to download: %s", url)
        GLib.idle_add(self._apply_news_thumbnail, url, data)

    def _apply_news_thumbnail(self, url: str, data: Optional[bytes]) -> bool:
        """Decode downloaded bytes and paint every row still waiting for `url`."""
        pictures = self._news_thumb_pending.pop(url, [])
        if data:
            try:
                texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
            except GLib.Error:
                texture = None
            if texture is not None:
                if len(self._news_thumb_cache) >= _NEWS_THUMB_CACHE_MAX:
                    self._news_thumb_cache.clear()
                self._news_thumb_cache[url] = texture
                for picture in pictures:
                    if picture.get_parent() is not None:
                        picture.set_paintable(texture)
        return False

    @staticmethod
    def build_news_summary_row(text: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow(activatable=False, selectable=False)
        row.set_child(
            Gtk.Label(
                label=text,
                wrap=True,
                xalign=0,
                margin_top=12,
                margin_bottom=12,
                margin_start=12,
                margin_end=12,
                css_classes=["body"],
            )
        )
        return row

    def on_news_row_activated(self, _row: Gtk.Widget, url: str) -> None:
        open_uri(url, self)

    def on_sort_action(self, action: Gio.SimpleAction, state: GLib.Variant) -> None:
        action.set_state(state)
        self.sort_state = str(state).strip("'")
        self.library.invalidate_sort()

        shared.state_schema.set_string("sort-mode", self.sort_state)

    def on_toggle_search_action(self, *_args: Any) -> None:
        if self.navigation_view.get_visible_page() == self.library_page:
            search_bar = self.search_bar
            search_entry = self.search_entry
        elif self.navigation_view.get_visible_page() == self.hidden_library_page:
            search_bar = self.hidden_search_bar
            search_entry = self.hidden_search_entry
        else:
            return

        search_bar.set_search_mode(not (search_mode := search_bar.get_search_mode()))

        if not search_mode:
            self.set_focus(search_entry)

        search_entry.set_text("")

    def show_details_page_search(self, widget: Gtk.Widget) -> None:
        library = (
            self.hidden_library if widget == self.hidden_search_entry else self.library
        )
        index = 0

        while True:
            if not (child := library.get_child_at_index(index)):
                break

            if self.filter_func(child):
                self.show_details_page(child.get_child())
                break

            index += 1

    def on_undo_action(
        self, _widget: Any, game: Optional[Game] = None, undo: Optional[str] = None
    ) -> None:
        if not game:  # If the action was activated via Ctrl + Z
            if shared.importer and (
                shared.importer.imported_game_ids or shared.importer.removed_game_ids
            ):
                shared.importer.undo_import()
                return

            try:
                game = tuple(self.toasts.keys())[-1][0]
                undo = tuple(self.toasts.keys())[-1][1]
            except IndexError:
                return

        if game:
            if undo == "hide":
                game.toggle_hidden(False)

            elif undo == "remove":
                game.removed = False
                game.save()
                game.update()

            self.toasts[(game, undo)].dismiss()
            self.toasts.pop((game, undo))

    def on_open_menu_action(self, *_args: Any) -> None:
        if self.navigation_view.get_visible_page() == self.library_page:
            self.primary_menu_button.popup()
        elif self.navigation_view.get_visible_page() == self.hidden_library_page:
            self.hidden_primary_menu_button.popup()
        elif self.navigation_view.get_visible_page() == self.zerados_library_page:
            self.zerados_primary_menu_button.popup()

    def on_close_action(self, *_args: Any) -> None:
        self.close()

    def update_details_notice(self, game: Game) -> None:
        self.details_view_update_notice.set_visible(game.has_update and not game.zerado)

    def on_update_notice_clicked(self, *_args: Any) -> None:
        game = self.active_game
        if game is None or not game.has_update:
            return

        open_uri(getattr(game, "update_url", ""), self)

        dialog = Adw.AlertDialog.new(
            _("Você instalou a atualização?"),
            _(
                "A página da atualização foi aberta no navegador. Confirme após "
                "instalá-la para ocultar o aviso."
            ),
        )
        dialog.add_response("cancel", _("Ainda não"))
        dialog.add_response("confirm", _("Já instalei"))
        dialog.set_response_appearance(
            "confirm", Adw.ResponseAppearance.SUGGESTED
        )
        dialog.set_default_response("confirm")
        dialog.set_close_response("cancel")
        dialog.connect("response", self.on_update_notice_response, game)
        dialog.present(self)

    def on_update_notice_response(
        self, _dialog: Adw.AlertDialog, response: str, game: Game
    ) -> None:
        if response != "confirm":
            return
        game.dismiss_update()
        if self.active_game is game:
            self.update_details_notice(game)

    def update_install_size_label(self, game: Game) -> None:
        text = "" if game.zerado else format_size(game.install_size)
        self.details_view_size.set_visible(bool(text))
        if text:
            self.details_view_size.set_label(_("Tamanho: {}").format(text))

    def update_status_button(self, game: Game) -> None:
        self.details_view_status_button.set_label(
            status_label(game.status) or _("Definir status")
        )
        self.details_view_status_button.set_menu_model(self.build_status_menu())
        self.details_view_delete_button.set_visible(game.zerado)

    @staticmethod
    def build_status_menu() -> Gio.Menu:
        menu = Gio.Menu()
        section = Gio.Menu()
        for value, label in STATUS_LABELS.items():
            item = Gio.MenuItem.new(label, None)
            item.set_action_and_target_value("win.set_status", GLib.Variant("s", value))
            section.append_item(item)
        menu.append_section(None, section)

        clear = Gio.Menu()
        item = Gio.MenuItem.new(_("Sem status"), None)
        item.set_action_and_target_value("win.set_status", GLib.Variant("s", ""))
        clear.append_item(item)
        menu.append_section(None, clear)
        return menu

    def on_set_status_action(self, _action: Any, target: GLib.Variant) -> None:
        game = getattr(self, "active_game", None)
        if game is None:
            return

        era_zerado = game.zerado
        game.definir_status(target.get_string())
        game.save()
        game.update()

        if era_zerado and game.removed and not game.zerado:
            self.navigation_view.pop()
            return
        if era_zerado and not game.zerado:
            self.show_details_page(game)

        self.update_status_button(game)
        self.update_notes_block(game)
        if getattr(self, "filter_status_state", ""):
            self.library.invalidate_filter()
            self.zerados_library.invalidate_filter()
            self.set_library_child()

    def build_card_menu(
        self, game: Game, members: Optional[list] = None
    ) -> Gio.Menu:
        grouped = bool(members and len(members) > 1)
        menu = Gio.Menu()
        if grouped:
            vias = Gio.Menu()
            for member in sorted(members, key=lambda m: m.name.casefold()):
                item = Gio.MenuItem.new(
                    self.get_application().get_source_name(member.source), None
                )
                item.set_action_and_target_value(
                    "win.launch_via", GLib.Variant("s", member.game_id)
                )
                vias.append_item(item)
            # The variable is the section title listing the launchers
            menu.append_section(_("Jogar via"), vias)

        base = Gio.Menu()
        for label, action in (
            (_("Edit"), "app.edit_game"),
            (_("Unhide") if game.hidden else _("Hide"), "app.hide_game"),
            (_("Remove"), "app.remove_game"),
            (_("Add to Sunshine"), "app.add_to_sunshine"),
        ):
            item = Gio.MenuItem.new(label, None)
            item.set_action_and_target_value(action, None)
            base.append_item(item)
        menu.append_section(None, base)

        alternar = Gio.Menu()
        item = Gio.MenuItem.new(
            _("Marcar como jogo")
            if game.is_launcher
            else _("Marcar como launcher"),
            None,
        )
        item.set_action_and_target_value(
            "win.toggle_launcher", GLib.Variant("s", game.game_id)
        )
        alternar.append_item(item)
        menu.append_section(None, alternar)

        chave = agrupamento.atualizar(game)
        if grouped:
            grupo = Gio.Menu()
            item = Gio.MenuItem.new(_("Desagrupar"), None)
            item.set_action_and_target_value(
                "win.desagrupar", GLib.Variant("s", chave)
            )
            grupo.append_item(item)
            menu.append_section(None, grupo)
        elif agrupamento.ativo() and agrupamento.desagrupada(chave):
            # Um desagrupamento manual é reversível: o mesmo menu devolve a
            # chave para o agrupamento e os membros voltam ao card único.
            grupo = Gio.Menu()
            item = Gio.MenuItem.new(_("Agrupar novamente"), None)
            item.set_action_and_target_value(
                "win.reagrupar", GLib.Variant("s", chave)
            )
            grupo.append_item(item)
            menu.append_section(None, grupo)
        return menu

    def on_launch_via_action(self, _action: Any, target: GLib.Variant) -> None:
        game = shared.store.get(target.get_string())
        if game is None:
            return
        agrupamento.definir_preferido(game)
        for member in agrupamento.membros(game):
            member.update()
        game.launch()

    def on_desagrupar_action(self, _action: Any, target: GLib.Variant) -> None:
        chave = target.get_string()
        agrupamento.desagrupar_chave(chave)
        for game in shared.store:
            if agrupamento.atualizar(game) == chave:
                game.update()

    def on_reagrupar_action(self, _action: Any, target: GLib.Variant) -> None:
        chave = target.get_string()
        agrupamento.reagrupar_chave(chave)
        for game in shared.store:
            if agrupamento.atualizar(game) == chave:
                game.update()

    def on_toggle_launcher_action(
        self, _action: Any, target: GLib.Variant
    ) -> None:
        game = shared.store.get(target.get_string())
        if game is None:
            return
        chave = agrupamento.atualizar(game)
        game.is_launcher = not game.is_launcher
        launcher.registrar(game, game.is_launcher)
        game.save()
        for outro in shared.store:
            if agrupamento.atualizar(outro) == chave:
                outro.update()
        agrupamento.reconciliar()

    def atualizar_launchers(self) -> None:
        while (child := self.launchers_box.get_first_child()) is not None:
            self.launchers_box.remove(child)
        items = launcher.listar()
        # The gamepad tester is always present in this bar, even when there are
        # no external launchers configured.
        self.launchers_bar.set_visible(True)
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        for game in items:
            icon_name = self._icone_disponivel(
                theme,
                launcher.nomes_de_icone(game),
            )
            button = Gtk.Button(
                tooltip_text=game.name,
                css_classes=["flat", "circular"],
                width_request=40,
                height_request=40,
                valign=Gtk.Align.CENTER,
            )
            button.set_child(Gtk.Image.new_from_icon_name(icon_name))
            button.connect("clicked", self.on_launcher_clicked, game)
            # Lets the gamepad find (and launch/menu) the focused launcher.
            button._jolven_launcher_game = game  # type: ignore[attr-defined]
            right = Gtk.GestureClick.new()
            right.set_button(3)
            right.connect("released", self.on_launcher_menu, game, button)
            button.add_controller(right)
            self.launchers_box.append(button)

    def _xcloud_enabled_changed(self, *_args: Any) -> None:
        self.atualizar_launchers()
        enabled = shared.schema.get_boolean("xbox-cloud-gaming")
        app = self.get_application()
        games = tuple(shared.store.source_games.get("xcloud", {}).values())
        iterator = iter(games)
        previous_state = app.state
        app.state = shared.AppState.LOAD_FROM_DISK

        if not games:
            self._xcloud_enabled_finished(previous_state, enabled)
            return
        from gi.repository import GLib

        try:
            for _index in range(24):
                try:
                    next(iterator).update()
                except StopIteration:
                    self._xcloud_enabled_finished(previous_state, enabled)
                    return
        except StopIteration:
            pass
        GLib.idle_add(self._xcloud_enabled_step, iterator, previous_state, enabled)

    def _xcloud_enabled_step(self, iterator: Any, previous_state: Any, enabled: bool) -> bool:
        from gi.repository import GLib

        try:
            for _index in range(24):
                try:
                    next(iterator).update()
                except StopIteration:
                    return self._xcloud_enabled_finished(previous_state, enabled)
        except StopIteration:
            return self._xcloud_enabled_finished(previous_state, enabled)
        return GLib.SOURCE_CONTINUE

    def _xcloud_enabled_finished(self, previous_state: Any, enabled: bool) -> bool:
        from gi.repository import GLib

        app = self.get_application()
        try:
            app.state = previous_state
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        self.set_library_child()
        self.library.invalidate_filter()
        self.set_library_child()
        self.create_source_rows()
        if enabled:
            from cartridges.xcloud_catalog import sync_async

            sync_async(
                on_complete=self._xcloud_sync_done,
                on_error=self._xcloud_sync_failed,
            )
        return GLib.SOURCE_REMOVE

    def _on_library_refresh_clicked(self, *_args: Any) -> None:
        """Reimporta todas as plataformas e, depois, o catálogo do xCloud.

        O botão deixou de ser exclusivo do Xbox Cloud (issue #71): cada
        acionamento reconstrói as fontes, então plataformas instaladas desde a
        última importação entram nesta mesma passada, sem reiniciar o Jolven.
        """
        if self._library_refreshing:
            self.toast_queue.add(
                Adw.Toast.new(_("Atualização da biblioteca em andamento"))
            )
            return

        app = self.get_application()
        if app.state != shared.AppState.DEFAULT:
            # Já existe uma importação (ou remoção em massa) em curso: ela
            # bloqueia a interface, então só avisamos em vez de empilhar outra.
            self.toast_queue.add(
                Adw.Toast.new(_("Aguarde a operação atual terminar"))
            )
            return

        self._set_library_refreshing(True)
        app.on_import_action(on_finished=self._on_library_refresh_imported)

    def _on_library_refresh_imported(self) -> None:
        """Encadeia o catálogo do xCloud ao fim da importação, se ligado."""
        if not self._library_refreshing:
            return
        try:
            enabled = shared.schema.get_boolean("xbox-cloud-gaming")
        except Exception:  # pylint: disable=broad-exception-caught
            enabled = False
        if not enabled:
            self._finish_library_refresh()
            return

        from cartridges.xcloud_catalog import sync_async

        # Chamadas de sync_async já chegam na thread principal (idle_add /
        # entregar_na_tela); os handlers abaixo são só os da atualização manual.
        started = sync_async(
            on_complete=self._on_library_refresh_synced,
            on_error=self._on_library_refresh_sync_failed,
            force=True,
        )
        if not started:
            self._finish_library_refresh()
            return
        toast = Adw.Toast.new(_("Atualizando catálogo Xbox Cloud…"))
        toast.set_timeout(0)
        toast.set_use_markup(False)
        self.toast_queue.add(toast)
        self._xcloud_refresh_toast = toast

    def _on_library_refresh_synced(self, total: int) -> None:
        self._xcloud_sync_done(total)
        self._finish_library_refresh()

    def _on_library_refresh_sync_failed(self, error: Any) -> None:
        self._xcloud_sync_failed(error)
        # A importação em si pode ter dado certo: libera o botão mesmo sem o
        # catálogo, em vez de deixá-lo travado.
        self._finish_library_refresh()

    def _finish_library_refresh(self) -> None:
        """Encerra o estado de atualização e devolve o botão ao usuário."""
        self._set_library_refreshing(False)
        self._dismiss_xcloud_refresh_toast()

    def _set_library_refreshing(self, busy: bool) -> None:
        self._library_refreshing = busy
        self.library_refresh_button.set_sensitive(not busy)
        self.library_refresh_spinner.set_visible(busy)

    def _dismiss_xcloud_refresh_toast(self) -> None:
        if self._xcloud_refresh_toast is not None:
            self.toast_queue.dismiss(self._xcloud_refresh_toast)
            self._xcloud_refresh_toast = None

    def _xcloud_sync_done(self, total: int) -> None:
        """Feedback do catálogo: vale para o botão Atualizar e para o switch."""
        toast = Adw.Toast.new(
            _("Catálogo Xbox Cloud atualizado: {} jogos").format(total)
        )
        toast.set_use_markup(False)
        self.toast_queue.add(toast)
        self.create_source_rows()

    def _xcloud_sync_failed(self, error: Any) -> None:
        logging.warning("Sincronização do catálogo xCloud falhou: %s", error)
        toast = Adw.Toast.new(
            _("Não foi possível atualizar o Xbox Cloud (offline?)")
        )
        toast.set_use_markup(False)
        self.toast_queue.add(toast)

    def on_launcher_clicked(self, _button: Gtk.Button, game: Game) -> None:
        game.launch()

    def launch_library_game(self, game: Game) -> None:
        """Joga pela plataforma que tornou o card agrupado visível.

        Um card pode representar, por exemplo, uma instalação local e a
        edição do xCloud. Quando apenas o filtro do xCloud está ativo, lançar
        o primário local faria o botão parecer inerte (ou abriria a cópia
        errada). Preserve o primário quando ele ainda pertence aos filtros
        visíveis; caso contrário, use o membro visível preferido do grupo.
        """
        members = agrupamento.membros(game)
        visible_members = [
            member
            for member in members
            if self._source_filter_id(member) in self.active_source_filters
        ]
        target = game
        if visible_members and game not in visible_members:
            target = agrupamento.primario(visible_members)
        logging.info(
            "Lançando %s via %s (%s)",
            target.name,
            target.source,
            target.executable,
        )
        target.launch()

    def on_launcher_menu(
        self,
        _gesture: Gtk.GestureClick,
        _n_press: int,
        _x: float,
        _y: float,
        game: Game,
        button: Gtk.Button,
    ) -> None:
        menu = Gio.Menu()
        item = Gio.MenuItem.new(_("Marcar como jogo"), None)
        item.set_action_and_target_value(
            "win.toggle_launcher", GLib.Variant("s", game.game_id)
        )
        menu.append_item(item)
        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(button)
        popover.set_position(Gtk.PositionType.BOTTOM)
        popover.popup()

    @staticmethod
    def _icone_disponivel(
        theme: Gtk.IconTheme,
        candidates: tuple[str, ...],
    ) -> str:
        return next(
            (name for name in candidates if theme.has_icon(name)),
            "application-x-executable-symbolic",
        )

    def launch_xcloud_game(self, game: Game) -> bool:
        """Abre o título do Xbox Cloud no navegador configurado, em quiosque."""
        if not shared.schema.get_boolean("xbox-cloud-gaming"):
            logging.warning("Jogo xCloud ignorado porque a integração está desativada")
            self.toast_queue.add(
                Adw.Toast.new(_("Ative o Xbox Cloud Gaming nas preferências"))
            )
            return False

        product_id = self._xcloud_product_id(game)
        if not product_id:
            logging.warning("Jogo xCloud sem product_id: %r", game.executable)
            self.toast_queue.add(
                Adw.Toast.new(_("Não foi possível abrir o jogo no Xbox Cloud Gaming"))
            )
            return False

        from cartridges.utils import browser  # noqa: PLC0415

        url = f"https://www.xbox.com/play/launch/{product_id}"
        ok, message = browser.launch_kiosk(
            shared.schema.get_string("xcloud-browser"), url
        )
        if not ok:
            self.toast_queue.add(
                Adw.Toast.new(message or _("Não foi possível abrir o navegador"))
            )
        return ok

    @staticmethod
    def _xcloud_product_id(game: Game) -> Optional[str]:
        executable = game.executable or ""
        if executable:
            try:
                path = urlparse(executable).path.rstrip("/")
                if path:
                    return path.rsplit("/", 1)[-1]
            except ValueError:
                pass
        game_id = game.game_id or ""
        if game_id.startswith("xcloud_"):
            return game_id.removeprefix("xcloud_")
        return None

    def on_delete_game_action(self, *_args: Any) -> None:
        game = getattr(self, "active_game", None)
        if game is None or not game.zerado:
            return
        dialog = Adw.AlertDialog.new(
            _("Excluir {}?").format(game.name),
            _(
                "Tem certeza que deseja excluir este jogo? "
                "Esta ação é irreversível."
            ),
        )
        dialog.add_response("cancel", _("Cancelar"))
        dialog.add_response("delete", _("Excluir"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self.on_delete_game_response, game)
        dialog.present(self)

    def on_uzdoom_mods_action(self, *_args: Any) -> None:
        game = getattr(self, "active_game", None)
        if game is None or game.base_source != "uzdoom":
            return
        UzdoomModsDialog(game).present(self)

    def on_delete_game_response(
        self, _dialog: Adw.AlertDialog, response: str, game: Game
    ) -> None:
        if response != "delete" or not game.zerado:
            return

        self.retirar_da_grade(game)
        shared.store.excluir(game)
        agrupamento.reconciliar()

        if self.navigation_view.get_visible_page() == self.details_page:
            self.navigation_view.pop()
        self.set_library_child()

        toast = Adw.Toast.new(_("{} excluído").format(game.name))
        toast.set_use_markup(False)
        self.toast_queue.add(toast)

    def update_notes_block(self, game: Game) -> None:
        notes = (game.notes or "").strip()
        self.details_view_notes.set_label(notes)
        self.details_view_notes_box.set_visible(bool(notes))
        self.details_view_notes_button.set_visible(can_edit_notes(game))

    def on_notes_popover_toggled(
        self, popover: Gtk.Popover, _pspec: Any
    ) -> None:
        self.sync_notes_editor(
            popover, self.details_view_notes_view, getattr(self, "active_game", None)
        )

    def update_playtime_label(self, game: Game) -> None:
        self.details_view_playtime.set_visible(bool(game.playtime))
        if not game.playtime:
            return

        self.details_view_playtime.set_text(
            _("Tempo de jogo: {}").format(format_playtime(game.playtime))
        )

        self._playtime_clickable = bool(session_log.load(game.game_id))
        self.details_view_playtime.set_tooltip_text(
            _("Ver o histórico de sessões") if self._playtime_clickable else None
        )
        self.details_view_playtime.set_cursor(
            Gdk.Cursor.new_from_name("pointer", None)
            if self._playtime_clickable
            else None
        )
        if self._playtime_clickable:
            self.details_view_playtime.add_css_class("playtime-clickable")
        else:
            self.details_view_playtime.remove_css_class("playtime-clickable")

    def on_playtime_activated(self, *_args: Any) -> None:
        if not self._playtime_clickable:
            return
        game = getattr(self, "active_game", None)
        if game is not None:
            SessionHistoryDialog(game).present(self)

    def retirar_da_grade(self, game: Game) -> None:
        if (parent := game.get_parent()) is not None:
            grade = parent.get_parent()
            if grade is not None:
                grade.remove(game)
            if game.get_parent():
                game.get_parent().set_child()
        self.game_covers.pop(game.game_id, None)

    def session_elapsed(self) -> int:
        from cartridges.process_session import ProcessSession

        if ProcessSession.active is not None:
            return ProcessSession.active.elapsed
        return 0

    def session_tick(self, *_args: Any) -> bool:
        self.session_blocker_timer.set_label(format_stopwatch(self.session_elapsed()))
        return GLib.SOURCE_CONTINUE

    def show_session_blocker(self, game: Game) -> None:
        if self.session_game is game and self.session_blocker.get_visible():
            return

        self.session_game = game
        self._game_overlay_open = False
        self.botao_tarefas.reavaliar()
        self.session_blocker_label.set_label(_("{} em execução").format(game.name))
        self.session_blocker.set_visible(True)
        self.navigation_view.set_sensitive(False)
        self._sync_recorder_button()
        self.session_return_button.grab_focus()
        self.session_tick()
        self.session_blocker_timer.set_visible(True)
        self.session_timer_id = GLib.timeout_add_seconds(1, self.session_tick)

        if shared.schema.get_boolean("session-wallpaper"):
            session_wallpaper.comecar(game)
        # A iluminação não é mais daqui: ela acompanha o processo em
        # `ProcessSession`, que existe mesmo com o rastreio de tempo desligado.
        # Manter as duas cópias aqui faria a fita trocar de cor duas vezes.

    def hide_session_blocker(self) -> None:
        self.session_blocker.set_visible(False)
        self.session_game = None
        self._game_overlay_open = False
        self.botao_tarefas.reavaliar()
        self.navigation_view.set_sensitive(True)

        if self.session_timer_id:
            GLib.source_remove(self.session_timer_id)
            self.session_timer_id = 0
        self.session_blocker_timer.set_visible(False)
        session_wallpaper.restaurar()

    def on_session_blocker_clicked(self, *_args: Any) -> None:
        from cartridges.process_session import ProcessSession

        if ProcessSession.active is not None:
            ProcessSession.active.stop(record=True)

    def open_game_overlay(self) -> None:
        """Bring the in-game controls to the front of the Gamescope session."""
        if self.session_game is None:
            return
        self._game_overlay_open = True
        self.present()
        GLib.idle_add(self._focus_session_return_button)

    def _focus_session_return_button(self) -> bool:
        self.session_return_button.grab_focus()
        return GLib.SOURCE_REMOVE

    def return_to_game(self, *_args: Any) -> None:
        """Hide Jolven so Gamescope can focus the running game again."""
        if self.session_game is None:
            return
        self._game_overlay_open = False
        self.minimize()

    def open_gpu_screen_recorder(self, *_args: Any) -> None:
        """Start or stop the native recorder for the running session."""
        self._recorder_action(replay=False)

    def on_save_recorder_replay(self, *_args: Any) -> None:
        """Flush the running recorder's replay buffer to disk."""
        self._recorder_action(replay=True)

    def _recorder_action(self, *, replay: bool) -> None:
        if self._recorder_busy:
            return
        try:
            from cartridges.recorder import RecorderService, RecorderSettings
        except ImportError:
            logging.warning("cartridges.recorder is unavailable")
            if not replay:
                self._notify_recorder_missing()
            return
        if not shared.schema.get_boolean("recorder-enabled"):
            if not replay:
                self._notify_recorder_missing()
            return
        self._recorder_busy = True
        threading.Thread(
            target=self._recorder_worker,
            args=(RecorderService, RecorderSettings, replay),
            daemon=True,
        ).start()

    def _recorder_worker(
        self, service_cls: Any, settings_cls: Any, replay: bool
    ) -> None:
        outcome = "error"
        try:
            service = self._recorder_service
            if service is None:
                service = service_cls()
                self._recorder_service = service
            if replay:
                outcome = "replay" if service.save_replay() else "error"
            elif service.is_running():
                outcome = "stop" if service.stop() else "error"
            elif not service.is_available():
                outcome = "missing"
            else:
                settings = self._build_recorder_settings(settings_cls)
                outcome = "start" if service.start(settings=settings) else "error"
        except Exception:
            logging.exception("Recorder action failed")
        entregar_na_tela(self._recorder_finished, outcome)

    def _build_recorder_settings(self, settings_cls: Any) -> Any:
        schema = shared.schema
        audio = schema.get_string("recorder-audio")
        return settings_cls(
            video_source=_RECORDER_SOURCES.get(
                schema.get_string("recorder-source"), "portal"
            ),
            container=schema.get_string("recorder-container"),
            codec=schema.get_string("recorder-codec"),
            quality=schema.get_string("recorder-quality"),
            bitrate_mode=schema.get_string("recorder-bitrate-mode"),
            fps=schema.get_int("recorder-fps"),
            cursor=schema.get_boolean("recorder-cursor"),
            scale=schema.get_string("recorder-scale"),
            audio_sources=_RECORDER_AUDIO_SOURCES.get(audio, ("default_output",)),
            audio_codec=schema.get_string("recorder-audio-codec"),
            audio_bitrate=schema.get_int("recorder-audio-bitrate"),
            replay_seconds=schema.get_int("recorder-replay-seconds"),
            replay_storage=schema.get_string("recorder-replay-storage"),
            output_dir=schema.get_string("recorder-output-dir"),
            stream_url=self._valid_stream_url(schema.get_string("recorder-stream-url")),
        )

    @staticmethod
    def _valid_stream_url(url: str) -> str:
        url = (url or "").strip()
        if not url:
            return ""
        if urlparse(url).scheme.lower() in _ALLOWED_STREAM_SCHEMES:
            return url
        logging.warning("Ignoring recorder stream URL with an unsupported scheme")
        return ""

    def _recorder_finished(self, outcome: str) -> None:
        self._recorder_busy = False
        if outcome == "missing":
            self.toast_queue.add(
                Adw.Toast.new(
                    _(
                        "GPU Screen Recorder não foi encontrado. Instale o aplicativo e tente novamente."
                    )
                )
            )
            return
        if outcome == "start":
            self._recorder_recording = True
            self._update_recorder_button()
            self.toast_queue.add(Adw.Toast.new(_("Gravação iniciada")))
            return
        if outcome == "stop":
            self._recorder_recording = False
            self._update_recorder_button()
            self.toast_queue.add(Adw.Toast.new(_("Gravação salva")))
            return
        if outcome == "replay":
            self.toast_queue.add(Adw.Toast.new(_("Replay salvo")))
            return
        self.toast_queue.add(Adw.Toast.new(_("Não foi possível controlar o gravador.")))

    def _update_recorder_button(self) -> None:
        if self._recorder_recording:
            self.gpu_screen_recorder_button.set_icon_name(
                "media-playback-stop-symbolic"
            )
            self.gpu_screen_recorder_button.set_tooltip_text(
                _("Parar a gravação. Clique com o botão direito para salvar o replay.")
            )
            return
        self.gpu_screen_recorder_button.set_icon_name("media-record-symbolic")
        self.gpu_screen_recorder_button.set_tooltip_text(
            _("Iniciar a gravação. Clique com o botão direito para salvar o replay.")
        )

    def _sync_recorder_button(self) -> None:
        service = self._recorder_service
        running = bool(service is not None and service.is_running())
        if running != self._recorder_recording:
            self._recorder_recording = running
            self._update_recorder_button()

    def _notify_recorder_missing(self) -> None:
        self.toast_queue.add(
            Adw.Toast.new(
                _(
                    "GPU Screen Recorder não foi encontrado. Instale o aplicativo e tente novamente."
                )
            )
        )

    def on_session_notes_popover_toggled(
        self, popover: Gtk.Popover, _pspec: Any
    ) -> None:
        self.sync_notes_editor(
            popover, self.session_blocker_notes_view, self.session_game
        )

    def sync_notes_editor(
        self, popover: Gtk.Popover, view: Gtk.TextView, game: Optional[Game]
    ) -> None:
        if game is None:
            return

        buffer = view.get_buffer()
        if popover.get_visible():
            buffer.set_text(game.notes or "")
            return

        notes = buffer.get_text(
            buffer.get_start_iter(), buffer.get_end_iter(), False
        ).strip()
        if notes == (game.notes or ""):
            return

        game.notes = notes
        game.save()
        game.update()
        refresh = getattr(self, "update_notes_block", None)
        if game is getattr(self, "active_game", None) and refresh is not None:
            refresh(game)
