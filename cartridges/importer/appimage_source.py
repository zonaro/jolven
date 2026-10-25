# appimage_source.py
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

"""Source of the games installed as AppImage.

An AppImage is a self-contained executable, so the games are found by
looking for the files in the folders where they are installed, the same
way the Flatpak source finds the exported desktop entries of the flatpaks.
The parsing lives in :mod:`cartridges.utils.appimage_scan`; this module
only joins it with the library.
"""

import builtins
import shlex
from pathlib import Path
from typing import NamedTuple, Optional

from gi.repository import GLib, Gtk

from cartridges import shared
from cartridges.game import Game
from cartridges.importer.source import Source, SourceIterable
from cartridges.utils.appimage_scan import (
    DesktopEntry,
    appimage_id,
    appimage_id_suffix,
    clean_appimage_name,
    default_roots,
    desktop_index,
    find_appimages,
    find_desktop_entry,
    find_sibling_icon,
    is_launcher_name,
)

# O launcher roda ``gettext.install`` antes de importar qualquer módulo do
# app; o fallback mantém este módulo importável em testes e ferramentas sem
# catálogo — o mesmo guarda de ``cartridges/game_session.py``.
if not hasattr(builtins, "_"):
    builtins._ = lambda text: text  # type: ignore[attr-defined]


class AppimageLocations(NamedTuple):
    """The AppImage source has no location to resolve: its folders are the
    ones the platform and the user agreed on, and a missing folder simply
    means that there is nothing to import."""


class AppimageSourceIterable(SourceIterable):
    source: "AppimageSource"

    def __iter__(self):
        """Generator method producing games"""

        import_launchers = shared.schema.get_boolean("appimage-import-launchers")
        roots = self.source.roots()
        if not roots:
            return

        desktop = desktop_index(self.source.desktop_directories())
        icon_theme = self.source.icon_theme()
        used_ids: dict[str, Path] = {}

        for appimage in find_appimages(roots):
            entry = find_desktop_entry(desktop, appimage)
            file_name = clean_appimage_name(appimage.stem)
            name = self.source.display_name(appimage, entry)

            # A launcher is not a game: it only enters the library when the
            # user asks for it, the same way the Flatpak source does.
            if not import_launchers and (
                is_launcher_name(file_name) or is_launcher_name(name)
            ):
                continue

            game_id = self.source.game_id(appimage, used_ids)

            values = {
                "source": self.source.source_id,
                "added": shared.import_time,
                "name": name,
                "game_id": game_id,
                "executable": self.source.make_executable(appimage),
                # An AppImage expects to run from the folder it lives in: it
                # keeps its data and its saves next to itself.
                "launch_working_directory": str(appimage.parent),
            }
            game = Game(values)

            additional_data = {}
            icon = self.source.find_icon(appimage, entry, name, icon_theme)
            if icon is not None:
                additional_data = {"local_icon_path": icon}

            yield (game, additional_data)


class AppimageSource(Source):
    """Games installed as AppImage."""

    source_id = "appimage"
    name = _("AppImage")
    iterable_class = AppimageSourceIterable
    available_on = {"linux"}

    locations: AppimageLocations

    def __init__(self) -> None:
        super().__init__()
        self.locations = AppimageLocations()

    def roots(self) -> list[Path]:
        """The folders where the AppImages are looked for.

        ``shared.home`` is the home of the user even inside the Flatpak
        sandbox: the app is granted ``--filesystem=host``, so the AppImages
        of the user are in the same place they are outside of it.
        """
        return default_roots(
            shared.home, shared.schema.get_string("appimage-location")
        )

    @staticmethod
    def desktop_directories() -> list[Path]:
        """The folders where the desktop entries are looked for."""
        directories = [
            shared.host_data_dir / "applications",
            shared.data_dir / "applications",
            Path("/usr/local/share/applications"),
            Path("/usr/share/applications"),
        ]
        unique: list[Path] = []
        for directory in directories:
            if directory not in unique:
                unique.append(directory)
        return unique

    @staticmethod
    def icon_theme() -> Gtk.IconTheme:
        """An icon theme that knows the folders of the system."""
        theme = Gtk.IconTheme.new()
        for search_path in (
            shared.host_data_dir / "icons",
            shared.data_dir / "icons",
            Path("/usr/local/share/icons"),
            Path("/usr/share/icons"),
            Path("/usr/share/pixmaps"),
        ):
            if search_path.is_dir():
                theme.add_search_path(str(search_path))
        return theme

    @staticmethod
    def display_name(appimage: Path, entry: Optional[DesktopEntry]) -> str:
        """The title of a game, from its desktop entry when there is one."""
        if entry is not None and entry.name:
            return entry.name
        return clean_appimage_name(appimage.stem)

    def game_id(self, appimage: Path, used_ids: dict[str, Path]) -> str:
        """The id of a game, unique in the library.

        The id comes from the name of the file, so it survives the move to
        another folder. Two files of the same name in different folders are
        told apart by a digest of the folder.
        """
        base_id = appimage_id(appimage)
        unique_id = base_id
        owner = used_ids.get(base_id)
        if owner is not None and owner != appimage:
            unique_id = f"{base_id}-{appimage_id_suffix(appimage)}"
        used_ids[base_id] = appimage
        return self.game_id_format.format(game_id=unique_id)

    @staticmethod
    def make_executable(appimage: Path) -> str:
        """The command that runs an AppImage.

        The path is quoted: the Jolven runs the command through a shell and
        a folder with spaces must not become two arguments.
        """
        return shlex.quote(str(appimage))

    @staticmethod
    def find_icon(
        appimage: Path,
        entry: Optional[DesktopEntry],
        name: str,
        icon_theme: Gtk.IconTheme,
    ) -> Optional[Path]:
        """The icon of a game, when one can be found."""
        if entry is not None and entry.icon:
            icon = AppimageSource.resolve_icon(entry.icon, icon_theme)
            if icon is not None:
                return icon

        icon = find_sibling_icon(appimage, [name])
        if icon is not None:
            return icon

        return AppimageSource.resolve_icon(name, icon_theme)

    @staticmethod
    def resolve_icon(icon_name: str, icon_theme: Gtk.IconTheme) -> Optional[Path]:
        """The file of an icon of the theme, when the theme knows it."""
        if not icon_name:
            return None

        if "/" in icon_name:
            path = Path(icon_name).expanduser()
            return path if path.is_file() else None

        try:
            icon = icon_theme.lookup_icon(
                icon_name, None, 512, 1, Gtk.Orientation.HORIZONTAL, 0
            )
        except GLib.Error:
            return None

        if icon is None:
            return None

        file = icon.get_file()
        if file is None:
            return None

        path = file.get_path()
        return Path(path) if path else None
