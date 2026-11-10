# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional RetroArch localhost controls for the Jolven desktop UI.

This dialog sends documented UDP commands to the user's *external*
RetroArch, only when enabled in RetroArch and with an active game.
No X11/Wayland input injection and no in-game overlay claims.
"""

from __future__ import annotations

import threading

from gi.repository import Adw, GLib, Gtk

from cartridges.utils.retroarch_nci import query_status, request_action


_ACTIONS = (
    ("MENU_TOGGLE", "Abrir/fechar menu"),
    ("PAUSE_TOGGLE", "Pausar/retomar"),
    ("SCREENSHOT", "Capturar tela"),
    ("FAST_FORWARD", "Alternar avanço rápido"),
    ("SLOWMOTION", "Alternar câmera lenta"),
    ("MUTE", "Silenciar/ativar áudio"),
    ("VOLUME_DOWN", "Diminuir volume"),
    ("VOLUME_UP", "Aumentar volume"),
)


class RetroArchControlsDialog(Adw.Window):
    def __init__(self, parent: Gtk.Window) -> None:
        super().__init__(title=_("Ações do RetroArch externo"))
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_default_size(430, 500)
        self._buttons: list[Gtk.Button] = []
        self._busy = False

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page.set_margin_top(20)
        page.set_margin_bottom(20)
        page.set_margin_start(20)
        page.set_margin_end(20)

        self._status = Gtk.Label(
            label=_("Verificando RetroArch em 127.0.0.1…"),
            wrap=True,
            xalign=0,
        )
        page.append(self._status)
        note = Gtk.Label(
            label=_(
                "Ative comandos de rede no RetroArch e limite a escuta ao "
                "próprio computador. O Jolven não confirma se uma ação foi "
                "executada; o envio UDP pode falhar sem aviso."
            ),
            wrap=True, xalign=0,
        )
        note.add_css_class("dim-label")
        page.append(note)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for command, label in _ACTIONS:
            button = Gtk.Button(label=_(label), sensitive=False)
            button.connect("clicked", self._action_clicked, command)
            content.append(button)
            self._buttons.append(button)
        scroll.set_child(content)
        page.append(scroll)

        refresh = Gtk.Button(label=_("Atualizar estado"))
        refresh.connect("clicked", lambda *_: self.refresh())
        page.append(refresh)
        self.set_content(page)
        self.refresh()

    def _set_status(self, message: str, ready: bool) -> bool:
        self._busy = False
        self._status.set_label(message)
        for button in self._buttons:
            button.set_sensitive(ready)
        return GLib.SOURCE_REMOVE

    def refresh(self) -> None:
        if self._busy:
            return
        self._busy = True
        for button in self._buttons:
            button.set_sensitive(False)

        def work() -> None:
            try:
                runtime = query_status()
                if not runtime.available:
                    message = _("Comandos não disponíveis ou resposta não verificada")
                    ready = False
                elif not runtime.playing:
                    message = _("RetroArch ativo, mas nenhum jogo foi detectado")
                    ready = False
                else:
                    message = _("RetroArch detectado: {}").format(
                        _("Pausado") if runtime.paused else _("Em execução")
                    )
                    ready = True
            except (OSError, ValueError):
                message, ready = _("Não foi possível consultar RetroArch"), False
            GLib.idle_add(self._set_status, message, ready)

        threading.Thread(
            target=work, daemon=True,
            name="jolven-retroarch-status",
        ).start()

    def _action_clicked(self, _button: Gtk.Button, command: str) -> None:
        if self._busy:
            return
        self._busy = True
        for button in self._buttons:
            button.set_sensitive(False)

        def work() -> None:
            try:
                result = request_action(command)
                message = (
                    _("Comando enviado (execução não verificada)")
                    if result.sent else _("RetroArch não confirmou a disponibilidade")
                )
            except (OSError, ValueError):
                message = _("Não foi possível enviar o comando")
            GLib.idle_add(self._set_status, message, False)
            GLib.idle_add(self.refresh)

        threading.Thread(
            target=work, daemon=True,
            name="jolven-retroarch-action",
        ).start()


def open_retroarch_controls(parent: Gtk.Window) -> None:
    dialog = RetroArchControlsDialog(parent)
    dialog.present()
