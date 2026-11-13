# SPDX-License-Identifier: GPL-3.0-or-later
"""Small GTK/libadwaita manager for Jolven's offline playlists."""

from __future__ import annotations

from gi.repository import Adw, Gtk

from cartridges import shared
from cartridges.utils.playlists import PlaylistStore


class PlaylistsDialog(Adw.Dialog):
    def __init__(self):
        super().__init__()
        self.set_title(_("My Playlists"))
        self.set_content_width(720)
        self.set_content_height(520)
        self.store = PlaylistStore(shared.app_dir / "playlists.json")

        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        add = Gtk.Button(icon_name="list-add-symbolic")
        add.set_tooltip_text(_("New Playlist"))
        add.connect("clicked", self._new)
        header.pack_start(add)
        view.add_top_bar(header)

        scroll = Gtk.ScrolledWindow()
        self.list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list_box.add_css_class("boxed-list")
        scroll.set_child(self.list_box)
        view.set_content(scroll)
        self.set_child(view)
        self._refresh()

    def _notify(self, message: str) -> None:
        shared.win.toast_queue.add(Adw.Toast.new(message))

    def _refresh(self) -> None:
        while row := self.list_box.get_first_child():
            self.list_box.remove(row)

        try:
            playlists = self.store.all()
        except ValueError:
            self._notify(_("Could not read playlists; existing file was preserved"))
            return

        if not playlists:
            self.list_box.append(Gtk.Label(
                label=_("No playlists yet. Use + to create one."),
                margin_top=20,
                margin_bottom=20,
            ))

        active = getattr(shared.win, "active_game", None)
        current_game = getattr(active, "game_id", None)
        for playlist in playlists:
            identifier = playlist["id"]
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                          margin_top=8, margin_bottom=8,
                          margin_start=12, margin_end=12)
            label = Gtk.Label(
                label="{} ({})".format(playlist["title"], len(playlist["games"])),
                xalign=0,
                hexpand=True,
                ellipsize=3,
            )
            row.append(label)

            if current_game:
                included = current_game in playlist["games"]
                toggle = Gtk.Button(
                    label=_("Remove game") if included else _("Add active game")
                )
                toggle.connect("clicked", self._toggle, identifier, current_game, not included)
                row.append(toggle)

            rename = Gtk.Button(icon_name="document-edit-symbolic")
            rename.set_tooltip_text(_("Rename Playlist"))
            rename.connect("clicked", self._rename, identifier, playlist["title"])
            row.append(rename)

            delete = Gtk.Button(icon_name="user-trash-symbolic")
            delete.set_tooltip_text(_("Delete Playlist"))
            delete.add_css_class("destructive-action")
            delete.connect("clicked", self._delete, identifier, playlist["title"])
            row.append(delete)
            self.list_box.append(row)

    def _prompt(self, title: str, old_name: str, on_confirm) -> None:
        prompt = Adw.AlertDialog.new(title, _("Enter a playlist name"))
        entry = Gtk.Entry(text=old_name, max_length=72)
        prompt.set_extra_child(entry)
        prompt.add_response("cancel", _("Cancel"))
        prompt.add_response("save", _("Save"))
        prompt.set_default_response("save")
        prompt.set_close_response("cancel")

        def response(_dialog, selected: str):
            if selected != "save":
                return
            name = entry.get_text().strip()
            if not name:
                return
            try:
                on_confirm(name)
                self._refresh()
            except (ValueError, KeyError):
                self._notify(_("Could not update playlist"))
        prompt.connect("response", response)
        prompt.present(self)

    def _new(self, _button) -> None:
        self._prompt(_("New Playlist"), "", self.store.create)

    def _rename(self, _button, playlist_id: str, old_name: str) -> None:
        self._prompt(
            _("Rename Playlist"), old_name,
            lambda name: self.store.rename(playlist_id, name),
        )

    def _toggle(self, _button, playlist_id: str, game_id: str, include: bool) -> None:
        try:
            self.store.set_member(playlist_id, game_id, include)
            self._refresh()
        except (ValueError, KeyError):
            self._notify(_("Could not update playlist"))

    def _delete(self, _button, playlist_id: str, title: str) -> None:
        alert = Adw.AlertDialog.new(
            _("Delete Playlist"),
            _("Delete {}? The games themselves will not be removed.").format(title),
        )
        alert.add_response("cancel", _("Cancel"))
        alert.add_response("delete", _("Delete"))
        alert.set_close_response("cancel")
        alert.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def response(_dialog, selected: str):
            if selected == "delete":
                try:
                    self.store.delete(playlist_id)
                    self._refresh()
                except (ValueError, KeyError):
                    self._notify(_("Could not delete playlist"))
        alert.connect("response", response)
        alert.present(self)


def show_playlists(parent: Gtk.Window) -> None:
    PlaylistsDialog().present(parent)
