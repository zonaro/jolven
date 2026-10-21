"""Pure-python tests for the Eden emulator source.

The module under test lives behind Gtk/GSettings imports (`cartridges.game`,
`cartridges.shared`) that do not exist in a bare source tree, so those two
dependencies are stubbed in `sys.modules` before import — exactly the parts
the exercised code only touches through `Game(values)` and
`shared.import_time`/`shared.schema`/`shared.flatpak_dir`. Everything asserted
here (config parsing, game id stability, command quoting, rom filtering) runs
with no display, no GTK and no GSettings database.
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
setattr(cartridges, "shared", _STUB_SHARED)
setattr(cartridges, "game", _STUB_GAME_MODULE)

from cartridges.importer import eden_source  # noqa: E402
from cartridges.importer.eden_source import (  # noqa: E402
    EdenSource,
    EdenSourceIterable,
)
from cartridges.importer.location import UnresolvableLocationError  # noqa: E402

for _name, _module in _originals.items():
    if _module is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _module
if _originals["cartridges.shared"] is not None:
    setattr(cartridges, "shared", _originals["cartridges.shared"])
if _originals["cartridges.game"] is not None:
    setattr(cartridges, "game", _originals["cartridges.game"])

# The stub instances are still referenced by the imported modules, so the
# tests can retarget the candidate roots.
_shared_stub = eden_source.shared


def _write_config(config_dir: Path, dirs: list[tuple[bool, str]]) -> Path:
    """Write a yuzu/eden-like qt-config.ini and return its directory."""
    config_dir.mkdir(parents=True, exist_ok=True)
    lines = ["[UI]", rf"Paths\gamedirs\size={len(dirs)}"]
    for index, (deep, path) in enumerate(dirs, start=1):
        lines.append(rf"Paths\gamedirs\{index}\deep_scan={str(deep).lower()}")
        lines.append(rf"Paths\gamedirs\{index}\path={path}")
    (config_dir / "qt-config.ini").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return config_dir


class EdenSourceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self._old_shared = (
            _shared_stub.flatpak_dir,
            _shared_stub.config_dir,
            _shared_stub.host_config_dir,
        )
        self.addCleanup(self._restore_shared)
        _shared_stub.flatpak_dir = self.tmp / "flatpak"
        _shared_stub.config_dir = self.tmp / "config"
        _shared_stub.host_config_dir = self.tmp / "host-config"

    def _restore_shared(self):
        (
            _shared_stub.flatpak_dir,
            _shared_stub.config_dir,
            _shared_stub.host_config_dir,
        ) = self._old_shared

    def _make_source(self, dirs: list[tuple[bool, str]], flatpak: bool = False):
        """Create a source whose qt-config.ini lives in a temp root."""
        if flatpak:
            root = _shared_stub.flatpak_dir / "dev.eden_emu.eden" / "config" / "eden"
        else:
            root = _shared_stub.config_dir / "eden"
        _write_config(root, dirs)
        source = EdenSource()
        return source


class SourceMetadataTests(EdenSourceTestCase):
    def test_source_metadata(self):
        self.assertEqual(EdenSource.source_id, "eden")
        self.assertEqual(EdenSource.name, "Eden")
        self.assertEqual(EdenSource.available_on, {"linux"})
        self.assertIs(EdenSource.iterable_class, EdenSourceIterable)
        self.assertEqual(
            EdenSourceIterable.extensions, (".xci", ".nsp", ".nso", ".nro")
        )


class IterGameDirsTests(EdenSourceTestCase):
    def test_parses_dirs_and_skips_empty_paths(self):
        roms = self.tmp / "roms"
        roms.mkdir()
        source = self._make_source(
            [(True, str(roms)), (False, "")],
        )
        dirs = list(EdenSourceIterable(source).iter_game_dirs())
        self.assertEqual(dirs, [(True, roms)])

    def test_missing_config_yields_nothing(self):
        source = EdenSource()
        # No qt-config.ini anywhere in the candidate roots.
        with self.assertRaises(UnresolvableLocationError):
            list(EdenSourceIterable(source).iter_game_dirs())


class ExecutableFormatTests(EdenSourceTestCase):
    def test_native_binary_is_used_outside_flatpak(self):
        roms = self.tmp / "roms"
        roms.mkdir()
        source = self._make_source([(False, str(roms))])
        self.assertEqual(source.executable_format, "eden -f {rom_path}")

    def test_flatpak_command_is_used_inside_flatpak(self):
        roms = self.tmp / "roms"
        roms.mkdir()
        source = self._make_source([(False, str(roms))], flatpak=True)
        self.assertEqual(
            source.executable_format, "flatpak run dev.eden_emu.eden -f {rom_path}"
        )

    def test_rom_path_is_shell_quoted(self):
        roms = self.tmp / "roms"
        roms.mkdir()
        source = self._make_source([(False, str(roms))])
        rom_path = roms / "My Game.nsp"
        self.assertEqual(
            source.make_executable(rom_path=rom_path),
            f"eden -f {shell_quote(str(rom_path))}",
        )


class IterationTests(EdenSourceTestCase):
    def test_yields_game_with_stable_id_and_command(self):
        roms = self.tmp / "roms"
        roms.mkdir()
        source = self._make_source([(False, str(roms))])
        rom_path = roms / "My Game.nsp"
        rom_path.write_bytes(b"x")

        results = list(EdenSourceIterable(source))
        self.assertEqual(len(results), 1)
        game, additional = results[0]
        self.assertEqual(game.values["game_id"], "eden_My Game")
        self.assertEqual(game.values["source"], "eden")
        self.assertEqual(game.values["name"], "My Game")
        self.assertEqual(
            game.values["executable"],
            f"eden -f {shell_quote(str(rom_path))}",
        )
        self.assertIn(" -f ", game.values["executable"])
        self.assertEqual(additional, {})

    def test_only_known_extensions_are_collected(self):
        roms = self.tmp / "roms"
        roms.mkdir()
        for name in ("a.xci", "b.nsp", "c.nso", "d.nro"):
            (roms / name).write_bytes(b"x")
        for name in ("readme.txt", "save.nsp2", "game.rom"):
            (roms / name).write_bytes(b"x")
        (roms / "subdir.nsp").mkdir()

        source = self._make_source([(False, str(roms))])
        found = sorted(path.name for path in EdenSourceIterable(source).iter_rom_files(roms))
        self.assertEqual(found, ["a.xci", "b.nsp", "c.nso", "d.nro"])

    def test_deep_scan_walks_subdirectories(self):
        roms = self.tmp / "roms"
        (roms / "sub").mkdir(parents=True)
        (roms / "top.nsp").write_bytes(b"x")
        (roms / "sub" / "deep.nsp").write_bytes(b"x")

        source = self._make_source([(True, str(roms))])
        found = sorted(path.name for path in EdenSourceIterable(source).iter_rom_files(roms, True))
        self.assertEqual(found, ["deep.nsp", "top.nsp"])


if __name__ == "__main__":
    unittest.main()
