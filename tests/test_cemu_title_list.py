"""Unit tests for the Cemu title list cache reader (pure stdlib, no GTK)."""

import tempfile
import unittest
from pathlib import Path

from cartridges.utils.cemu_title_list import (
    TITLE_LIST_CACHE_NAME,
    CemuTitleListEntry,
    find_title_list_cache,
    read_title_list_cache,
)

TITLE_LIST_XML = """<?xml version="1.0" encoding="utf-8"?>
<title_list>
	<title titleId="000500001017d800" version="0" sdk_version="21004" group_id="000017d8" app_type="80000000">
		<region>2</region>
		<name>Hyrule Warriors</name>
		<format>1</format>
		<path>/roms/wiiu/Hyrule Warriors [Game] [000500001017d800]</path>
	</title>
	<title titleId="000500001010ec00" version="0" sdk_version="21004" group_id="00001010" app_type="80000000">
		<region>1</region>
		<name>New Super Mario Bros. U</name>
		<format>0</format>
		<path>/roms/wiiu/nsmbu</path>
	</title>
	<title titleId="0005000c101c3b00">
		<name>New Super Luigi U DLC</name>
		<path>/roms/wiiu/dlc.wua</path>
	</title>
	<title>
		<name>No title id</name>
		<path>/roms/wiiu/whatever</path>
	</title>
	<title titleId="0005000010145000">
		<name>No path</name>
		<path></path>
	</title>
	<title titleId="0005000010146000">
		<path>/roms/wiiu/nameless</path>
	</title>
</title_list>
"""


class TitleListCacheNameTests(unittest.TestCase):
    def test_the_name_is_the_one_used_by_cemu(self):
        self.assertEqual(TITLE_LIST_CACHE_NAME, "title_list_cache.xml")


class ReadTitleListCacheTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.cache = Path(self._tmpdir.name) / TITLE_LIST_CACHE_NAME

    def _write(self, content: str) -> Path:
        self.cache.write_text(content, encoding="utf-8")
        return self.cache

    def test_reads_the_titles_of_the_cache(self):
        entries = read_title_list_cache(self._write(TITLE_LIST_XML))
        self.assertEqual(len(entries), 4)
        self.assertEqual(
            entries[0],
            CemuTitleListEntry(
                title_id="000500001017d800",
                name="Hyrule Warriors",
                path=Path("/roms/wiiu/Hyrule Warriors [Game] [000500001017d800]"),
                format=1,
            ),
        )
        self.assertEqual(entries[1].title_id, "000500001010ec00")
        self.assertEqual(entries[1].name, "New Super Mario Bros. U")
        self.assertEqual(entries[1].path, Path("/roms/wiiu/nsmbu"))
        self.assertEqual(entries[1].format, 0)

    def test_skips_the_entries_without_a_title_id_or_a_path(self):
        entries = read_title_list_cache(self._write(TITLE_LIST_XML))
        title_ids = [entry.title_id for entry in entries]
        self.assertNotIn("", title_ids)
        self.assertNotIn("0005000010145000", title_ids)

    def test_keeps_the_entries_without_a_name(self):
        entries = read_title_list_cache(self._write(TITLE_LIST_XML))
        nameless = [entry for entry in entries if entry.title_id == "0005000010146000"]
        self.assertEqual(len(nameless), 1)
        self.assertEqual(nameless[0].name, "")

    def test_tolerates_a_missing_file(self):
        missing = Path(self._tmpdir.name) / "nowhere.xml"
        self.assertEqual(read_title_list_cache(missing), [])

    def test_tolerates_a_malformed_file(self):
        broken = self._write("<title_list><title>")
        self.assertEqual(read_title_list_cache(broken), [])

    def test_tolerates_an_empty_file(self):
        empty = self._write("")
        self.assertEqual(read_title_list_cache(empty), [])


class FindTitleListCacheTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp = Path(self._tmpdir.name)

    def test_returns_the_first_existing_candidate(self):
        first = self.tmp / "first.xml"
        second = self.tmp / "second.xml"
        second.write_text("<title_list/>", encoding="utf-8")
        self.assertEqual(
            find_title_list_cache([first, second]), second
        )

    def test_returns_none_when_no_candidate_exists(self):
        missing = self.tmp / "missing.xml"
        self.assertIsNone(find_title_list_cache([missing]))

    def test_ignores_a_candidate_that_is_a_folder(self):
        folder = self.tmp / "folder.xml"
        folder.mkdir()
        self.assertIsNone(find_title_list_cache([folder]))

    def test_returns_none_without_candidates(self):
        self.assertIsNone(find_title_list_cache([]))


if __name__ == "__main__":
    unittest.main()
