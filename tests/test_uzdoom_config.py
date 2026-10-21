"""Tests for the reading of the configuration file of UZDoom.

The module under test does not import GTK, does not write anything and
only reads files, so it is imported as is. Every test passes its own
environment and its own home directory: the tests never read the
configuration of the machine they run on.
"""

import tempfile
import unittest
from pathlib import Path

from cartridges.importer import uzdoom_config


class UzdoomConfigTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()
        self.env = {"HOME": str(self.home)}

    def _write_ini(self, relative: str, content: str) -> Path:
        """Write an INI file inside the fake home directory."""

        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path


class FindConfigFilesTests(UzdoomConfigTestCase):
    def test_nothing_is_found_without_configuration(self) -> None:
        self.assertEqual(
            uzdoom_config.find_config_files(env=self.env, home=self.home), []
        )

    def test_the_native_file_is_found(self) -> None:
        expected = self._write_ini(".config/uzdoom/uzdoom.ini", "[Global]\n")
        self.assertEqual(
            uzdoom_config.find_config_files(env=self.env, home=self.home),
            [expected],
        )

    def test_the_file_without_subdirectory_is_found(self) -> None:
        expected = self._write_ini(".config/uzdoom.ini", "[Global]\n")
        self.assertEqual(
            uzdoom_config.find_config_files(env=self.env, home=self.home),
            [expected],
        )

    def test_the_flatpak_file_is_found(self) -> None:
        expected = self._write_ini(
            ".var/app/org.zdoom.UZDoom/config/uzdoom/uzdoom.ini", "[Global]\n"
        )
        self.assertEqual(
            uzdoom_config.find_config_files(env=self.env, home=self.home),
            [expected],
        )

    def test_the_files_are_returned_in_priority_order(self) -> None:
        flatpak = self._write_ini(
            ".var/app/org.zdoom.UZDoom/config/uzdoom/uzdoom.ini", "[Global]\n"
        )
        native = self._write_ini(".config/uzdoom/uzdoom.ini", "[Global]\n")
        self.assertEqual(
            uzdoom_config.find_config_files(env=self.env, home=self.home),
            [native, flatpak],
        )

    def test_xdg_config_home_comes_first(self) -> None:
        xdg = Path(self._tmp.name) / "xdg"
        xdg.mkdir()
        expected = xdg / "uzdoom" / "uzdoom.ini"
        expected.parent.mkdir(parents=True)
        expected.write_text("[Global]\n", encoding="utf-8")
        native = self._write_ini(".config/uzdoom/uzdoom.ini", "[Global]\n")

        env = dict(self.env)
        env["XDG_CONFIG_HOME"] = str(xdg)

        self.assertEqual(
            uzdoom_config.find_config_files(env=env, home=self.home),
            [expected, native],
        )

    def test_the_same_file_is_not_returned_twice(self) -> None:
        self._write_ini(".config/uzdoom/uzdoom.ini", "[Global]\n")
        env = dict(self.env)
        env["XDG_CONFIG_HOME"] = str(self.home / ".config")

        files = uzdoom_config.find_config_files(env=env, home=self.home)
        self.assertEqual(len(files), 1)


class ParseSectionTests(UzdoomConfigTestCase):
    def test_the_order_of_the_paths_is_kept(self) -> None:
        ini = self._write_ini(
            ".config/uzdoom/uzdoom.ini",
            "[IWADSearch.Directories]\n"
            "Path=/games/one\n"
            "Path=/games/two\n"
            "Path=/games/three\n",
        )
        self.assertEqual(
            uzdoom_config.parse_section_paths(ini, "IWADSearch.Directories"),
            ["/games/one", "/games/two", "/games/three"],
        )

    def test_a_path_list_is_split(self) -> None:
        ini = self._write_ini(
            ".config/uzdoom/uzdoom.ini",
            "[FileSearch.Directories]\nPathList=/games/one:/games/two\n",
        )
        self.assertEqual(
            uzdoom_config.parse_section_paths(ini, "FileSearch.Directories"),
            ["/games/one", "/games/two"],
        )

    def test_a_recursive_path_is_a_path(self) -> None:
        ini = self._write_ini(
            ".config/uzdoom/uzdoom.ini",
            "[FileSearch.Directories]\nRecursivePath=/games/one\n",
        )
        self.assertEqual(
            uzdoom_config.parse_section_paths(ini, "FileSearch.Directories"),
            ["/games/one"],
        )

    def test_the_comments_are_skipped(self) -> None:
        ini = self._write_ini(
            ".config/uzdoom/uzdoom.ini",
            "[IWADSearch.Directories]\n"
            "# a comment\n"
            "// another comment\n"
            "Path=/games/one\n",
        )
        self.assertEqual(
            uzdoom_config.parse_section_paths(ini, "IWADSearch.Directories"),
            ["/games/one"],
        )

    def test_a_semicolon_is_not_a_comment(self) -> None:
        ini = self._write_ini(
            ".config/uzdoom/uzdoom.ini",
            "[IWADSearch.Directories]\n;Path=/games/wrong\n",
        )
        self.assertEqual(
            uzdoom_config.parse_section_paths(ini, "IWADSearch.Directories"),
            [],
        )

    def test_the_section_name_is_case_insensitive(self) -> None:
        ini = self._write_ini(
            ".config/uzdoom/uzdoom.ini",
            "[iwadsearch.directories]\nPath=/games/one\n",
        )
        self.assertEqual(
            uzdoom_config.parse_section_paths(ini, "IWADSearch.Directories"),
            ["/games/one"],
        )

    def test_the_key_name_is_case_insensitive(self) -> None:
        ini = self._write_ini(
            ".config/uzdoom/uzdoom.ini",
            "[IWADSearch.Directories]\npath=/games/one\n",
        )
        self.assertEqual(
            uzdoom_config.parse_section_paths(ini, "IWADSearch.Directories"),
            ["/games/one"],
        )

    def test_the_other_sections_are_ignored(self) -> None:
        ini = self._write_ini(
            ".config/uzdoom/uzdoom.ini",
            "[IWADSearch.Directories]\nPath=/games/one\n"
            "[FileSearch.Directories]\nPath=/games/two\n",
        )
        self.assertEqual(
            uzdoom_config.parse_section_paths(ini, "FileSearch.Directories"),
            ["/games/two"],
        )

    def test_a_missing_file_has_no_path(self) -> None:
        self.assertEqual(
            uzdoom_config.parse_section_paths(
                self.home / "nowhere" / "uzdoom.ini", "IWADSearch.Directories"
            ),
            [],
        )

    def test_garbage_has_no_path(self) -> None:
        ini = self._write_ini(
            ".config/uzdoom/uzdoom.ini",
            "this is not an INI file\n"
            "neither is this = nor this\n"
            "\x00\x01\x02\n",
        )
        self.assertEqual(
            uzdoom_config.parse_section_paths(ini, "IWADSearch.Directories"),
            [],
        )

    def test_a_multiline_value_is_skipped(self) -> None:
        ini = self._write_ini(
            ".config/uzdoom/uzdoom.ini",
            "[IWADSearch.Directories]\n"
            "Path=/games/one\n"
            "Something=<<<TAG\n"
            "not a folder\n"
            ">>>TAG\n"
            "Path=/games/two\n",
        )
        self.assertEqual(
            uzdoom_config.parse_section_paths(ini, "IWADSearch.Directories"),
            ["/games/one", "/games/two"],
        )

    def test_the_carriage_returns_are_dropped(self) -> None:
        ini = self.home / ".config" / "uzdoom" / "uzdoom.ini"
        ini.parent.mkdir(parents=True)
        ini.write_bytes(
            b"[IWADSearch.Directories]\r\nPath=/games/one\r\n"
        )
        self.assertEqual(
            uzdoom_config.parse_section_paths(ini, "IWADSearch.Directories"),
            ["/games/one"],
        )


class ExpandEntryTests(UzdoomConfigTestCase):
    def test_a_plain_path_is_kept(self) -> None:
        self.assertEqual(
            uzdoom_config.expand_entry(
                "/games/one", env=self.env, home=self.home
            ),
            "/games/one",
        )

    def test_the_home_directory_is_expanded(self) -> None:
        self.assertEqual(
            uzdoom_config.expand_entry(
                "~/games", env=self.env, home=self.home
            ),
            f"{self.home}/games",
        )

    def test_the_home_variable_is_expanded(self) -> None:
        self.assertEqual(
            uzdoom_config.expand_entry(
                "$HOME/games", env=self.env, home=self.home
            ),
            f"{self.home}/games",
        )

    def test_a_variable_that_is_set_is_expanded(self) -> None:
        env = dict(self.env)
        env["DOOMWADDIR"] = "/games"
        self.assertEqual(
            uzdoom_config.expand_entry(
                "$DOOMWADDIR/wads", env=env, home=self.home
            ),
            "/games/wads",
        )

    def test_a_variable_that_is_not_set_drops_the_entry(self) -> None:
        env = dict(self.env)
        env.pop("DOOMWADDIR", None)
        self.assertIsNone(
            uzdoom_config.expand_entry(
                "$DOOMWADDIR/wads", env=env, home=self.home
            )
        )

    def test_a_variable_that_is_empty_drops_the_entry(self) -> None:
        env = dict(self.env)
        env["DOOMWADDIR"] = ""
        self.assertIsNone(
            uzdoom_config.expand_entry(
                "$DOOMWADDIR/wads", env=env, home=self.home
            )
        )

    def test_an_empty_value_is_dropped(self) -> None:
        self.assertIsNone(
            uzdoom_config.expand_entry("   ", env=self.env, home=self.home)
        )


class EngineDefaultTests(UzdoomConfigTestCase):
    def test_the_current_directory_is_an_engine_default(self) -> None:
        self.assertTrue(
            uzdoom_config.is_engine_default(Path("."), home=self.home)
        )

    def test_the_share_folders_are_engine_defaults(self) -> None:
        for path in (
            "/usr/share",
            "/usr/share/games/uzdoom",
            "/usr/share/games/doom",
            "/usr/share/doom",
            "/usr/local/share",
            "/usr/local/share/games/uzdoom",
            "/app/share",
            "/app/share/games/doom",
        ):
            with self.subTest(path=path):
                self.assertTrue(
                    uzdoom_config.is_engine_default(Path(path), home=self.home)
                )

    def test_the_home_folders_are_engine_defaults(self) -> None:
        for path in (
            "~/.local/share/games/uzdoom",
            "~/.local/share/games/doom",
            "~/.local/share/doom",
        ):
            with self.subTest(path=path):
                self.assertTrue(
                    uzdoom_config.is_engine_default(Path(path), home=self.home)
                )

    def test_the_folder_of_the_user_is_not_an_engine_default(self) -> None:
        self.assertFalse(
            uzdoom_config.is_engine_default(
                Path("/home/tester/games"), home=self.home
            )
        )


class SearchDirsTests(UzdoomConfigTestCase):
    def test_nothing_is_found_without_configuration(self) -> None:
        self.assertEqual(
            uzdoom_config.search_dirs(
                "IWADSearch.Directories", env=self.env, home=self.home
            ),
            [],
        )

    def test_the_folders_are_found_in_order(self) -> None:
        self._write_ini(
            ".config/uzdoom/uzdoom.ini",
            "[IWADSearch.Directories]\n"
            "Path=/games/one\n"
            "Path=/games/two\n",
        )
        self.assertEqual(
            uzdoom_config.search_dirs(
                "IWADSearch.Directories", env=self.env, home=self.home
            ),
            ["/games/one", "/games/two"],
        )

    def test_the_engine_defaults_are_dropped(self) -> None:
        self._write_ini(
            ".config/uzdoom/uzdoom.ini",
            "[IWADSearch.Directories]\n"
            "Path=/usr/share/games/uzdoom\n"
            "Path=.\n"
            "Path=/usr/local/share\n"
            "Path=/games/one\n",
        )
        self.assertEqual(
            uzdoom_config.search_dirs(
                "IWADSearch.Directories", env=self.env, home=self.home
            ),
            ["/games/one"],
        )

    def test_a_folder_that_is_not_set_is_dropped(self) -> None:
        self._write_ini(
            ".config/uzdoom/uzdoom.ini",
            "[FileSearch.Directories]\n"
            "Path=$PROGDIR\n"
            "Path=/games/one\n",
        )
        env = dict(self.env)
        env.pop("PROGDIR", None)
        self.assertEqual(
            uzdoom_config.search_dirs(
                "FileSearch.Directories", env=env, home=self.home
            ),
            ["/games/one"],
        )

    def test_the_same_folder_of_two_files_is_kept_once(self) -> None:
        self._write_ini(
            ".config/uzdoom/uzdoom.ini",
            "[FileSearch.Directories]\nPath=/games/one\n",
        )
        self._write_ini(
            ".var/app/org.zdoom.UZDoom/config/uzdoom/uzdoom.ini",
            "[FileSearch.Directories]\n"
            "Path=/games/one\n"
            "Path=/games/two\n",
        )
        self.assertEqual(
            uzdoom_config.search_dirs(
                "FileSearch.Directories", env=self.env, home=self.home
            ),
            ["/games/one", "/games/two"],
        )

    def test_the_folders_are_absolute(self) -> None:
        self._write_ini(
            ".config/uzdoom/uzdoom.ini",
            "[FileSearch.Directories]\nPath=~/games/one\n",
        )
        self.assertEqual(
            uzdoom_config.search_dirs(
                "FileSearch.Directories", env=self.env, home=self.home
            ),
            [f"{self.home}/games/one"],
        )


if __name__ == "__main__":
    unittest.main()
