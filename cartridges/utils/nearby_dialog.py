# SPDX-License-Identifier: GPL-3.0-or-later
"""On-demand Jolven Nearby GTK session control; no auto-start service.

The GUI deliberately displays the ephemeral token/fingerprint but never
stores credentials. A receiver always asks for explicit offer approval.
Port binding, file validation and TLS live in stdlib-only backend modules.
"""

from __future__ import annotations

import threading
from pathlib import Path

from gi.repository import Adw, GLib, Gtk

from cartridges.utils.nearby_receiver import create_receiver, serve_receiver
from cartridges.utils.nearby_sender import create_sender, serve_sender


_KINDS = ("rom", "save", "cover", "label")


class NearbyDialog(Adw.Window):
    def __init__(self, parent: Gtk.Window) -> None:
        super().__init__(title=_("Jolven Nearby"))
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_default_size(580, 560)
        self._closing = False
        self._busy = False
        self._selected_file: Path | None = None
        self._selected_folder: Path | None = None
        self._stop = threading.Event()
        self._pending_approval: threading.Event | None = None
        self.connect("close-request", self._on_close)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        root.set_margin_top(18)
        root.set_margin_bottom(18)
        root.set_margin_start(18)
        root.set_margin_end(18)

        intro = Gtk.Label(
            label=_(
                "Transfira apenas arquivos seus. O app Android usa HTTPS "
                "com verificação de fingerprint SHA-256 e token temporário. "
                "Nenhum emulador, ROM ou save é obtido automaticamente."
            ),
            wrap=True, xalign=0,
        )
        intro.add_css_class("dim-label")
        root.append(intro)

        self._lan = Gtk.Switch(valign=Gtk.Align.CENTER)
        access = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        access.append(Gtk.Label(
            label=_("Permitir conexões na LAN (porta temporária)"),
            xalign=0, hexpand=True, wrap=True,
        ))
        access.append(self._lan)
        root.append(access)

        warning = Gtk.Label(
            label=_(
                "Desativado: somente este computador (127.0.0.1). "
                "Ativado: escuta na LAN por até 5 minutos; use apenas redes "
                "confiáveis e mantenha o firewall ativo."
            ),
            wrap=True, xalign=0,
        )
        warning.add_css_class("dim-label")
        root.append(warning)

        source_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._choose_source = Gtk.Button(label=_("Selecionar arquivo para enviar…"))
        self._choose_source.connect("clicked", self._pick_file)
        source_row.append(self._choose_source)
        self._kind = Gtk.DropDown.new_from_strings([
            _("ROM própria"), _("Save exportado"), _("Capa"), _("Etiqueta")
        ])
        source_row.append(self._kind)
        root.append(source_row)

        self._file_label = Gtk.Label(
            label=_("Nenhum arquivo selecionado"), xalign=0,
            wrap=True, selectable=True,
        )
        root.append(self._file_label)

        target_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._choose_target = Gtk.Button(label=_("Selecionar pasta para receber…"))
        self._choose_target.connect("clicked", self._pick_folder)
        target_row.append(self._choose_target)
        root.append(target_row)
        self._folder_label = Gtk.Label(
            label=_("Nenhuma pasta selecionada"),
            xalign=0, wrap=True, selectable=True,
        )
        root.append(self._folder_label)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._send = Gtk.Button(label=_("Iniciar envio"), sensitive=False)
        self._send.connect("clicked", self._start_send)
        actions.append(self._send)
        self._receive = Gtk.Button(label=_("Aguardar recebimento"), sensitive=False)
        self._receive.connect("clicked", self._start_receive)
        actions.append(self._receive)
        self._cancel = Gtk.Button(label=_("Encerrar sessão"), sensitive=False)
        self._cancel.connect("clicked", self._stop_session)
        actions.append(self._cancel)
        root.append(actions)

        self._status = Gtk.Label(
            label=_("Sessão desligada"), xalign=0, wrap=True,
            selectable=True,
        )
        root.append(self._status)
        self._credentials = Gtk.Label(
            label="", xalign=0, wrap=True, selectable=True,
        )
        root.append(self._credentials)

        scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
        )
        scroll.set_child(root)
        self.set_content(scroll)

    def _pick_file(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title(_("Escolher arquivo pessoal para compartilhar"))
        dialog.open(self, None, self._file_chosen)

    def _file_chosen(self, chooser, result) -> None:
        try:
            file = chooser.open_finish(result)
        except Exception:
            return
        path = file.get_path() if file else None
        if not path:
            self._status.set_label(_("Arquivo não acessível via portal"))
            return
        self._selected_file = Path(path)
        self._file_label.set_label(self._selected_file.name)
        self._controls()

    def _pick_folder(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title(_("Escolher pasta para receber arquivos"))
        dialog.select_folder(self, None, self._folder_chosen)

    def _folder_chosen(self, chooser, result) -> None:
        try:
            file = chooser.select_folder_finish(result)
        except Exception:
            return
        path = file.get_path() if file else None
        if not path:
            self._status.set_label(_("Pasta não acessível via portal"))
            return
        self._selected_folder = Path(path)
        self._folder_label.set_label(self._selected_folder.name)
        self._controls()

    def _controls(self) -> None:
        self._send.set_sensitive(not self._busy and self._selected_file is not None)
        self._receive.set_sensitive(
            not self._busy and self._selected_folder is not None
        )
        self._choose_source.set_sensitive(not self._busy)
        self._choose_target.set_sensitive(not self._busy)
        self._kind.set_sensitive(not self._busy)
        self._lan.set_sensitive(not self._busy)
        self._cancel.set_sensitive(self._busy)

    def _prepare_session(self) -> str | None:
        if self._busy:
            return None
        self._busy = True
        self._stop = threading.Event()
        self._credentials.set_label("")
        self._status.set_label(_("Criando sessão TLS temporária…"))
        self._controls()
        return "0.0.0.0" if self._lan.get_active() else "127.0.0.1"

    def _start_send(self, _button: Gtk.Button) -> None:
        if self._selected_file is None:
            return
        bind = self._prepare_session()
        if bind is None:
            return
        source = self._selected_file
        kind = _KINDS[self._kind.get_selected()]
        threading.Thread(
            target=self._run_sender,
            args=(source, kind, bind, self._stop),
            name="jolven-nearby-send", daemon=True,
        ).start()

    def _run_sender(
        self, source: Path, kind: str, bind: str, stop: threading.Event
    ) -> None:
        try:
            server, temporary, info, deadline = create_sender(
                [(source, kind)], bind_address=bind, session_seconds=300,
            )
            GLib.idle_add(self._show_session, info, _("Enviando"))
            serve_sender(server, temporary, deadline, stop)
            message = _("Sessão de envio encerrada")
        except Exception:
            message = _("Não foi possível iniciar ou concluir o envio")
        GLib.idle_add(self._finish_session, message)

    def _start_receive(self, _button: Gtk.Button) -> None:
        if self._selected_folder is None:
            return
        bind = self._prepare_session()
        if bind is None:
            return
        dest = self._selected_folder
        threading.Thread(
            target=self._run_receiver,
            args=(dest, bind, self._stop),
            name="jolven-nearby-receive", daemon=True,
        ).start()

    def _run_receiver(
        self, destination: Path, bind: str, stop: threading.Event
    ) -> None:
        try:
            server, temporary, state, info, deadline = create_receiver(
                destination, bind_address=bind,
                session_seconds=300, approve_offer=self._approve_offer,
            )
            GLib.idle_add(self._show_session, info, _("Recebendo"))
            serve_receiver(server, temporary, state, deadline, stop)
            message = (
                _("Arquivo recebido com verificação de integridade")
                if state["finished"] else _("Sessão de recepção encerrada")
            )
        except Exception:
            message = _("Não foi possível iniciar ou concluir o recebimento")
        GLib.idle_add(self._finish_session, message)

    def _approve_offer(self, entries) -> bool:
        """Invoked on the receiving worker; defaults to deny after timeout."""
        if self._closing or self._stop.is_set():
            return False
        approved = [False]
        answered = threading.Event()
        self._pending_approval = answered
        GLib.idle_add(self._display_approval, entries, approved, answered)
        answered.wait(timeout=45)
        self._pending_approval = None
        return approved[0] and not self._stop.is_set() and not self._closing

    def _display_approval(self, entries, approved, answered) -> bool:
        if self._closing or self._stop.is_set():
            answered.set()
            return GLib.SOURCE_REMOVE
        descriptions = "\n".join(
            "- {} ({} bytes, {})".format(item.name, item.size, item.kind)
            for item in entries[:12]
        )
        if len(entries) > 12:
            descriptions += "\n" + _("Mais arquivos estão na oferta")
        popup = Adw.AlertDialog.new(
            _("Aceitar os arquivos oferecidos?"),
            descriptions,
        )
        popup.add_response("reject", _("Recusar"))
        popup.add_response("accept", _("Aceitar todos"))
        popup.set_response_appearance("accept", Adw.ResponseAppearance.SUGGESTED)
        popup.set_close_response("reject")

        def responded(_dialog, choice: str) -> None:
            approved[0] = choice == "accept"
            answered.set()

        popup.connect("response", responded)
        popup.present(self)
        return GLib.SOURCE_REMOVE

    def _show_session(self, info, mode: str) -> bool:
        if self._closing:
            return GLib.SOURCE_REMOVE
        self._status.set_label(
            _("{} — porta {}, expira em até 5 minutos").format(
                mode, info.port
            )
        )
        self._credentials.set_label(
            _("No Android, use o IP do PC na rede e esta porta.\n"
              "Fingerprint SHA-256:\n{}\nToken de sessão:\n{}").format(
                info.fingerprint, info.token,
            )
        )
        return GLib.SOURCE_REMOVE

    def _stop_session(self, _button: Gtk.Button) -> None:
        self._stop.set()
        if self._pending_approval:
            self._pending_approval.set()
        self._status.set_label(_("Encerrando sessão…"))

    def _finish_session(self, message: str) -> bool:
        if self._closing:
            return GLib.SOURCE_REMOVE
        self._busy = False
        self._credentials.set_label("")
        self._status.set_label(message)
        self._controls()
        return GLib.SOURCE_REMOVE

    def _on_close(self, *_args) -> bool:
        self._closing = True
        self._stop.set()
        if self._pending_approval:
            self._pending_approval.set()
        return False


def open_nearby_dialog(parent: Gtk.Window) -> None:
    window = NearbyDialog(parent)
    window.present()
