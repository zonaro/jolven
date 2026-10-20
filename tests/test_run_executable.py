"""Pure-python tests for the launch path of the Jolven.

The module under test imports ``cartridges.shared`` (the GSettings schema
and the GTK window live there), which does not exist in a bare source tree,
so it is stubbed in ``sys.modules`` before the import — the same trick
``tests/test_eden_source.py`` uses. Everything asserted here runs with no
display, no GTK and no GSettings database: the spawn itself is mocked, so
no game is ever started.
"""

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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


class _StubRuntime:
    is_game_mode = False
    is_session = False
    is_nested = False


class _StubShared:
    APP_ID = "io.github.zonaro.Jolven"

    def __init__(self):
        self.schema = _StubSchema()
        self.runtime = _StubRuntime()
        self.home = Path("/tmp")


# The stub must win over the real module even when another test module
# already imported it: `from cartridges import shared` resolves the
# attribute of the package first, and the module under test binds
# `shared` at import time. So the stubs are installed, the module that
# binds them is re-imported, and the environment is restored afterwards.
import cartridges  # noqa: E402

_STUBBED_MODULES = ("cartridges.shared", "cartridges.utils.run_executable")
_originals = {name: sys.modules.pop(name, None) for name in _STUBBED_MODULES}

_STUB_SHARED = _StubShared()
sys.modules["cartridges.shared"] = _STUB_SHARED
setattr(cartridges, "shared", _STUB_SHARED)

from cartridges.utils import run_executable as run_executable_module  # noqa: E402
from cartridges.utils.run_executable import (  # noqa: E402
    ensure_executable,
    local_executable,
)

# `shared` goes back to where it was. The module under test keeps the
# stub: it is the object these tests exercise, and no other test launches
# a game.
if _originals["cartridges.shared"] is not None:
    sys.modules["cartridges.shared"] = _originals["cartridges.shared"]
    setattr(cartridges, "shared", _originals["cartridges.shared"])
else:
    sys.modules.pop("cartridges.shared", None)
    if hasattr(cartridges, "shared"):
        delattr(cartridges, "shared")
if _originals["cartridges.utils.run_executable"] is not None:
    sys.modules["cartridges.utils.run_executable"] = _originals[
        "cartridges.utils.run_executable"
    ]


class EnsureExecutableTests(unittest.TestCase):
    """The owner bit is added, and nothing else is touched."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def _make_file(self, name="game.x86_64", mode=0o644):
        path = self.tmp / name
        path.write_bytes(b"\x7fELF")
        path.chmod(mode)
        return path

    def test_owner_bit_is_added(self):
        path = self._make_file()
        ensure_executable(path)
        mode = path.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR)

    def test_only_the_owner_bit_changes(self):
        path = self._make_file(mode=0o644)
        ensure_executable(path)
        mode = stat.S_IMODE(path.stat().st_mode)
        self.assertEqual(mode, 0o744)

    def test_group_and_other_are_untouched(self):
        path = self._make_file(mode=0o604)
        ensure_executable(path)
        mode = stat.S_IMODE(path.stat().st_mode)
        self.assertEqual(mode & 0o070, 0o000)
        self.assertEqual(mode & 0o007, 0o004)

    def test_file_with_the_bit_is_untouched(self):
        path = self._make_file(mode=0o755)
        before = path.stat().st_mode
        ensure_executable(path)
        self.assertEqual(path.stat().st_mode, before)

    def test_directory_is_skipped(self):
        folder = self.tmp / "folder"
        folder.mkdir()
        folder.chmod(0o755)
        before = folder.stat().st_mode
        ensure_executable(folder)
        self.assertEqual(folder.stat().st_mode, before)

    def test_missing_file_is_skipped(self):
        ensure_executable(self.tmp / "gone")

    def test_failure_is_not_fatal(self):
        path = self._make_file()
        with patch.object(run_executable_module.os, "chmod", side_effect=OSError):
            ensure_executable(path)
        self.assertFalse(path.stat().st_mode & stat.S_IXUSR)


class LocalExecutableTests(unittest.TestCase):
    """Only the program a command runs is a target."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def _make_file(self, name="game.x86_64"):
        path = self.tmp / name
        path.write_bytes(b"\x7fELF")
        path.chmod(0o755)
        return path

    def test_plain_path_is_the_target(self):
        path = self._make_file()
        self.assertEqual(local_executable(str(path)), path)

    def test_quoted_path_with_spaces_is_the_target(self):
        path = self.tmp / "My Game.x86_64"
        path.write_bytes(b"\x7fELF")
        path.chmod(0o755)
        self.assertEqual(local_executable(f"'{path}'"), path)

    def test_environment_wrapper_is_skipped(self):
        path = self._make_file()
        self.assertEqual(local_executable(f"env FOO=bar '{path}'"), path)

    def test_assignment_before_the_program_is_skipped(self):
        path = self._make_file()
        self.assertEqual(local_executable(f"MANGOHUD=1 '{path}'"), path)

    def test_arguments_are_not_targets(self):
        rom = self._make_file("game.nsp")
        self.assertIsNone(local_executable(f"eden -f '{rom}'"))

    def test_launcher_uri_is_not_a_target(self):
        self.assertIsNone(local_executable("xdg-open steam://rungameid/620"))

    def test_flatpak_app_is_not_a_target(self):
        self.assertIsNone(local_executable("flatpak run com.example.Game"))

    def test_store_client_is_not_a_target(self):
        self.assertIsNone(local_executable("legendary launch My Game"))

    def test_empty_command_is_not_a_target(self):
        self.assertIsNone(local_executable(""))

    def test_missing_file_is_not_a_target(self):
        self.assertIsNone(local_executable(str(self.tmp / "gone")))

    def test_relative_program_needs_the_working_directory(self):
        path = self._make_file()
        self.assertIsNone(local_executable("./game.x86_64"))
        self.assertEqual(
            local_executable("./game.x86_64", self.tmp),
            path,
        )


class RunExecutableTests(unittest.TestCase):
    """The bit is given before the spawn, and the spawn still happens."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self._old_home = run_executable_module.shared.home
        run_executable_module.shared.home = self.tmp
        self.addCleanup(self._restore_home)

    def _restore_home(self):
        run_executable_module.shared.home = self._old_home

    def _make_file(self, name="game.x86_64", mode=0o644):
        path = self.tmp / name
        path.write_bytes(b"\x7fELF")
        path.chmod(mode)
        return path

    def _launch(self, command, path):
        """Run a launch with the spawn mocked; returns the mode at spawn."""
        modes = []

        def fake_popen(*_args, **_kwargs):
            modes.append(stat.S_IMODE(path.stat().st_mode))
            return object()

        with patch.dict(os.environ, {"FLATPAK_ID": ""}), patch.object(
            run_executable_module.subprocess, "Popen", side_effect=fake_popen
        ):
            run_executable_module.run_executable(
                command, use_gamemode=False, use_mangohud=False
            )
        return modes

    def test_the_bit_is_set_before_the_spawn(self):
        path = self._make_file()
        modes = self._launch(str(path), path)
        self.assertEqual(modes, [0o744])

    def test_a_quoted_path_is_set_before_the_spawn(self):
        path = self._make_file("My Game.x86_64")
        modes = self._launch(f"'{path}'", path)
        self.assertEqual(modes, [0o744])

    def test_a_program_that_is_already_runnable_is_untouched(self):
        path = self._make_file(mode=0o755)
        modes = self._launch(str(path), path)
        self.assertEqual(modes, [0o755])

    def test_the_spawn_still_happens(self):
        path = self._make_file()
        with patch.dict(os.environ, {"FLATPAK_ID": ""}), patch.object(
            run_executable_module.subprocess, "Popen"
        ) as popen:
            run_executable_module.run_executable(
                str(path), use_gamemode=False, use_mangohud=False
            )
        popen.assert_called_once()

    def test_a_launcher_uri_is_left_alone(self):
        with patch.dict(os.environ, {"FLATPAK_ID": ""}), patch.object(
            run_executable_module.subprocess, "Popen"
        ) as popen:
            run_executable_module.run_executable(
                "xdg-open steam://rungameid/620",
                use_gamemode=False,
                use_mangohud=False,
            )
        popen.assert_called_once()

    def test_a_failing_chmod_does_not_stop_the_launch(self):
        path = self._make_file()
        with patch.dict(os.environ, {"FLATPAK_ID": ""}), patch.object(
            run_executable_module.os, "chmod", side_effect=OSError
        ), patch.object(run_executable_module.subprocess, "Popen") as popen:
            run_executable_module.run_executable(
                str(path), use_gamemode=False, use_mangohud=False
            )
        popen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
