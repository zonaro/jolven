"""Pure-python tests for the AppImage source.

The module under test lives behind Gtk/GSettings imports (`cartridges.game`,
`cartridges.shared`) that do not exist in a bare source tree, so those two
dependencies are stubbed in `sys.modules` before import — exactly the parts
the exercised code only touches through `Game(values)` and
`shared.import_time`/`shared.schema`/`shared.home`. Everything asserted here
(file detection, name cleaning, launcher classification, desktop entries and
the iteration of the source) runs with no display, no GTK and no GSettings
database.
"""

import builtins
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

import gi

gi.require_version("Gtk", "4.0")


class _StubSchema:
    def __init__(self):
        self.strings = {}
        self.booleans = {}

    def get_string(self, key):
        return self.strings.get(key, "")

    def get_boolean(self, key):
        return self.booleans.get(key, False)

    def set_string(self, key, value):
        self.strings[key] = value


class _StubShared:
    def __init__(self):
        self.schema = _StubSchema()
        self.import_time = 1234567890
        # Pointers that do not exist, so a source only finds something when
        # a test explicitly places an AppImage inside one of them.
        self.home = Path("/nonexistent/jolven-home")
        self.host_data_dir = Path("/nonexistent/jolven-host-data")
        self.data_dir = Path("/nonexistent/jolven-data")


class _StubGame:
    """Records the values dict like `Game.update_values` would."""

    def __init__(self, values):
        self.values = dict(values)
        for key, value in values.items():
            setattr(self, key, value)


_STUB_SHARED = _StubShared()
_STUB_GAME_MODULE = type("game", (), {"Game": _StubGame})

# The stubs must win over the real modules even when another test module
# already imported them: `from cartridges import shared` resolves the
# attribute of the package first, and the location/source modules bind
# `shared` at import time. So the stubs are installed, the modules that
# bind them are re-imported, and the environment is restored afterwards.
import cartridges  # noqa: E402
import cartridges.importer  # noqa: E402

_STUBBED_MODULES = (
    "cartridges.shared",
    "cartridges.game",
    "cartridges.importer.location",
    "cartridges.importer.source",
)
_originals = {name: sys.modules.pop(name, None) for name in _STUBBED_MODULES}

sys.modules["cartridges.shared"] = _STUB_SHARED
sys.modules["cartridges.game"] = _STUB_GAME_MODULE
setattr(cartridges, "shared", _STUB_SHARED)
setattr(cartridges, "game", _STUB_GAME_MODULE)

from cartridges.utils import appimage_scan  # noqa: E402
from cartridges.utils.appimage_scan import (  # noqa: E402
    clean_appimage_name,
    default_roots,
    desktop_index,
    find_appimages,
    find_desktop_entry,
    is_appimage,
    is_launcher_name,
    programs_from_exec,
)
from cartridges.importer import appimage_source  # noqa: E402
from cartridges.importer.appimage_source import (  # noqa: E402
    AppimageSource,
    AppimageSourceIterable,
)
from cartridges.utils import launcher  # noqa: E402


def _restore_module(name: str, module) -> None:
    """Put back a module the tests replaced.

    Both the entry of `sys.modules` and the attribute of the package are
    restored: `from cartridges import shared` looks at the attribute first,
    so a stub left behind would follow into the other test modules.
    """
    if module is None:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = module

    parent_name, _, attribute = name.rpartition(".")
    parent = sys.modules.get(parent_name)
    if parent is None:
        return
    if module is None:
        if hasattr(parent, attribute):
            delattr(parent, attribute)
    else:
        setattr(parent, attribute, module)


for _name, _module in _originals.items():
    _restore_module(_name, _module)

# The modules of this source are dropped as well: the next test that
# imports them gets them bound to the real `shared`, and not to the stub.
for _name in (
    "cartridges.importer.appimage_source",
    "cartridges.utils.appimage_scan",
    "cartridges.utils.launcher",
):
    _restore_module(_name, None)

# The stub is still the `shared` the source module binds, so the tests can
# retarget the home of the user.
_shared_stub = appimage_source.shared


class AppimageScanTestCase(unittest.TestCase):
    """The pure part: what is an AppImage and what it is called."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def write_appimage(self, name: str, magic: bytes = b"AI\x02") -> Path:
        """A file that looks like an AppImage."""
        path = self.tmp / name
        path.write_bytes(magic + b"\x00" * 64)
        path.chmod(0o755)
        return path

    def test_magic_number_is_an_appimage(self):
        path = self.write_appimage("Game.bin", magic=b"AI\x02")
        self.assertTrue(is_appimage(path))

    def test_old_magic_number_is_an_appimage(self):
        path = self.write_appimage("Game.bin", magic=b"AI\x01")
        self.assertTrue(is_appimage(path))

    def test_elf_file_named_appimage_is_an_appimage(self):
        path = self.tmp / "Game.AppImage"
        path.write_bytes(b"\x7fELF" + b"\x00" * 64)
        self.assertTrue(is_appimage(path))

    def test_text_file_named_appimage_is_not_an_appimage(self):
        path = self.tmp / "notes.appimage"
        path.write_text("just a note")
        self.assertFalse(is_appimage(path))

    def test_elf_file_without_the_suffix_is_not_an_appimage(self):
        path = self.tmp / "Game.bin"
        path.write_bytes(b"\x7fELF" + b"\x00" * 64)
        self.assertFalse(is_appimage(path))

    def test_find_appimages_in_a_folder(self):
        game = self.write_appimage("Game.AppImage")
        self.write_appimage("Other.AppImage")
        (self.tmp / "notes.txt").write_text("hello")

        found = find_appimages([self.tmp])

        self.assertIn(game, found)
        self.assertEqual(len(found), 2)

    def test_find_appimages_ignores_a_missing_folder(self):
        self.assertEqual(find_appimages([self.tmp / "nope"]), [])

    def test_find_appimages_stops_at_the_depth(self):
        deep = self.tmp / "one" / "two"
        deep.mkdir(parents=True)
        deep_file = deep / "Game.AppImage"
        deep_file.write_bytes(b"AI\x02" + b"\x00" * 64)

        self.assertEqual(find_appimages([self.tmp], max_depth=1), [])
        self.assertEqual(find_appimages([self.tmp], max_depth=2), [deep_file])

    def test_name_without_the_packaging_noise(self):
        self.assertEqual(
            clean_appimage_name("SuperTuxKart-0.6.1-x86_64"), "SuperTuxKart"
        )
        self.assertEqual(clean_appimage_name("Celeste-1.4.0.0-x86_64"), "Celeste")
        self.assertEqual(clean_appimage_name("retroarch-1.16.0-x86_64"), "retroarch")
        self.assertEqual(clean_appimage_name("Game"), "Game")

    def test_name_keeps_a_number_that_belongs_to_the_title(self):
        self.assertEqual(clean_appimage_name("Portal 2"), "Portal 2")
        self.assertEqual(clean_appimage_name("Half-Life 2"), "Half-Life 2")

    def test_name_drops_the_suffix_and_the_platform(self):
        self.assertEqual(clean_appimage_name("Game.AppImage"), "Game")
        self.assertEqual(clean_appimage_name("Game-linux-x86_64"), "Game")

    def test_known_launchers_are_recognized(self):
        for name in ("RetroArch", "retroarch", "Lutris", "Heroic", "itch", "Steam"):
            self.assertTrue(is_launcher_name(name), name)

    def test_a_game_that_starts_with_a_launcher_name_is_not_a_launcher(self):
        self.assertFalse(is_launcher_name("Itchy"))
        self.assertFalse(is_launcher_name("Steamer"))
        self.assertFalse(is_launcher_name("Hades"))

    def test_a_launcher_with_a_suffix_is_recognized(self):
        self.assertTrue(is_launcher_name("Steam Linux Runtime"))
        self.assertTrue(is_launcher_name("Heroic Games Launcher"))

    def test_an_ambiguous_name_is_not_a_launcher(self):
        self.assertFalse(is_launcher_name("Dolphin Tale"))
        self.assertFalse(is_launcher_name("Eden Legacy"))

    def test_the_id_comes_from_the_name_of_the_file(self):
        path = Path("/home/user/.local/bin/SuperTuxKart-0.6.1-x86_64.AppImage")
        self.assertEqual(
            appimage_scan.appimage_id(path), "SuperTuxKart-0.6.1-x86_64"
        )

    def test_the_id_has_no_unsafe_character(self):
        path = Path("/tmp/Game & Co!.AppImage")
        self.assertEqual(appimage_scan.appimage_id(path), "Game-Co")

    def test_default_roots_are_the_usual_folders(self):
        roots = default_roots(Path("/home/user"))

        self.assertIn(Path("/home/user/.local/bin"), roots)
        self.assertIn(Path("/home/user/Applications"), roots)
        self.assertIn(Path("/home/user/bin"), roots)

    def test_default_roots_take_the_extra_folder(self):
        roots = default_roots(Path("/home/user"), "/opt/games")

        self.assertIn(Path("/opt/games"), roots)

    def test_the_extra_folder_is_made_absolute(self):
        roots = default_roots(Path("/home/user"), "games")

        self.assertIn(Path.cwd() / "games", roots)


class DesktopEntryTestCase(unittest.TestCase):
    """The desktop entries that may exist for an AppImage."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_programs_of_an_exec_line(self):
        programs = programs_from_exec("/home/user/Game.AppImage %U")

        self.assertEqual(programs, (Path("/home/user/Game.AppImage"),))

    def test_programs_ignore_the_environment_and_the_codes(self):
        programs = programs_from_exec("env FOO=bar /home/user/Game.AppImage %F")

        self.assertEqual(programs, (Path("/home/user/Game.AppImage"),))

    def test_programs_of_a_relative_exec_line(self):
        self.assertEqual(programs_from_exec("Game.AppImage %U"), ())

    def test_an_entry_that_runs_another_program_is_not_matched(self):
        game = self.tmp / "Game.AppImage"
        game.write_bytes(b"AI\x02" + b"\x00" * 64)
        desktop = self.tmp / "game.desktop"
        desktop.write_text(
            "[Desktop Entry]\n"
            "Name=My Game\n"
            "Exec=/path/to/other %U\n"
            "Categories=Game;\n"
        )

        index = desktop_index([self.tmp])
        entry = find_desktop_entry(index, game)

        self.assertIsNone(entry)

    def test_the_entry_that_runs_the_program_is_found(self):
        game = self.tmp / "Game.AppImage"
        game.write_bytes(b"AI\x02" + b"\x00" * 64)
        desktop = self.tmp / "game.desktop"
        desktop.write_text(
            "[Desktop Entry]\n"
            "Name=My Game\n"
            "Exec=" + str(game) + " %U\n"
            "Categories=Game;\n"
            "Icon=my-game\n"
        )

        index = desktop_index([self.tmp])
        entry = find_desktop_entry(index, game)

        self.assertIsNotNone(entry)
        self.assertEqual(entry.name, "My Game")
        self.assertEqual(entry.icon, "my-game")
        self.assertIn("game", entry.categories)


class AppimageSourceTestCase(unittest.TestCase):
    """The source itself: what it puts in the library."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

        self.home = self.tmp / "home"
        self.bin = self.home / ".local" / "bin"
        self.bin.mkdir(parents=True)

        self._old_home = _shared_stub.home
        self.addCleanup(self._restore_home)
        _shared_stub.home = self.home

        self._old_booleans = dict(_shared_stub.schema.booleans)
        self.addCleanup(self._restore_booleans)
        _shared_stub.schema.booleans.clear()

    def _restore_home(self):
        _shared_stub.home = self._old_home

    def _restore_booleans(self):
        _shared_stub.schema.booleans = self._old_booleans

    def write_appimage(self, name: str, magic: bytes = b"AI\x02") -> Path:
        path = self.bin / name
        path.write_bytes(magic + b"\x00" * 64)
        path.chmod(0o755)
        return path

    def games(self) -> list:
        source = AppimageSource()
        return list(AppimageSourceIterable(source))

    def test_a_game_is_imported(self):
        game_file = self.write_appimage("SuperTuxKart-0.6.1-x86_64.AppImage")

        games = self.games()

        self.assertEqual(len(games), 1)
        game, _additional = games[0]
        self.assertEqual(game.source, "appimage")
        self.assertEqual(game.name, "SuperTuxKart")
        self.assertEqual(game.game_id, "appimage_SuperTuxKart-0.6.1-x86_64")
        self.assertEqual(game.executable, str(game_file))
        self.assertEqual(game.launch_working_directory, str(self.bin))

    def test_the_command_quotes_a_path_with_spaces(self):
        game_file = self.write_appimage("My Game.AppImage")

        games = self.games()

        self.assertEqual(games[0][0].executable, shlex.quote(str(game_file)))

    def test_a_launcher_is_not_imported_by_default(self):
        self.write_appimage("RetroArch-1.16.0-x86_64.AppImage")

        self.assertEqual(self.games(), [])

    def test_a_launcher_is_imported_when_the_user_asks_for_it(self):
        self.write_appimage("RetroArch-1.16.0-x86_64.AppImage")
        _shared_stub.schema.booleans["appimage-import-launchers"] = True

        games = self.games()

        self.assertEqual(len(games), 1)
        self.assertEqual(games[0][0].name, "RetroArch")

    def test_the_icon_next_to_the_game_is_used(self):
        self.write_appimage("SuperTuxKart-0.6.1-x86_64.AppImage")
        icon = self.bin / "SuperTuxKart.png"
        icon.write_bytes(b"\x89PNG\r\n\x1a\n")

        games = self.games()

        self.assertEqual(games[0][1], {"local_icon_path": icon})

    def test_two_games_of_the_same_name_are_told_apart(self):
        other = self.home / "Applications"
        other.mkdir(parents=True)
        self.write_appimage("Game.AppImage")
        second = other / "Game.AppImage"
        second.write_bytes(b"AI\x02" + b"\x00" * 64)

        games = self.games()

        self.assertEqual(len(games), 2)
        ids = {game.game_id for game, _ in games}
        self.assertEqual(len(ids), 2)
        self.assertIn("appimage_Game", ids)

    def test_a_file_that_is_not_an_appimage_is_ignored(self):
        (self.bin / "notes.appimage").write_text("just a note")

        self.assertEqual(self.games(), [])


class LauncherDetectionTestCase(unittest.TestCase):
    """The launchers that the source imports are launchers in the UI too."""

    def game(self, name: str, base_source: str = "appimage"):
        return SimpleNamespace(
            base_source=base_source,
            game_id=f"{base_source}_{name}",
            name=name,
        )

    def test_a_launcher_appimage_is_a_launcher(self):
        for name in ("RetroArch", "PlayOnLinux", "Cemu", "itch.io"):
            with self.subTest(name=name):
                self.assertTrue(launcher.detectar(self.game(name)))

    def test_a_game_is_not_a_launcher(self):
        for name in ("SuperTuxKart", "Steamroller", "Eden Legacy"):
            with self.subTest(name=name):
                self.assertFalse(launcher.detectar(self.game(name)))

    def test_the_detection_does_not_reach_the_other_sources(self):
        jogo = self.game("PlayOnLinux", base_source="flatpak")

        self.assertFalse(launcher.detectar(jogo))


if __name__ == "__main__":
    unittest.main()
