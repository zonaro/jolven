"""Pure-python tests for the Cemu source.

The module under test lives behind Gtk/GSettings imports (`cartridges.game`,
`cartridges.shared`) that do not exist in a bare source tree, so those two
dependencies are stubbed in `sys.modules` before import — exactly the parts
the exercised code only touches through `Game(values)` and
`shared.import_time`/`shared.schema`. Everything asserted here (merging of
the legacy cache, of the title list cache and of the scan, game id
stability, command quoting) runs with no display, no GTK, no GSettings
database and no subprocess.
"""

import builtins
import sys
import tempfile
import unittest
from pathlib import Path
from shlex import quote as shell_quote

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]


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
        # Pointers that do not exist, so a source is only resolvable when a
        # test explicitly places a config inside one of them.
        self.flatpak_dir = Path("/nonexistent/jolven-flatpak")
        self.config_dir = Path("/nonexistent/jolven-config")
        self.host_config_dir = Path("/nonexistent/jolven-host-config")
        self.host_data_dir = Path("/nonexistent/jolven-host-data")


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

_STUBBED_MODULES = (
    "cartridges.shared",
    "cartridges.game",
    "cartridges.importer.location",
    "cartridges.importer.source",
)
_originals = {name: sys.modules.pop(name, None) for name in _STUBBED_MODULES}

sys.modules["cartridges.shared"] = _STUB_SHARED
sys.modules["cartridges.game"] = _STUB_GAME_MODULE
cartridges.shared = _STUB_SHARED
cartridges.game = _STUB_GAME_MODULE

from cartridges.importer import cemu_source  # noqa: E402
from cartridges.importer.cemu_source import (  # noqa: E402
    CemuSource,
    CemuSourceIterable,
)

for _name, _module in _originals.items():
    if _module is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _module
if _originals["cartridges.shared"] is not None:
    cartridges.shared = _originals["cartridges.shared"]
if _originals["cartridges.game"] is not None:
    cartridges.game = _originals["cartridges.game"]

# The stub instances are still referenced by the imported modules, so the
# tests can retarget the candidate roots.
_shared_stub = cemu_source.shared

TITLE_ID = "000500001017D800"


def _write_title_list_cache(path: Path, entries: list[tuple[str, str, str]]) -> Path:
    """Write a Cemu title list cache with the given titles."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<title_list>"]
    for title_id, name, game_path in entries:
        lines.append(f'\t<title titleId="{title_id}" version="0">')
        lines.append(f"\t\t<name>{name}</name>")
        lines.append("\t\t<format>0</format>")
        lines.append(f"\t\t<path>{game_path}</path>")
        lines.append("\t</title>")
    lines.append("</title_list>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class CemuSourceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self._old_shared = (
            _shared_stub.flatpak_dir,
            _shared_stub.config_dir,
            _shared_stub.host_config_dir,
            _shared_stub.host_data_dir,
        )
        self.addCleanup(self._restore_shared)
        _shared_stub.flatpak_dir = self.tmp / "flatpak"
        _shared_stub.config_dir = self.tmp / "config"
        _shared_stub.host_config_dir = self.tmp / "host-config"
        _shared_stub.host_data_dir = self.tmp / "host-data"

        self._old_location = _shared_stub.schema.strings.get("cemu-location")
        self.addCleanup(self._restore_location)

        # The ROMs of the user.
        self.roms = self.tmp / "roms"
        self.roms.mkdir()
        # The configuration of Cemu, with an empty legacy cache.
        self.config_root = self.tmp / "config" / "Cemu"
        self.config_root.mkdir(parents=True)
        self.write_settings()

    def _restore_shared(self):
        (
            _shared_stub.flatpak_dir,
            _shared_stub.config_dir,
            _shared_stub.host_config_dir,
            _shared_stub.host_data_dir,
        ) = self._old_shared

    def _restore_location(self):
        if self._old_location is None:
            _shared_stub.schema.strings.pop("cemu-location", None)
        else:
            _shared_stub.schema.set_string("cemu-location", self._old_location)

    def write_settings(
        self, cache_entries: list[tuple[str, str, str, str]] | None = None
    ) -> Path:
        """Write the settings.xml of Cemu."""
        lines = ["<content>", "\t<GamePaths>", f"\t\t<Entry>{self.roms}</Entry>"]
        lines.append("\t</GamePaths>")
        lines.append("\t<GameCache>")
        for title_id, name, custom_name, path in cache_entries or []:
            lines.append("\t\t<Entry>")
            lines.append(f"\t\t\t<title_id>{title_id}</title_id>")
            lines.append(f"\t\t\t<name>{name}</name>")
            lines.append(f"\t\t\t<custom_name>{custom_name}</custom_name>")
            lines.append(f"\t\t\t<path>{path}</path>")
            lines.append("\t\t</Entry>")
        lines.append("\t</GameCache>")
        lines.append("</content>")
        settings = self.config_root / "settings.xml"
        settings.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return settings

    def make_game_folder(self, name: str, title_id: str = TITLE_ID) -> Path:
        """Create a folder that looks like an extracted game."""
        folder = self.roms / name
        for part in ("content", "code", "meta"):
            (folder / part).mkdir(parents=True, exist_ok=True)
        (folder / "meta" / "meta.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<u8>\n"
            f"\t<title_id>{title_id}</title_id>\n"
            "</u8>\n",
            encoding="utf-8",
        )
        return folder

    def write_flatpak_title_list_cache(self, entries) -> Path:
        """Write the title list cache of a Flatpak installation."""
        return _write_title_list_cache(
            self.tmp / "data" / "Cemu" / "title_list_cache.xml", entries
        )

    def write_host_title_list_cache(self, entries) -> Path:
        """Write the title list cache of a native installation."""
        return _write_title_list_cache(
            self.tmp / "host-data" / "Cemu" / "title_list_cache.xml", entries
        )


class SourceMetadataTests(CemuSourceTestCase):
    def test_source_metadata(self):
        self.assertEqual(CemuSource.source_id, "cemu")
        self.assertEqual(CemuSource.name, "Cemu")
        self.assertEqual(CemuSource.available_on, {"linux"})
        self.assertIs(CemuSource.iterable_class, CemuSourceIterable)

    def test_game_id_format_is_stable(self):
        source = CemuSource()
        self.assertEqual(source.game_id_format, "cemu_{game_id}")

    def test_the_source_has_a_single_location(self):
        source = CemuSource()
        self.assertEqual(list(source.locations._asdict()), ["config"])


class IterationTests(CemuSourceTestCase):
    def test_the_game_of_the_title_list_cache_is_imported(self):
        folder = self.make_game_folder("Hyrule Warriors [Game] [000500001017d800]")
        self.write_flatpak_title_list_cache(
            [("000500001017d800", "Hyrule Warriors", str(folder))]
        )

        results = list(CemuSourceIterable(CemuSource()))

        self.assertEqual(len(results), 1)
        game, additional = results[0]
        self.assertEqual(game.values["game_id"], f"cemu_{TITLE_ID}")
        self.assertEqual(game.values["source"], "cemu")
        self.assertEqual(game.values["name"], "Hyrule Warriors")
        self.assertEqual(
            game.values["executable"], f"Cemu -f -g {shell_quote(str(folder))}"
        )
        self.assertEqual(additional, {})

    def test_a_title_of_the_cache_and_of_the_scan_is_imported_once(self):
        folder = self.make_game_folder("Hyrule Warriors [Game] [000500001017d800]")
        self.write_flatpak_title_list_cache(
            [("000500001017d800", "Hyrule Warriors", str(folder))]
        )

        results = list(CemuSourceIterable(CemuSource()))

        self.assertEqual(len(results), 1)
        game, _additional = results[0]
        self.assertEqual(game.values["name"], "Hyrule Warriors")

    def test_the_game_of_the_scan_is_imported_without_the_cache(self):
        # The bug of issue #59: Cemu never wrote its own cache.
        folder = self.make_game_folder("Hyrule Warriors [Game] [000500001017d800]")

        results = list(CemuSourceIterable(CemuSource()))

        self.assertEqual(len(results), 1)
        game, _additional = results[0]
        self.assertEqual(game.values["game_id"], f"cemu_{TITLE_ID}")
        self.assertEqual(game.values["name"], "Hyrule Warriors")
        self.assertEqual(
            game.values["executable"], f"Cemu -f -g {shell_quote(str(folder))}"
        )

    def test_the_cache_of_the_host_data_dir_is_used(self):
        folder = self.make_game_folder("Hyrule Warriors [Game] [000500001017d800]")
        self.write_host_title_list_cache(
            [("000500001017d800", "Hyrule Warriors", str(folder))]
        )

        results = list(CemuSourceIterable(CemuSource()))

        self.assertEqual(len(results), 1)
        game, _additional = results[0]
        self.assertEqual(game.values["name"], "Hyrule Warriors")

    def test_a_dlc_title_is_not_imported(self):
        self.make_game_folder("DLC Pack [0005000c101c3b00]", "0005000c101c3b00")
        self.write_flatpak_title_list_cache(
            [("0005000c101c3b00", "DLC Pack", str(self.roms / "DLC Pack"))]
        )

        self.assertEqual(list(CemuSourceIterable(CemuSource())), [])

    def test_the_custom_name_of_the_legacy_cache_wins(self):
        folder = self.make_game_folder("Hyrule Warriors [Game] [000500001017d800]")
        self.write_flatpak_title_list_cache(
            [("000500001017d800", "Hyrule Warriors", str(folder))]
        )
        self.write_settings(
            [
                (
                    "000500001017D800",
                    "Hyrule Warriors",
                    "My Renamed Game",
                    str(folder),
                )
            ]
        )

        results = list(CemuSourceIterable(CemuSource()))

        self.assertEqual(len(results), 1)
        game, _additional = results[0]
        self.assertEqual(game.values["name"], "My Renamed Game")
        self.assertEqual(game.values["game_id"], f"cemu_{TITLE_ID}")

    def test_the_game_of_the_legacy_cache_is_imported(self):
        rpx = self.roms / "nsmbu" / "code" / "content.rpx"
        rpx.parent.mkdir(parents=True)
        rpx.write_bytes(b"rpx")
        self.write_settings(
            [("000500001010EC00", "New Super Mario Bros. U", "", str(rpx))]
        )

        results = list(CemuSourceIterable(CemuSource()))

        self.assertEqual(len(results), 1)
        game, _additional = results[0]
        self.assertEqual(game.values["game_id"], "cemu_000500001010EC00")
        self.assertEqual(game.values["name"], "New Super Mario Bros. U")
        self.assertEqual(
            game.values["executable"], f"Cemu -f -g {shell_quote(str(rpx))}"
        )

    def test_a_game_whose_path_is_gone_is_not_imported(self):
        self.write_settings(
            [
                (
                    "000500001010EC00",
                    "New Super Mario Bros. U",
                    "",
                    str(self.roms / "gone.rpx"),
                )
            ]
        )

        self.assertEqual(list(CemuSourceIterable(CemuSource())), [])

    def test_the_added_time_comes_from_the_shared_module(self):
        self.make_game_folder("Hyrule Warriors [Game] [000500001017d800]")

        results = list(CemuSourceIterable(CemuSource()))

        self.assertEqual(len(results), 1)
        game, _additional = results[0]
        self.assertEqual(game.values["added"], _shared_stub.import_time)


class ExecutableTests(CemuSourceTestCase):
    def test_the_native_command_is_used_outside_flatpak(self):
        source = CemuSource()
        self.assertEqual(source.executable_format, "Cemu -f -g {rom_path}")

    def test_the_flatpak_command_is_used_inside_flatpak(self):
        root = self.tmp / "flatpak" / "info.cemu.Cemu" / "config" / "Cemu"
        root.mkdir(parents=True)
        (root / "settings.xml").write_text("<content/>", encoding="utf-8")

        source = CemuSource()

        self.assertEqual(
            source.executable_format, "flatpak run info.cemu.Cemu -f -g {rom_path}"
        )

    def test_the_path_with_spaces_is_shell_quoted(self):
        source = CemuSource()
        rom_path = Path("/roms/wiiu/My Game")
        self.assertEqual(
            source.make_executable(rom_path=rom_path),
            f"Cemu -f -g {shell_quote(str(rom_path))}",
        )


if __name__ == "__main__":
    unittest.main()
