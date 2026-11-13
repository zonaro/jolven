# test_linux_desktop_contract.py
#
# Copyright 2026 Jolven contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression guards for the Linux desktop scope.

These tests intentionally use only the Python standard library, so that the
core CI job can detect accidental Win32 dependency reintroductions without
a graphical environment or PyGObject installed.
"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class LinuxDesktopContractTests(unittest.TestCase):
    def test_no_windows_importer_or_mutex_module(self) -> None:
        self.assertFalse((ROOT / "cartridges/importer/shortcuts_source.py").exists())
        self.assertFalse((ROOT / "cartridges/utils/single_instance.py").exists())
        self.assertFalse((ROOT / "tests/test_shortcuts_source.py").exists())

        self.assertNotIn("ShortcutsSource", source("cartridges/importer/registry.py"))
        self.assertNotIn(
            "shortcuts_source.py", source("po/POTFILES")
        )

    def test_gsettings_retained_and_windows_schema_keys_removed(self) -> None:
        shared = source("cartridges/shared.py.in")
        schema = source("data/io.github.zonaro.Jolven.gschema.xml.in")
        self.assertIn("Gio.Settings.new(APP_ID)", shared)
        self.assertIn("Gio.Settings.new(APP_ID + \".State\")", shared)
        for setting in ("shortcuts", "shortcuts-location", "shortcuts-recursive"):
            self.assertNotIn(f'<key name="{setting}"', schema)

    def test_runtime_uses_no_win32_services(self) -> None:
        forbidden = (
            "IS_WINDOWS",
            "CreateMutexW",
            "Windows Hello",
            "winreg",
            "ctypes.WinDLL",
            "RegNotifyChangeKeyValue",
            "winrt.windows",
        )
        for path in (
            "cartridges/main.py",
            "cartridges/platform/__init__.py",
            "cartridges/platform/paths.py",
            "cartridges/platform/authentication.py",
            "cartridges/shared.py.in",
        ):
            content = source(path)
            with self.subTest(path=path):
                for identifier in forbidden:
                    self.assertNotIn(identifier, content)

    def test_single_instance_uses_linux_gapplication(self) -> None:
        main = source("cartridges/main.py")
        self.assertIn("Adw.Application", main)
        self.assertIn("if shared.win is not None:", main)
        self.assertIn("shared.win.present()", main)

    def test_ci_no_windows_build(self) -> None:
        workflow = source(".github/workflows/ci.yml")
        self.assertIn("runs-on: ubuntu-latest", workflow)
        self.assertIn("Flatpak Builder", workflow)
        self.assertNotIn("windows-latest", workflow)
        self.assertNotIn("msys2/setup-msys2", workflow)

    def test_wine_games_still_supported(self) -> None:
        monitor = source("cartridges/utils/process_monitor.py")
        self.assertIn('".exe"', monitor)
        importer = source("cartridges/importer/importer.py")
        self.assertIn("if game.base_source not in scanned:", importer)


if __name__ == "__main__":
    unittest.main()
