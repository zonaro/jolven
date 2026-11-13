# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only RetroArch setup assistant fixtures."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cartridges.utils.retroarch_diagnostics import (
    inspect_retroarch, parse_retroarch_config,
)


class RetroArchDiagnosticsTests(unittest.TestCase):
    def test_parse_comments_quoted_values_and_duplicates(self):
        values = parse_retroarch_config(
            '# comment\nlibretro_directory = ":cores"\n'
            'libretro_directory = ":cores-new" # override\n'
            'system_directory = ":system"\n'
            'video_shader_dir = ":shaders"\n'
            'malformed line\n'
        )
        self.assertEqual(values["libretro_directory"], ":cores-new")
        self.assertEqual(values["system_directory"], ":system")

    def test_missing_config_does_not_crash(self):
        with tempfile.TemporaryDirectory() as temp:
            status = inspect_retroarch(Path(temp) / "missing.cfg")
            self.assertFalse(status.present)
            self.assertIn("config_not_found", status.warnings)

    def test_reports_user_supplied_cores_no_config_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "cores").mkdir()
            (root / "system").mkdir()
            (root / "shaders").mkdir()
            (root / "cores" / "snes9x_libretro.so").write_bytes(b"test")
            (root / "cores" / "readme.txt").write_text("not a core")
            cfg = root / "retroarch.cfg"
            config = (
                'libretro_directory = ":cores"\n'
                'system_directory = ":system"\n'
                'video_shader_dir = ":shaders"\n'
            )
            cfg.write_text(config)
            status = inspect_retroarch(cfg)
            self.assertTrue(status.present)
            self.assertEqual(status.cores, ("snes9x_libretro.so",))
            self.assertEqual(status.system_directory, root / "system")
            self.assertEqual(cfg.read_text(), config)

    def test_outside_home_is_rejected_by_default(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg = root / "retroarch.cfg"
            cfg.write_text('libretro_directory = "/etc"\n')
            status = inspect_retroarch(cfg)
            self.assertIsNone(status.core_directory)
            self.assertIn("libretro_directory_outside_allowed_roots", status.warnings)

    def test_oversized_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg = Path(temp) / "retroarch.cfg"
            cfg.write_bytes(b"x" * (1024 * 1024 + 1))
            status = inspect_retroarch(cfg)
            self.assertIn("config_too_large", status.warnings)

    def test_core_directory_symlink_outside_is_not_traversed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "real").mkdir()
            (root / "linked").symlink_to(root / "real", target_is_directory=True)
            cfg = root / "retroarch.cfg"
            cfg.write_text('libretro_directory = ":linked"\n')
            status = inspect_retroarch(cfg)
            # It is not a permission to inspect an arbitrary target path.
            self.assertEqual(status.cores, ())


if __name__ == "__main__":
    unittest.main()
