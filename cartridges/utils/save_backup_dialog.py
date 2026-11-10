# SPDX-License-Identifier: GPL-3.0-or-later
"""User-consented GTK pickers for emulator save backup and restore.

Neither picker scans external emulator sandboxes. All I/O is performed off
the GTK main thread; the archive core enforces path and checksum validation.
"""

from __future__ import annotations

import threading
from pathlib import Path

from gi.repository import Adw, GLib, Gtk

from cartridges.utils.emulator_saves import (
    create_save_backup,
    restore_save_backup,
)


class SaveBackupFlow:
    def __init__(self, parent: Gtk.Window) -> None:
        self.parent = parent
        self._selected: list[Path] = []
        self._archive: Path | None = None

    def _toast(self, message: str) -> bool:
        from cartridges import shared
        if shared.win is not None:
            shared.win.toast_queue.add(Adw.Toast.new(message))
        return False

    def _background(self, work, success: str) -> None:
        def run() -> None:
            try:
                work()
            except Exception:
                # Do not log emulator content paths or secrets in UI.
                GLib.idle_add(
                    self._toast, _("Save backup/restore could not be completed")
                )
            else:
                GLib.idle_add(self._toast, success)

        threading.Thread(target=run, daemon=True, name="jolven-save-backup").start()

    def start_export(self) -> None:
        chooser = Gtk.FileDialog()
        chooser.set_title(_("Select save files to back up"))
        chooser.open_multiple(self.parent, None, self._on_files_selected)

    def _on_files_selected(self, dialog, result) -> None:
        try:
            selected = dialog.open_multiple_finish(result)
        except Exception:  # Cancel or portal failure.
            return
        files = []
        for index in range(selected.get_n_items()):
            item = selected.get_item(index)
            path = item.get_path() if item else None
            if not path:
                self._toast(_("Some selected files are not locally accessible"))
                return
            files.append(Path(path))
        if not files:
            return
        self._selected = files
        chooser = Gtk.FileDialog()
        chooser.set_title(_("Save Jolven backup archive"))
        chooser.set_initial_name("jolven-saves.zip")
        chooser.save(self.parent, None, self._on_export_destination)

    def _on_export_destination(self, dialog, result) -> None:
        try:
            destination = dialog.save_finish(result)
        except Exception:
            return
        path = destination.get_path() if destination else None
        if not path:
            self._toast(_("Backup destination is not locally accessible"))
            return
        self._background(
            lambda: create_save_backup(self._selected, Path(path)),
            _("Save backup exported"),
        )

    def start_restore(self) -> None:
        chooser = Gtk.FileDialog()
        chooser.set_title(_("Select a Jolven save backup ZIP"))
        chooser.open(self.parent, None, self._on_backup_selected)

    def _on_backup_selected(self, dialog, result) -> None:
        try:
            selected = dialog.open_finish(result)
        except Exception:
            return
        path = selected.get_path() if selected else None
        if not path:
            self._toast(_("Backup archive is not locally accessible"))
            return
        self._archive = Path(path)
        chooser = Gtk.FileDialog()
        chooser.set_title(_("Choose folder to restore save files"))
        chooser.select_folder(self.parent, None, self._on_restore_destination)

    def _on_restore_destination(self, dialog, result) -> None:
        try:
            selected = dialog.select_folder_finish(result)
        except Exception:
            return
        path = selected.get_path() if selected else None
        if not path or self._archive is None:
            self._toast(_("Select an accessible folder"))
            return
        archive = self._archive
        self._background(
            lambda: restore_save_backup(archive, Path(path)),
            _("Save files restored"),
        )


def export_emulator_saves(parent: Gtk.Window) -> None:
    SaveBackupFlow(parent).start_export()


def restore_emulator_saves(parent: Gtk.Window) -> None:
    SaveBackupFlow(parent).start_restore()
