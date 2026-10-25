"""Unit tests for the Cemu game folder scanner (pure stdlib, no GTK)."""

import tempfile
import unittest
from pathlib import Path

from cartridges.utils.cemu_game_scan import (
    EXTRACTED_GAME_FOLDERS,
    GAME_FILE_EXTENSIONS,
    TITLE_TMD_NAME,
    CemuScannedGame,
    clean_game_name,
    scan_game_paths,
)


class CemuGameScanTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.roms = Path(self._tmpdir.name) / "roms"
        self.roms.mkdir()

    def _make_game_folder(
        self,
        name: str,
        *,
        title_id: str | None = None,
        meta_ini: str | None = None,
        parent: Path | None = None,
    ) -> Path:
        """Create a folder that looks like an extracted game."""
        folder = (parent or self.roms) / name
        for part in EXTRACTED_GAME_FOLDERS:
            (folder / part).mkdir(parents=True, exist_ok=True)
        if title_id is not None:
            (folder / "meta" / "meta.xml").write_text(
                '<?xml version="1.0" encoding="utf-8"?>\n'
                "<u8>\n"
                f"\t<title_id>{title_id}</title_id>\n"
                "\t<title_version>0</title_version>\n"
                "</u8>\n",
                encoding="utf-8",
            )
        if meta_ini is not None:
            (folder / "meta" / "meta.ini").write_text(meta_ini, encoding="utf-8")
        return folder

    def _by_title_id(self, games, title_id: str) -> CemuScannedGame | None:
        for game in games:
            if game.title_id.lower() == title_id.lower():
                return game
        return None


class ConstantsTests(unittest.TestCase):
    def test_the_known_extensions(self):
        self.assertEqual(
            GAME_FILE_EXTENSIONS, (".wud", ".wux", ".iso", ".wua", ".wuhb")
        )

    def test_the_name_of_a_nus_title(self):
        self.assertEqual(TITLE_TMD_NAME, "title.tmd")

    def test_the_folders_of_an_extracted_game(self):
        self.assertEqual(EXTRACTED_GAME_FOLDERS, ("content", "code", "meta"))


class CleanGameNameTests(unittest.TestCase):
    def test_drops_the_bracketed_groups(self):
        self.assertEqual(
            clean_game_name("Hyrule Warriors [Game] [000500001017d800]"),
            "Hyrule Warriors",
        )

    def test_keeps_a_name_without_groups(self):
        self.assertEqual(clean_game_name("Hyrule Warriors"), "Hyrule Warriors")


class ScanGamePathsTests(CemuGameScanTestCase):
    def test_finds_an_extracted_game(self):
        folder = self._make_game_folder(
            "Hyrule Warriors [Game] [000500001017d800]",
            title_id="000500001017D800",
        )

        games = scan_game_paths([self.roms])

        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].title_id, "000500001017D800")
        self.assertEqual(games[0].name, "Hyrule Warriors")
        self.assertEqual(games[0].path, folder)

    def test_uses_the_name_of_the_meta_ini(self):
        self._make_game_folder(
            "Super Mario [000500001010ec00]",
            meta_ini="[Info]\nlongname_en=Super Mario Bros. U\nshortname_en=SMBU\n",
        )

        games = scan_game_paths([self.roms])

        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].title_id, "000500001010ec00")
        self.assertEqual(games[0].name, "Super Mario Bros. U")

    def test_takes_the_title_id_of_the_code_folder(self):
        folder = self._make_game_folder("Super Mario [000500001010ec00]")
        (folder / "code" / "app.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<App>\n"
            "\t<title_id>000500001010ec00</title_id>\n"
            "</App>\n",
            encoding="utf-8",
        )

        games = scan_game_paths([self.roms])

        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].title_id, "000500001010ec00")

    def test_skips_the_dlc_and_the_update(self):
        self._make_game_folder(
            "DLC Pack [0005000c101c3b00]", title_id="0005000c101c3b00"
        )
        self._make_game_folder(
            "Game Update [0005000e1010ec00]", title_id="0005000e1010ec00"
        )

        self.assertEqual(scan_game_paths([self.roms]), [])

    def test_finds_a_nus_title(self):
        folder = self.roms / "NUS Game [000500001017d900]"
        folder.mkdir()
        title = folder / TITLE_TMD_NAME
        title.write_bytes(b"\x00\x01")

        games = scan_game_paths([self.roms])

        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].title_id, "000500001017d900")
        self.assertEqual(games[0].path, title)

    def test_skips_a_nus_title_with_an_incomplete_download(self):
        folder = self.roms / "NUS Game [000500001017d900]"
        folder.mkdir()
        (folder / TITLE_TMD_NAME).write_bytes(b"\x00\x01")
        (folder / "0000003D.app.part").write_bytes(b"\x00\x01")

        self.assertEqual(scan_game_paths([self.roms]), [])

    def test_keeps_a_nus_title_whose_download_is_finished(self):
        folder = self.roms / "NUS Game [000500001017d900]"
        folder.mkdir()
        (folder / TITLE_TMD_NAME).write_bytes(b"\x00\x01")
        (folder / "0000003D.app.part").write_bytes(b"\x00\x01")
        (folder / "0000003D.app").write_bytes(b"\x00\x01")

        games = scan_game_paths([self.roms])

        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].title_id, "000500001017d900")

    def test_finds_an_archive(self):
        archive = self.roms / "Archive Game [000500001017da00].wud"
        archive.write_bytes(b"\x00\x01")

        games = scan_game_paths([self.roms])

        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].title_id, "000500001017da00")
        self.assertEqual(games[0].name, "Archive Game")
        self.assertEqual(games[0].path, archive)

    def test_finds_every_known_extension(self):
        for index, extension in enumerate(GAME_FILE_EXTENSIONS):
            title_id = f"0005000010{index:06x}"
            archive = self.roms / f"Game {index} [{title_id}].{extension}"
            archive.write_bytes(b"\x00\x01")

        games = scan_game_paths([self.roms])

        self.assertEqual(len(games), len(GAME_FILE_EXTENSIONS))

    def test_ignores_a_folder_without_the_three_folders(self):
        folder = self.roms / "Just A Folder"
        folder.mkdir()
        (folder / "readme.txt").write_text("nothing", encoding="utf-8")

        self.assertEqual(scan_game_paths([self.roms]), [])

    def test_ignores_a_missing_root(self):
        missing = self.roms / "nowhere"

        self.assertEqual(scan_game_paths([missing]), [])

    def test_ignores_a_game_without_a_title_id(self):
        self._make_game_folder("No Id Game")

        self.assertEqual(scan_game_paths([self.roms]), [])

    def test_ignores_the_hidden_folders(self):
        folder = self._make_game_folder(
            "Hidden [000500001017d800]", title_id="000500001017D800"
        )
        hidden = self.roms / ".hidden"
        hidden.mkdir()
        folder.rename(hidden / folder.name)

        self.assertEqual(scan_game_paths([self.roms]), [])

    def test_the_depth_is_bounded(self):
        deep = self.roms
        for level in range(8):
            deep = deep / f"level{level}"
            deep.mkdir()
        self._make_game_folder(
            "Deep Game [000500001017d800]",
            title_id="000500001017D800",
            parent=deep,
        )

        self.assertEqual(scan_game_paths([self.roms], max_depth=2), [])
        self.assertEqual(len(scan_game_paths([self.roms], max_depth=10)), 1)

    def test_a_title_is_found_only_once(self):
        self._make_game_folder(
            "Hyrule Warriors [Game] [000500001017d800]",
            title_id="000500001017D800",
        )
        self._make_game_folder(
            "Hyrule Warriors (other copy) [000500001017d800]",
            title_id="000500001017d800",
        )

        self.assertEqual(len(scan_game_paths([self.roms])), 1)

    def test_the_root_may_be_a_game_folder(self):
        folder = self._make_game_folder(
            "Hyrule Warriors [Game] [000500001017d800]",
            title_id="000500001017D800",
        )

        games = scan_game_paths([folder])

        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].path, folder)


if __name__ == "__main__":
    unittest.main()
