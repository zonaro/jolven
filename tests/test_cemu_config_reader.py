"""Unit tests for the Cemu settings.xml reader (pure stdlib, no GTK)."""

import tempfile
import unittest
from pathlib import Path

from cartridges.utils.cemu_config_reader import (
    CemuConfigReader,
    is_base_game_title,
)

SETTINGS_XML = """<?xml version="1.0" encoding="utf-8"?>
<content>
	<GamePaths>
		<Entry>/roms/wiiu</Entry>
		<Entry> </Entry>
	</GamePaths>
	<GameCache>
		<Entry>
			<title_id>000500001010EC00</title_id>
			<name>New Super Mario Bros. U</name>
			<custom_name></custom_name>
			<path>/roms/wiiu/nsmbu/code/content.rpx</path>
		</Entry>
		<Entry>
			<title_id>0005000c101c3b00</title_id>
			<name>New Super Luigi U DLC</name>
			<path>/roms/wiiu/dlc.wua</path>
		</Entry>
		<Entry>
			<title_id>0005000e1010ec00</title_id>
			<name>Update</name>
			<path>/roms/wiiu/update.wua</path>
		</Entry>
		<Entry>
			<title_id></title_id>
			<name>No title id</name>
			<path>/roms/wiiu/whatever.rpx</path>
		</Entry>
		<Entry>
			<title_id>0005000010144d00</title_id>
			<name></name>
			<custom_name>Renamed Game</custom_name>
			<path>/roms/wiiu/renamed/code/content.rpx</path>
		</Entry>
		<Entry>
			<title_id>0005000010145000</title_id>
			<name>No path</name>
			<path></path>
		</Entry>
	</GameCache>
</content>
"""


class CemuConfigReaderTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.settings_file = Path(self._tmpdir.name) / "settings.xml"

    def _write(self, content: str) -> Path:
        self.settings_file.write_text(content, encoding="utf-8")
        return self.settings_file

    def test_reads_game_paths_and_cache_entries(self):
        reader = CemuConfigReader(self._write(SETTINGS_XML))
        self.assertEqual(reader.get_game_paths(), ["/roms/wiiu"])
        entries = list(reader.get_game_cache_entries())
        self.assertEqual(len(entries), 4)
        self.assertEqual(entries[0]["title_id"], "000500001010EC00")
        self.assertEqual(entries[0]["name"], "New Super Mario Bros. U")
        self.assertEqual(entries[0]["custom_name"], "")
        self.assertEqual(entries[0]["path"], "/roms/wiiu/nsmbu/code/content.rpx")
        self.assertEqual(entries[3]["custom_name"], "Renamed Game")

    def test_accepts_keys_at_document_root(self):
        reader = CemuConfigReader(
            self._write(
                "<settings><GameCache><Entry>"
                "<title_id>00050000101c9200</title_id>"
                "<path>/roms/metroid.rpx</path>"
                "</Entry></GameCache></settings>"
            )
        )
        entries = list(reader.get_game_cache_entries())
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title_id"], "00050000101c9200")

    def test_tolerates_missing_and_malformed_files(self):
        missing = CemuConfigReader(Path(self._tmpdir.name) / "nope.xml")
        self.assertEqual(missing.get_game_paths(), [])
        self.assertEqual(list(missing.get_game_cache_entries()), [])

        broken = CemuConfigReader(self._write("<content><GameCache>"))
        self.assertEqual(broken.get_game_paths(), [])
        self.assertEqual(list(broken.get_game_cache_entries()), [])

    def test_tolerates_missing_sections(self):
        reader = CemuConfigReader(self._write("<content></content>"))
        self.assertEqual(reader.get_game_paths(), [])
        self.assertEqual(list(reader.get_game_cache_entries()), [])


class BaseTitleFilterTests(unittest.TestCase):
    def test_accepts_base_games_only(self):
        self.assertTrue(is_base_game_title("000500001010EC00"))
        self.assertTrue(is_base_game_title("00050000101c9200"))
        self.assertFalse(is_base_game_title("0005000c101c3b00"))  # DLC
        self.assertFalse(is_base_game_title("0005000e1010ec00"))  # update
        self.assertFalse(is_base_game_title("000500101004a000"))  # system
        self.assertFalse(is_base_game_title(""))


if __name__ == "__main__":
    unittest.main()
