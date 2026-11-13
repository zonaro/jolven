# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit, user-driven single-ROM import into Jolven's existing Add Game form.

This flow never extracts archives, downloads cores, edits retroarch.cfg or
inserts an unverified game directly into the Store. The user reviews the
generated command in the normal DetailsDialog and confirms saving.
"""

from __future__ import annotations

from pathlib import Path

from gi.repository import Adw, Gtk

from cartridges.details_dialog import DetailsDialog
from cartridges.importer.manual_roms import (
    detect_rom,
    retroarch_launch_command,
)


class ManualRomImportFlow:
    """Async GTK FileDialog → core selection → editable Add Game dialog."""

    def __init__(self, parent: Gtk.Window) -> None:
        self.parent = parent
        self.rom: Path | None = None
        self.flatpak = False

    def begin(self) -> None:
        if DetailsDialog.is_open:
            return
        dialog = Gtk.FileDialog()
        dialog.set_title(_("Choose a ROM"))
        dialog.open(self.parent, None, self._on_rom_selected)

    def _error(self, title: str, message: str) -> None:
        alert = Adw.AlertDialog.new(title, message)
        alert.add_response("ok", _("OK"))
        alert.set_default_response("ok")
        alert.present(self.parent)

    def _on_rom_selected(self, dialog, result) -> None:
        try:
            gfile = dialog.open_finish(result)
        except Exception:  # User cancellation or portal failure.
            return
        if not gfile:
            return
        path = gfile.get_path()
        if not path:
            self._error(
                _("ROM file unavailable"),
                _("Select a local file accessible through the file portal."),
            )
            return

        candidate = detect_rom(path)
        if candidate.is_unknown:
            self._error(
                _("Unrecognized ROM file"),
                _("This file extension is not in Jolven's console catalog."),
            )
            return
        if not Path(path).is_file():
            self._error(_("ROM file unavailable"), _("The selected file cannot be read."))
            return
        self.rom = Path(path)
        consoles = ", ".join(candidate.platforms) or _("Unknown system")
        detail = (
            _("Multiple consoles can use this file format. Select the correct ")
            + _("core in the next step; Jolven will not guess the console.")
            if candidate.requires_choice
            else _("Detected console candidate: {}").format(consoles)
        )
        chooser = Adw.AlertDialog.new(
            _("Choose RetroArch installation"), detail
        )
        chooser.add_response("cancel", _("Cancel"))
        chooser.add_response("native", _("Native RetroArch"))
        chooser.add_response("flatpak", _("Flatpak RetroArch"))
        chooser.set_close_response("cancel")
        chooser.connect("response", self._on_installation_chosen)
        chooser.present(self.parent)

    def _on_installation_chosen(self, _dialog, response: str) -> None:
        if response not in {"native", "flatpak"}:
            return
        self.flatpak = response == "flatpak"
        dialog = Gtk.FileDialog()
        dialog.set_title(_("Choose the installed libretro core (.so)"))
        core_filter = Gtk.FileFilter()
        core_filter.set_name(_("Libretro cores"))
        core_filter.add_suffix("so")
        dialog.set_default_filter(core_filter)
        dialog.open(self.parent, None, self._on_core_selected)

    def _on_core_selected(self, dialog, result) -> None:
        try:
            gfile = dialog.open_finish(result)
        except Exception:
            return
        if not gfile or self.rom is None:
            return
        core_path = gfile.get_path()
        if not core_path:
            self._error(_("Core unavailable"), _("Choose a readable local core."))
            return
        try:
            command = retroarch_launch_command(
                self.rom, Path(core_path), flatpak=self.flatpak
            )
        except ValueError as error:
            self._error(_("Invalid ROM or core path"), str(error))
            return

        if DetailsDialog.is_open:
            return
        details = DetailsDialog()
        details.name.set_text(self.rom.stem)
        details.executable.set_text(command)
        details.present(self.parent)


def choose_manual_rom(parent: Gtk.Window) -> None:
    """Open a one-at-a-time ROM import wizard from the Add Game menu."""
    ManualRomImportFlow(parent).begin()
