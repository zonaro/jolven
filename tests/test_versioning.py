"""Pure-stdlib contract tests for frozen UTC build/release versions."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BUILD_AUX = ROOT / "build-aux"
sys.path.insert(0, str(BUILD_AUX))
import versioning  # noqa: E402


class JolvenVersionTests(unittest.TestCase):
    def test_valid_ordinal_days_and_24_hour_clock(self) -> None:
        for candidate in ("26.001.0000", "26.365.2359", "24.366.2359", "00.001.0012"):
            with self.subTest(candidate=candidate):
                self.assertEqual(versioning.validate_version(candidate), candidate)

    def test_invalid_day_hour_minute_and_format(self) -> None:
        for candidate in ("26.000.1200", "26.366.1200", "24.367.0000", "26.010.2400",
                          "26.010.0060", "26.10.1234", "2026.001.1200", "26.001.9", ""):
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    versioning.validate_version(candidate)

    def test_frozen_version_overrides_system_time(self) -> None:
        with patch.dict(os.environ, {"JOLVEN_VERSION": "24.366.2359"}):
            self.assertEqual(versioning.build_version(), "24.366.2359")

    def test_current_utc_version_is_legal(self) -> None:
        with patch.dict(os.environ, {"JOLVEN_VERSION": "", "CARTRIDGES_VERSION": ""}):
            self.assertEqual(versioning.validate_version(versioning.build_version()),
                             versioning.build_version())

    def test_get_and_write_use_same_version(self) -> None:
        env = {**os.environ, "JOLVEN_VERSION": "26.317.0132"}
        value = subprocess.check_output(
            [sys.executable, str(BUILD_AUX / "get-version.py")],
            env=env, text=True,
        ).strip()
        self.assertEqual(value, "26.317.0132")
        with tempfile.TemporaryDirectory() as folder:
            template = Path(folder) / "version.in"
            output = Path(folder) / "version.py"
            template.write_text('BUILD_VERSION = "@VCS_TAG@"\n', encoding="utf-8")
            subprocess.check_call([sys.executable, str(BUILD_AUX / "write-version.py"),
                                   str(template), str(output)], env=env)
            self.assertEqual(output.read_text(encoding="utf-8"),
                             'BUILD_VERSION = "26.317.0132"\n')

    def test_release_notes_are_english(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "notes.md"
            subprocess.check_call([
                sys.executable, str(ROOT / "packaging/release-notes.py"),
                "--version", "26.317.0132", "--commit", "a" * 40,
                "--built-at", "2026-11-13 01:32 UTC", "--output", str(output),
            ])
            text = output.read_text(encoding="utf-8")
            self.assertIn("This release contains", text)
            self.assertIn("AppImage", text)
            self.assertIn("RPM", text)
            self.assertIn("DEB", text)
            self.assertNotIn("Correções", text)


if __name__ == "__main__":
    unittest.main()
