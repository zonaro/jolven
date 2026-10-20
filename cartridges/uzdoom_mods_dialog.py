# uzdoom_mods_dialog.py
#
# SPDX-License-Identifier: GPL-3.0-or-later
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

"""Per-game selection and ordering of the UZDoom mods.

UZDoom loads a PWAD (or a PK3 archive) on top of an IWAD with the ``-file``
flag, and it accepts several of them: the last one loaded wins, so the order
is part of the configuration. This dialog lists the mods found in the folder
picked in Preferences, lets the user choose which ones are loaded and in
which order, and stores the result in the game.

The folder is scanned in a worker thread: reading the header of every WAD of
a big collection is slow enough to freeze the interface, and GTK must never
be touched outside the main thread.
"""

import logging
import threading
from pathlib import Path
from typing import Any, Optional

from gi.repository import Adw, Gtk

from cartridges import shared
from cartridges.game import Game
from cartridges.utils.na_tela import entregar_na_tela


#: Magic header of a ZDoom PWAD file. The mods are the WADs that are not
#: IWADs: the IWAD is the game itself and is never listed here.
PWAD_MAGIC = b"PWAD"

#: Archives that hold mods. They are accepted by their extension alone: a
#: PK3 is a zip file and reading its content would cost much more than what
#: the extension already tells us.
ARCHIVE_SUFFIXES = (".pk3", ".ipk3")

#: Size of the move buttons in session mode, where the controls are used
#: with a gamepad from a distance.
SESSION_BUTTON_SIZE = 44


def scan_mods(folder: Optional[Path]) -> list[str]:
    """Return the mod candidates of *folder*, sorted by file name.

    A WAD is a candidate when its header says it is a PWAD; an archive is a
    candidate when its name ends with a known mod extension. The folder is
    read from a worker thread, so nothing here may touch GTK.
    """

    if folder is None:
        return []

    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return []

    mods: list[str] = []
    for path in entries:
        try:
            if not path.is_file():
                continue
        except OSError:
            continue

        suffix = path.suffix.lower()
        if suffix in ARCHIVE_SUFFIXES:
            mods.append(str(path))
            continue

        if suffix != ".wad":
            continue

        try:
            with path.open("rb") as wad_file:
                magic = wad_file.read(4)
        except OSError:
            continue

        if magic == PWAD_MAGIC:
            mods.append(str(path))

    return mods


def merge_mods(found: list[str], saved: list[str]) -> list[str]:
    """Combine the mods found on disk with the ones already saved.

    The saved mods come first, in the order the game loads them, so opening
    the dialog never silently reorders the current selection. A saved mod
    whose file is gone is kept: the file may come back, and dropping it
    without asking would change the game behind the user's back.
    """

    known: dict[str, str] = {}
    for mod in found:
        known.setdefault(str(Path(mod)), mod)

    merged: list[str] = []
    used: set[str] = set()
    for mod in saved:
        key = str(Path(mod))
        merged.append(known.get(key, key))
        used.add(key)

    for key, mod in known.items():
        if key not in used:
            merged.append(mod)

    return merged


@Gtk.Template(resource_path=shared.PREFIX + "/gtk/uzdoom-mods-dialog.ui")
class UzdoomModsDialog(Adw.Dialog):
    """Choose which mods a UZDoom game loads, and in which order."""

    __gtype_name__ = "UzdoomModsDialog"

    mods_list: Gtk.ListBox = Gtk.Template.Child()
    empty_state_row: Gtk.Label = Gtk.Template.Child()
    apply_button: Gtk.Button = Gtk.Template.Child()
    cancel_button: Gtk.Button = Gtk.Template.Child()

    def __init__(self, game: Game, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.game = game
        self._closed = False
        self._scanned = False
        # Path and check button of every row. The rows move around when the
        # user reorders them, so the order is read from the list box itself
        # instead of from a parallel list.
        self._paths: dict[Gtk.ListBoxRow, str] = {}
        self._checks: dict[Gtk.ListBoxRow, Gtk.CheckButton] = {}

        self.set_title(_("Mods"))
        self.apply_button.connect("clicked", self.on_apply)
        self.connect("closed", self.on_closed)

    def present(self, parent: Optional[Gtk.Widget] = None) -> None:
        super().present(parent)
        self.start_scan()

    # region Scanning

    @staticmethod
    def mod_folder() -> Optional[Path]:
        """The folder picked in Preferences, when it holds a directory."""

        raw = shared.schema.get_string("uzdoom-location").strip()
        if not raw:
            return None
        try:
            folder = Path(raw).expanduser()
        except (OSError, RuntimeError, ValueError):
            return None
        if not folder.is_dir():
            return None
        return folder

    def start_scan(self) -> None:
        """Read the folder in a worker and deliver the result to the screen."""

        if self._scanned:
            return
        self._scanned = True

        folder = self.mod_folder()
        saved = list(getattr(self.game, "uzdoom_mods", None) or [])
        threading.Thread(
            target=self.scan_thread, args=(folder, saved), daemon=True
        ).start()

    def scan_thread(self, folder: Optional[Path], saved: list[str]) -> None:
        try:
            found = scan_mods(folder)
        except Exception as error:  # pylint: disable=broad-except
            # A folder that cannot be read must not leave the dialog empty:
            # the mods already saved still have to show up.
            logging.warning("Could not scan the UZDoom folder: %s", error)
            found = []

        merged = merge_mods(found, saved)
        entregar_na_tela(self.show_mods, found, merged, saved)

    def show_mods(
        self, found: list[str], merged: list[str], saved: list[str]
    ) -> bool:
        """Fill the list with the scanned mods. Runs on the main thread."""

        if self._closed:
            return False

        self.mods_list.remove_all()
        self._paths.clear()
        self._checks.clear()

        selected = {str(Path(mod)) for mod in saved}
        for path in merged:
            self.build_row(path, str(Path(path)) in selected)

        # The note tells the user why the list is empty (or short): no mod
        # was found in the folder. It shows even when the game already has
        # mods saved, because those mods are not in the folder.
        self.empty_state_row.set_visible(not found)
        return False

    # endregion
    # region Rows

    def build_row(self, path: str, included: bool) -> None:
        """Add a row for the mod at *path*."""

        row = Adw.ActionRow()
        row.set_title(Path(path).name)

        if Path(path).is_file():
            row.set_subtitle(path)
        else:
            row.set_subtitle(_("Missing file"))
            row.set_tooltip_text(path)

        check = Gtk.CheckButton()
        check.set_active(included)
        check.set_tooltip_text(_("Load this mod"))
        check.update_property(
            (Gtk.AccessibleProperty.LABEL,), (_("Load this mod"),)
        )

        up = Gtk.Button(icon_name="go-up-symbolic", tooltip_text=_("Move up"))
        up.add_css_class("flat")
        up.update_property((Gtk.AccessibleProperty.LABEL,), (_("Move up"),))

        down = Gtk.Button(icon_name="go-down-symbolic", tooltip_text=_("Move down"))
        down.add_css_class("flat")
        down.update_property((Gtk.AccessibleProperty.LABEL,), (_("Move down"),))

        if shared.runtime.is_session:
            for button in (check, up, down):
                button.set_size_request(SESSION_BUTTON_SIZE, SESSION_BUTTON_SIZE)

        suffix = Gtk.Box(spacing=6)
        suffix.append(check)
        suffix.append(up)
        suffix.append(down)
        row.add_suffix(suffix)

        up.connect("clicked", self.on_move, row, -1)
        down.connect("clicked", self.on_move, row, 1)

        self._paths[row] = path
        self._checks[row] = check
        self.mods_list.append(row)

    def on_move(
        self, button: Gtk.Button, row: Gtk.ListBoxRow, offset: int
    ) -> None:
        """Swap the row with its neighbour, so the load order changes."""

        index = row.get_index()
        target = index + offset
        if index < 0 or target < 0:
            return

        self.mods_list.remove(row)
        self.mods_list.insert(row, target)

        # The row was detached and put back: give the focus back to the
        # button that was pressed, so the keyboard and the gamepad keep
        # driving the same control.
        button.grab_focus()

    def selected_paths(self) -> list[str]:
        """The paths of the checked rows, in the order they are shown."""

        paths: list[str] = []
        child = self.mods_list.get_first_child()
        while child is not None:
            path = self._paths.get(child)
            check = self._checks.get(child)
            if path is not None and check is not None and check.get_active():
                paths.append(path)
            child = child.get_next_sibling()
        return paths

    # endregion
    # region Applying

    def on_apply(self, *_args: Any) -> None:
        self.game.uzdoom_mods = self.selected_paths()
        self.game.save()
        self.game.update()
        self.close()

    def on_closed(self, *_args: Any) -> None:
        self._closed = True

    # endregion
