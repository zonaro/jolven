"""Posiciona a janela principal no monitor configurado."""

from __future__ import annotations

import logging

from gi.repository import Gdk, Gio, GLib

from cartridges import shared


def _get_display():
    try:
        return Gdk.Display.get_default()
    except Exception:
        return None


def _find_monitor_by_connector(display, connector: str):
    if not display or not connector:
        return None
    try:
        monitors = display.get_monitors()
        if not monitors:
            return None
        for i in range(monitors.get_n_items()):
            monitor = monitors.get_item(i)
            get_connector = getattr(monitor, "get_connector", None)
            if get_connector and get_connector() == connector:
                return monitor
    except Exception:
        logging.exception("Não foi possível buscar monitores")
    return None


def apply_window_monitor(window) -> None:
    """Aplica o monitor configurado para a janela principal (modo desktop)."""
    if not window or getattr(shared.runtime, "is_game_mode", False):
        return
    try:
        schema = shared.schema
    except Exception:
        return
    try:
        connector = schema.get_string("window-monitor") if schema else ""
    except Exception:
        return
    if not connector:
        return
    display = _get_display()
    monitor = _find_monitor_by_connector(display, connector)
    if monitor is None:
        return
    try:
        if hasattr(window, "fullscreen_on_monitor"):
            window.fullscreen_on_monitor(monitor)
            return
        if hasattr(window, "set_display"):
            # Fallback best effort
            pass
    except Exception:
        logging.exception("Não foi possível posicionar a janela no monitor configurado")


def apply_monitor_change(schema, key: str, window) -> None:
    if key != "window-monitor":
        return
    apply_window_monitor(window)
