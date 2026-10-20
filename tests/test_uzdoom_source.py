"""Pure-python tests for the UZDoom source.

The module under test lives behind Gtk/GSettings imports (`cartridges.game`,
`cartridges.shared`) that do not exist in a bare source tree, so those two
dependencies are stubbed in `sys.modules` before import — exactly the parts
the exercised code only touches through `Game(values)` and
`shared.import_time`/`shared.schema`. Everything asserted here (IWAD/PWAD
filtering, game id stability, command quoting, launcher detection) runs with
no display, no GTK, no GSettings database and no subprocess.
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

from cartridges.importer import uzdoom_source  # noqa: E402
from cartridges.importer.location import UnresolvableLocationError  # noqa: E402
from cartridges.importer.uzdoom_source import (  # noqa: E402
    UzdoomSource,
    UzdoomSourceIterable,
    resolve_uzdoom_base,
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
# tests can retarget the schema.
_shared_stub = uzdoom_source.shared

IWAD = b"IWAD"
PWAD = b"PWAD"


def _make_wad(path: Path, magic: bytes = IWAD) -> Path:
    """Write a WAD-like file with the given magic header."""
    path.write_bytes(magic + b"\x00" * 8)
    return path


class UzdoomSourceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.wads = self.tmp / "wads"
        self.wads.mkdir()
        self._old_location = _shared_stub.schema.strings.get("uzdoom-location")
        self.addCleanup(self._restore_location)
        _shared_stub.schema.set_string("uzdoom-location", str(self.wads))

    def _restore_location(self):
        if self._old_location is None:
            _shared_stub.schema.strings.pop("uzdoom-location", None)
        else:
            _shared_stub.schema.set_string("uzdoom-location", self._old_location)

    def _make_source(self, **kwargs) -> UzdoomSource:
        """Create a source pointing at the temporary WADs folder.

        The launcher detection is always injected, so the tests never spawn
        a subprocess and never depend on what is installed on the host.
        """
        kwargs.setdefault("find_program", self._no_program)
        kwargs.setdefault("has_flatpak", self._no_flatpak)
        return UzdoomSource(**kwargs)

    @staticmethod
    def _no_program(_name: str):
        return None

    @staticmethod
    def _no_flatpak(_app_id: str) -> bool:
        return False


class SourceMetadataTests(UzdoomSourceTestCase):
    def test_source_metadata(self):
        self.assertEqual(UzdoomSource.source_id, "uzdoom")
        self.assertEqual(UzdoomSource.name, "UZDoom")
        self.assertEqual(UzdoomSource.available_on, {"linux"})
        self.assertIs(UzdoomSource.iterable_class, UzdoomSourceIterable)
        self.assertEqual(UzdoomSourceIterable.extensions, (".wad",))

    def test_game_id_format_is_stable(self):
        source = self._make_source()
        self.assertEqual(source.game_id_format, "uzdoom_{game_id}")


class IterationTests(UzdoomSourceTestCase):
    def test_iwad_yields_a_game_with_a_stable_id(self):
        wad = _make_wad(self.wads / "doom2.wad")
        source = self._make_source()

        results = list(UzdoomSourceIterable(source))
        self.assertEqual(len(results), 1)
        game, additional = results[0]
        self.assertEqual(game.values["game_id"], "uzdoom_doom2")
        self.assertEqual(game.values["source"], "uzdoom")
        self.assertEqual(game.values["name"], "doom2")
        self.assertEqual(
            game.values["executable"],
            f"uzdoom -iwad {shell_quote(str(wad))}",
        )
        self.assertEqual(additional, {})

    def test_pwad_is_not_listed(self):
        _make_wad(self.wads / "mod.wad", PWAD)
        source = self._make_source()
        self.assertEqual(list(UzdoomSourceIterable(source)), [])

    def test_other_extensions_are_ignored(self):
        _make_wad(self.wads / "doom2.zip")
        _make_wad(self.wads / "doom2.txt")
        _make_wad(self.wads / "doom2")
        source = self._make_source()
        self.assertEqual(list(UzdoomSourceIterable(source)), [])

    def test_uppercase_extension_is_matched(self):
        wad = _make_wad(self.wads / "DOOM2.WAD")
        source = self._make_source()
        results = list(UzdoomSourceIterable(source))
        self.assertEqual(len(results), 1)
        game, _additional = results[0]
        self.assertEqual(game.values["game_id"], "uzdoom_DOOM2")
        self.assertEqual(
            game.values["executable"],
            f"uzdoom -iwad {shell_quote(str(wad))}",
        )

    def test_truncated_and_garbage_files_are_skipped(self):
        (self.wads / "short.wad").write_bytes(b"IW")
        (self.wads / "empty.wad").write_bytes(b"")
        (self.wads / "garbage.wad").write_bytes(b"XXXX1234")
        source = self._make_source()
        self.assertEqual(list(UzdoomSourceIterable(source)), [])

    def test_subdirectories_are_not_scanned(self):
        (self.wads / "sub").mkdir()
        _make_wad(self.wads / "sub" / "doom.wad")
        source = self._make_source()
        self.assertEqual(list(UzdoomSourceIterable(source)), [])


class ExecutableTests(UzdoomSourceTestCase):
    def test_path_with_spaces_is_shell_quoted(self):
        wads = self.tmp / "my wads"
        wads.mkdir()
        wad = _make_wad(wads / "doom ii.wad")
        _shared_stub.schema.set_string("uzdoom-location", str(wads))
        source = self._make_source()

        executable = source.make_executable(iwad_path=wad)
        self.assertEqual(executable, f"uzdoom -iwad {shell_quote(str(wad))}")
        self.assertTrue(executable.endswith(f"'{wad}'"))

    def test_native_binary_is_preferred(self):
        source = self._make_source(
            find_program=lambda name: "/usr/bin/uzdoom" if name == "uzdoom" else None,
            has_flatpak=self._no_flatpak,
        )
        self.assertEqual(source.executable_base, "uzdoom")
        self.assertEqual(source.executable_format, "uzdoom -iwad {iwad_path}")

    def test_flatpak_is_used_when_the_binary_is_missing(self):
        source = self._make_source(
            find_program=self._no_program,
            has_flatpak=lambda app_id: app_id == "org.zdoom.UZDoom",
        )
        self.assertEqual(source.executable_base, "flatpak run org.zdoom.UZDoom")
        self.assertEqual(
            source.executable_format,
            "flatpak run org.zdoom.UZDoom -iwad {iwad_path}",
        )

    def test_native_binary_is_the_fallback(self):
        source = self._make_source(
            find_program=self._no_program,
            has_flatpak=self._no_flatpak,
        )
        self.assertEqual(source.executable_base, "uzdoom")

    def test_base_is_resolved_only_once(self):
        calls = []

        def counting_which(name):
            calls.append(name)
            return "/usr/bin/uzdoom"

        source = self._make_source(
            find_program=counting_which,
            has_flatpak=self._no_flatpak,
        )
        source.make_executable(iwad_path=self.wads / "doom2.wad")
        source.make_executable(iwad_path=self.wads / "heretic.wad")
        self.assertEqual(calls, ["uzdoom"])

    def test_resolve_uzdoom_base_helper(self):
        self.assertEqual(
            resolve_uzdoom_base(
                find_program=lambda name: "/usr/bin/uzdoom",
                has_flatpak=self._no_flatpak,
            ),
            "uzdoom",
        )
        self.assertEqual(
            resolve_uzdoom_base(
                find_program=self._no_program,
                has_flatpak=lambda app_id: app_id == "org.zdoom.UZDoom",
            ),
            "flatpak run org.zdoom.UZDoom",
        )
        self.assertEqual(
            resolve_uzdoom_base(
                find_program=self._no_program,
                has_flatpak=self._no_flatpak,
            ),
            "uzdoom",
        )


class LocationTests(UzdoomSourceTestCase):
    def test_blank_location_is_unresolvable(self):
        _shared_stub.schema.set_string("uzdoom-location", "")
        source = self._make_source()
        with self.assertRaises(UnresolvableLocationError):
            list(iter(source))

    def test_deleted_folder_is_unresolvable(self):
        missing = self.tmp / "gone"
        _shared_stub.schema.set_string("uzdoom-location", str(missing))
        source = self._make_source()
        with self.assertRaises(UnresolvableLocationError):
            list(iter(source))


if __name__ == "__main__":
    unittest.main()
