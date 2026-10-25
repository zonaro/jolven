"""Pure-python tests for the ZDoom archive helpers.

The module under test is pure stdlib: it never imports GTK, the game model
or the shared configuration, so it is imported as it is and tested with real
zip files written in a temporary folder.
"""

import tempfile
import unittest
import zipfile
from pathlib import Path

from cartridges.utils import zdoom_archives


IWADINFO = """
IWad
{
\tName = "DOOM Fusion"
\tAutoname = "doom.id.fusion"
\tConfig = "Doom"
\tGame = "Doom"
}
"""


class ZdoomArchivesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def _zip(self, name: str, entries: dict[str, str]) -> Path:
        """Write a zip file with *entries* and return its path."""

        path = self.tmp / name
        with zipfile.ZipFile(path, "w") as archive:
            for entry, content in entries.items():
                archive.writestr(entry, content)
        return path

    def _game_archive(self, name: str = "game.ipk3") -> Path:
        """Write a zip file that holds the ``IWADINFO`` lump."""

        return self._zip(name, {"iwadinfo.txt": IWADINFO})


class IsGameArchiveTests(ZdoomArchivesTestCase):
    def test_a_zip_with_a_root_iwadinfo_is_a_game_archive(self) -> None:
        path = self._game_archive()
        self.assertTrue(zdoom_archives.is_game_archive(path))

    def test_a_zip_without_iwadinfo_is_not_a_game_archive(self) -> None:
        path = self._zip("plain.pk3", {"readme.txt": "nothing here"})
        self.assertFalse(zdoom_archives.is_game_archive(path))

    def test_an_empty_zip_is_not_a_game_archive(self) -> None:
        path = self._zip("empty.ipk3", {})
        self.assertFalse(zdoom_archives.is_game_archive(path))

    def test_an_iwadinfo_in_a_subdirectory_is_not_the_lump(self) -> None:
        path = self._zip("nested.ipk3", {"data/iwadinfo.txt": IWADINFO})
        self.assertFalse(zdoom_archives.is_game_archive(path))

    def test_the_lump_is_found_whatever_the_case_of_the_file_name(self) -> None:
        path = self._zip("upper.ipk3", {"IWADINFO.TXT": IWADINFO})
        self.assertTrue(zdoom_archives.is_game_archive(path))

    def test_the_lump_is_found_without_its_extension(self) -> None:
        path = self._zip("noext.ipk3", {"iwadinfo": IWADINFO})
        self.assertTrue(zdoom_archives.is_game_archive(path))

    def test_a_file_that_is_not_a_zip_is_not_a_game_archive(self) -> None:
        path = self.tmp / "notzip.ipk3"
        path.write_bytes(b"not a zip file at all")
        self.assertFalse(zdoom_archives.is_game_archive(path))

    def test_a_missing_file_is_not_a_game_archive(self) -> None:
        path = self.tmp / "missing.ipk3"
        self.assertFalse(zdoom_archives.is_game_archive(path))

    def test_a_corrupt_zip_is_not_a_game_archive(self) -> None:
        path = self.tmp / "corrupt.ipk3"
        path.write_bytes(zdoom_archives.ZIP_MAGIC + b"\x00" * 32)
        self.assertFalse(zdoom_archives.is_game_archive(path))

    def test_an_empty_file_is_not_a_game_archive(self) -> None:
        path = self.tmp / "empty_file.ipk3"
        path.write_bytes(b"")
        self.assertFalse(zdoom_archives.is_game_archive(path))

    def test_a_folder_is_not_a_game_archive(self) -> None:
        folder = self.tmp / "folder.ipk3"
        folder.mkdir()
        self.assertFalse(zdoom_archives.is_game_archive(folder))


class ReadGameNameTests(ZdoomArchivesTestCase):
    def test_the_name_of_the_game_is_read(self) -> None:
        path = self._game_archive()
        self.assertEqual(zdoom_archives.read_game_name(path), "DOOM Fusion")

    def test_the_name_is_read_from_a_block_on_a_single_line(self) -> None:
        path = self._zip("inline.ipk3", {"iwadinfo.txt": 'IWad { Name = "Heretic" }'})
        self.assertEqual(zdoom_archives.read_game_name(path), "Heretic")

    def test_the_name_of_a_block_without_a_name_is_none(self) -> None:
        path = self._zip("noname.ipk3", {"iwadinfo.txt": 'IWad { Game = "Doom" }'})
        self.assertIsNone(zdoom_archives.read_game_name(path))

    def test_a_file_without_an_iwad_block_has_no_name(self) -> None:
        path = self._zip("plain.ipk3", {"iwadinfo.txt": "just a text file"})
        self.assertIsNone(zdoom_archives.read_game_name(path))

    def test_a_missing_file_has_no_name(self) -> None:
        path = self.tmp / "missing.ipk3"
        self.assertIsNone(zdoom_archives.read_game_name(path))

    def test_a_file_that_is_not_a_zip_has_no_name(self) -> None:
        path = self.tmp / "notzip.ipk3"
        path.write_bytes(b"not a zip file at all")
        self.assertIsNone(zdoom_archives.read_game_name(path))

    def test_a_broken_encoding_does_not_raise(self) -> None:
        path = self._zip("broken.ipk3", {"iwadinfo.txt": b'IWad { Name = "DOOM \xff\xfe" }'})
        self.assertEqual(zdoom_archives.read_game_name(path), "DOOM")


if __name__ == "__main__":
    unittest.main()
