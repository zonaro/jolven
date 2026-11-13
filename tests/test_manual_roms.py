# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure stdlib tests for the manual ROM import kernel."""

import shlex
import tempfile
import unittest
import zipfile
from pathlib import Path

from cartridges.importer.manual_roms import (
    detect_rom, inspect_rom_zip, retroarch_launch_command, scan_rom_paths,
)


class ManualRomKernelTests(unittest.TestCase):
    def test_detects_unique_and_ambiguous_platforms(self):
        self.assertEqual(detect_rom("game.gba").platforms, ("gba",))
        self.assertFalse(detect_rom("game.gba").requires_choice)
        for name in ("disc.iso", "retro.zip", "disc.chd", "disc.cue"):
            self.assertTrue(detect_rom(name).requires_choice)
        self.assertTrue(detect_rom("unknown.txt").is_unknown)

    def test_safe_recursive_scan_ignores_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a").mkdir()
            (root / "a" / "game.gba").write_bytes(b"homebrew")
            (root / "a" / "readme.txt").write_text("notes")
            (root / "outside").symlink_to(root / "a", target_is_directory=True)
            games = list(scan_rom_paths([root]))
            self.assertEqual([g.path.name for g in games], ["game.gba"])
            self.assertLessEqual(len(list(scan_rom_paths([root], max_files=1))), 1)

    def test_zip_inspection_without_extraction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "safe.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("folder/game.nes", b"homebrew")
            self.assertEqual(inspect_rom_zip(archive), ("folder/game.nes",))
            self.assertFalse((root / "folder").exists())

            evil = root / "evil.zip"
            with zipfile.ZipFile(evil, "w") as zf:
                zf.writestr("../escape.nes", b"bad")
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                inspect_rom_zip(evil)

    def test_launch_command_quotes_user_paths(self):
        rom = Path("/roms/It's a game (USA).gba")
        core = Path("/cores/core libretro.so")
        command = retroarch_launch_command(rom, core)
        self.assertEqual(
            command,
            "retroarch -L " + shlex.quote(str(core)) + " " + shlex.quote(str(rom))
        )
        with self.assertRaises(ValueError):
            retroarch_launch_command(Path("relative.gba"), Path("/core.so"))


if __name__ == "__main__":
    unittest.main()
