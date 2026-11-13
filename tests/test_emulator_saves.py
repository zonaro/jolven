# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure stdlib portable save backup tests."""

import tempfile
import unittest
import zipfile
from pathlib import Path

from cartridges.utils.emulator_saves import (
    create_save_backup, restore_save_backup, MANIFEST_NAME,
)


class EmulatorSaveBackupTests(unittest.TestCase):
    def test_roundtrip_without_overwriting_existing_save(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original = root / "example.srm"
            original.write_bytes(b"homebrew save data")
            backup = root / "backup.zip"
            manifest = create_save_backup([original], backup, emulator_hint="RetroArch")
            self.assertEqual(manifest["files"][0]["name"], "example.srm")

            dest = root / "restored"
            dest.mkdir()
            result = restore_save_backup(backup, dest)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].read_bytes(), b"homebrew save data")
            with self.assertRaises(FileExistsError):
                restore_save_backup(backup, dest)
            self.assertEqual(result[0].read_bytes(), b"homebrew save data")

    def test_unsafe_extra_zip_path_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            save = root / "s.srm"
            save.write_bytes(b"test")
            archive = root / "backup.zip"
            create_save_backup([save], archive)
            with zipfile.ZipFile(archive, "a") as zf:
                zf.writestr("../escape", b"bad")
            out = root / "out"
            out.mkdir()
            with self.assertRaisesRegex(ValueError, "Unexpected ZIP"):
                restore_save_backup(archive, out)
            self.assertEqual(list(out.iterdir()), [])

    def test_refuses_symlink_input_and_self_backup(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original = root / "data.srm"
            original.write_bytes(b"a")
            link = root / "shortcut.srm"
            link.symlink_to(original)
            with self.assertRaises(ValueError):
                create_save_backup([link], root / "back.zip")

            target = root / "back.zip"
            with self.assertRaises(ValueError):
                create_save_backup([target], target)

    def test_manifest_is_present(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            save = root / "one.sav"
            save.write_bytes(b"save")
            archive = root / "b.zip"
            create_save_backup([save], archive)
            with zipfile.ZipFile(archive) as zf:
                self.assertIn(MANIFEST_NAME, zf.namelist())


if __name__ == "__main__":
    unittest.main()
