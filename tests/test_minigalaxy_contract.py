"""Contrato puro da leitura local do Minigalaxy (issue #158).

Sem GTK, sem GSettings e sem depender de uma instalação real do Minigalaxy: o
módulo testado só conhece os formatos de arquivo, e as fixtures em
``tests/fixtures/minigalaxy`` reproduzem as rotas observadas no upstream
(``sharkwouter/minigalaxy``, commit ``f23e237``).
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from cartridges.importer import minigalaxy


FIXTURES = Path(__file__).parent / "fixtures" / "minigalaxy"
NATIVE = FIXTURES / "native"
WINE = FIXTURES / "wine"
BROKEN = FIXTURES / "broken"


class InstallDirTests(unittest.TestCase):
    def test_reads_install_dir_from_config(self) -> None:
        install_dir = minigalaxy.read_install_dir(NATIVE / "config" / "config.json")
        self.assertEqual(install_dir, Path("~/GOG Games").expanduser())

    def test_missing_key_falls_back_to_none(self) -> None:
        config = BROKEN / "config-sem-chave" / "config.json"
        self.assertIsNone(minigalaxy.read_install_dir(config))

    def test_truncated_config_is_rejected(self) -> None:
        with self.assertRaises(minigalaxy.InvalidMinigalaxyConfig):
            minigalaxy.read_install_dir(BROKEN / "config" / "config.json")

    def test_non_text_install_dir_is_rejected(self) -> None:
        with self.assertRaises(minigalaxy.InvalidMinigalaxyConfig):
            minigalaxy.read_install_dir(BROKEN / "config-tipo" / "config.json")

    def test_relative_install_dir_is_rejected(self) -> None:
        with self.assertRaises(minigalaxy.InvalidMinigalaxyConfig):
            minigalaxy.read_install_dir(BROKEN / "config-relativo" / "config.json")

    def test_absent_config_raises_readable_error(self) -> None:
        with self.assertRaises(minigalaxy.InvalidGameMetadata):
            minigalaxy.read_install_dir(FIXTURES / "nao-existe" / "config.json")

    def test_refresh_token_never_leaks(self) -> None:
        """O contrato descarta tudo que não é ``install_dir``."""

        config = NATIVE / "config" / "config.json"
        self.assertIn("TOKEN-FICTICIO", config.read_text(encoding="utf-8"))
        install_dir = minigalaxy.read_install_dir(config)
        self.assertNotIn("TOKEN-FICTICIO", repr(install_dir))


class GameinfoTests(unittest.TestCase):
    def test_name_from_first_line_and_id_from_fifth(self) -> None:
        name, gog_id = minigalaxy.parse_gameinfo(
            NATIVE / "install" / "Beneath a Steel Sky" / "gameinfo"
        )
        self.assertEqual(name, "Beneath a Steel Sky")
        self.assertEqual(gog_id, "1207658691")

    def test_unicode_and_apostrophe_are_preserved(self) -> None:
        name, gog_id = minigalaxy.parse_gameinfo(
            NATIVE / "install" / "Assassin's Creed Ünïcode" / "gameinfo"
        )
        self.assertEqual(name, "Assassin's Creed Ünïcode")
        self.assertEqual(gog_id, "1207659000")

    def test_zero_id_is_unknown(self) -> None:
        _name, gog_id = minigalaxy.parse_gameinfo(
            NATIVE / "install" / "Sem Identificador" / "gameinfo"
        )
        self.assertIsNone(gog_id)

    def test_blank_id_is_unknown(self) -> None:
        _name, gog_id = minigalaxy.parse_gameinfo(
            NATIVE / "install" / "Sem Linha de ID" / "gameinfo"
        )
        self.assertIsNone(gog_id)

    def test_truncated_gameinfo_is_an_item_failure(self) -> None:
        with self.assertRaises(minigalaxy.InvalidGameMetadata):
            minigalaxy.parse_gameinfo(BROKEN / "install" / "Gameinfo Truncado" / "gameinfo")

    def test_invalid_utf8_is_an_item_failure(self) -> None:
        path = BROKEN / "install" / "Gameinfo UTF8 Invalido" / "gameinfo"
        with self.assertRaises(minigalaxy.InvalidGameMetadata):
            minigalaxy.parse_gameinfo(path)


class GoggameTests(unittest.TestCase):
    def test_bom_json_is_decoded(self) -> None:
        path = WINE / "install" / "Disco Elysium" / "goggame-1423049311.info"
        self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
        name, gog_id, task = minigalaxy.parse_goggame_info(path)
        self.assertEqual(name, "Disco Elysium")
        self.assertEqual(gog_id, "1423049311")
        self.assertIsNotNone(task)
        self.assertEqual(task["path"], "game/bin/Disco Elysium.exe")

    def test_primary_task_is_selected(self) -> None:
        path = WINE / "install" / "Disco Elysium" / "goggame-1423049311.info"
        _name, _gog_id, task = minigalaxy.parse_goggame_info(path)
        self.assertEqual(task["workingDir"], "game/bin")
        self.assertEqual(task["arguments"], "-force-d3d11")

    def test_invalid_json_is_an_item_failure(self) -> None:
        with self.assertRaises(minigalaxy.InvalidGameMetadata):
            minigalaxy.parse_goggame_info(BROKEN / "install" / "Goggame Invalido" / "goggame-123.info")

    def test_game_without_name_is_an_item_failure(self) -> None:
        with self.assertRaises(minigalaxy.InvalidGameMetadata):
            minigalaxy.parse_goggame_info(
                BROKEN / "install" / "Goggame Sem Nome" / "goggame-124.info"
            )

    def test_id_falls_back_to_the_file_name(self) -> None:
        name, gog_id, _task = minigalaxy.parse_goggame_info(
            BROKEN / "install" / "Goggame Hostil" / "goggame-125.info"
        )
        self.assertEqual(name, "Goggame Hostil")
        self.assertEqual(gog_id, "125")


class PreferencesTests(unittest.TestCase):
    def test_known_keys_are_read(self) -> None:
        prefs = minigalaxy.read_preferences(
            NATIVE / "config", NATIVE / "install" / "Duke Nukem 3D"
        )
        self.assertEqual(prefs.last_launch_option, "dosbox")
        self.assertTrue(prefs.use_gamemode)
        self.assertFalse(prefs.use_mangohud)

    def test_unknown_command_is_never_used(self) -> None:
        prefs = minigalaxy.read_preferences(
            NATIVE / "config", NATIVE / "install" / "Duke Nukem 3D"
        )
        self.assertFalse(hasattr(prefs, "command"))

    def test_broken_preferences_do_not_break_the_game(self) -> None:
        prefs = minigalaxy.read_preferences(
            NATIVE / "config", NATIVE / "install" / "Broken Sword"
        )
        self.assertEqual(prefs, minigalaxy.MinigalaxyPreferences())

    def test_absent_config_dir_is_empty(self) -> None:
        prefs = minigalaxy.read_preferences(None, NATIVE / "install" / "Broken Sword")
        self.assertEqual(prefs, minigalaxy.MinigalaxyPreferences())


class LauncherTests(unittest.TestCase):
    def test_start_script(self) -> None:
        directory = NATIVE / "install" / "Beneath a Steel Sky"
        kind = minigalaxy.detect_launcher(directory, ["gameinfo", "start.sh"], [])
        self.assertEqual(kind, "start_script")

    def test_dosbox_needs_the_host_program(self) -> None:
        directory = NATIVE / "install" / "Duke Nukem 3D"
        entries = ["gameinfo", "dosbox_duke3d.conf"]
        self.assertEqual(minigalaxy.detect_launcher(directory, entries, []), "unavailable")
        self.assertEqual(minigalaxy.detect_launcher(directory, entries, ["dosbox"]), "dosbox")

    def test_scummvm_needs_the_host_program(self) -> None:
        directory = NATIVE / "install" / "Broken Sword"
        entries = ["gameinfo", "scummvm.ini"]
        self.assertEqual(minigalaxy.detect_launcher(directory, entries, []), "unavailable")
        self.assertEqual(minigalaxy.detect_launcher(directory, entries, ["scummvm"]), "scummvm")

    def test_wine_prefix_requires_wine(self) -> None:
        directory = WINE / "install" / "Disco Elysium"
        entries = ["goggame-1423049311.info", "prefix"]
        self.assertEqual(minigalaxy.detect_launcher(directory, entries, []), "unavailable")
        self.assertEqual(minigalaxy.detect_launcher(directory, entries, ["wine"]), "wine")

    def test_no_known_launcher_stays_unavailable(self) -> None:
        directory = NATIVE / "install" / "pasta-aleatoria"
        self.assertEqual(
            minigalaxy.detect_launcher(directory, ["leiame.txt"], ["wine", "dosbox"]),
            "unavailable",
        )


class ScanTests(unittest.TestCase):
    def test_native_scan_lists_only_installed_games(self) -> None:
        scan = minigalaxy.scan_install_dir(
            NATIVE / "install",
            config_dir=NATIVE / "config",
            available_programs=("dosbox", "scummvm", "wine"),
        )
        names = {game.name for game in scan.games}
        self.assertEqual(
            names,
            {
                "Beneath a Steel Sky",
                "Duke Nukem 3D",
                "Broken Sword",
                "Assassin's Creed Ünïcode",
                "Sem Identificador",
                "Sem Linha de ID",
            },
        )
        self.assertTrue(scan.complete)
        self.assertEqual(scan.failures, ())
        for game in scan.games:
            self.assertEqual(game.platform, "linux")

    def test_installer_hidden_and_random_directories_are_ignored(self) -> None:
        scan = minigalaxy.scan_install_dir(NATIVE / "install")
        names = {game.directory.name for game in scan.games}
        self.assertNotIn("installer", names)
        self.assertNotIn(".oculto", names)
        self.assertNotIn("pasta-aleatoria", names)

    def test_local_artwork_is_attached(self) -> None:
        scan = minigalaxy.scan_install_dir(NATIVE / "install", config_dir=NATIVE / "config")
        game = next(g for g in scan.games if g.name == "Beneath a Steel Sky")
        self.assertEqual(game.artwork, NATIVE / "install" / "Beneath a Steel Sky" / "thumbnail.jpg")

    def test_wine_scan_reads_bom_goggame(self) -> None:
        scan = minigalaxy.scan_install_dir(
            WINE / "install", config_dir=WINE / "config", available_programs=("wine",)
        )
        by_name = {game.name: game for game in scan.games}
        self.assertIn("Disco Elysium", by_name)
        self.assertEqual(by_name["Disco Elysium"].platform, "windows")
        self.assertEqual(by_name["Disco Elysium"].gog_id, "1423049311")
        self.assertEqual(by_name["Disco Elysium"].launcher, "wine")

    def test_partial_installation_without_play_tasks_is_skipped(self) -> None:
        scan = minigalaxy.scan_install_dir(WINE / "install", available_programs=("wine",))
        names = {game.name for game in scan.games}
        self.assertNotIn("Instalacao Parcial", names)

    def test_broken_items_are_reported_without_failing_the_scan(self) -> None:
        scan = minigalaxy.scan_install_dir(BROKEN / "install")
        self.assertTrue(scan.complete)
        failures = {failure.directory.name for failure in scan.failures}
        self.assertEqual(
            failures,
            {"Gameinfo Truncado", "Gameinfo UTF8 Invalido", "Goggame Invalido", "Goggame Sem Nome"},
        )

    def test_missing_install_dir_is_an_incomplete_scan(self) -> None:
        scan = minigalaxy.scan_install_dir(FIXTURES / "nao-existe")
        self.assertFalse(scan.complete)
        self.assertEqual(scan.games, ())

    def test_install_dir_that_is_a_file_is_incomplete(self) -> None:
        scan = minigalaxy.scan_install_dir(NATIVE / "config" / "config.json")
        self.assertFalse(scan.complete)

    def test_symlink_leaving_the_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "install"
            outside = Path(directory) / "fora"
            root.mkdir()
            outside.mkdir()
            (outside / "gameinfo").write_text("Externo\n1\n1\nen\n42\n", encoding="utf-8")
            (root / "Link").symlink_to(outside)
            scan = minigalaxy.scan_install_dir(root)
            self.assertTrue(scan.complete)
            self.assertEqual(scan.games, ())
            self.assertEqual(len(scan.failures), 1)
            self.assertIn("fora da instalação", scan.failures[0].reason)

    def test_symlink_inside_the_root_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "Real"
            real.mkdir()
            (real / "gameinfo").write_text("Real\n1\n1\nen\n42\n", encoding="utf-8")
            (root / "Apelido").symlink_to(real)
            scan = minigalaxy.scan_install_dir(root)
            self.assertEqual(
                sorted(game.name for game in scan.games), ["Real", "Real"]
            )
            self.assertTrue(scan.complete)


class StableIdTests(unittest.TestCase):
    def _scan(self) -> minigalaxy.MinigalaxyScan:
        return minigalaxy.scan_install_dir(NATIVE / "install")

    def test_ids_are_prefixed_and_use_the_gog_id(self) -> None:
        ids = minigalaxy.stable_game_ids(self._scan().games)
        directory = NATIVE / "install" / "Beneath a Steel Sky"
        self.assertEqual(ids[directory], "minigalaxy_1207658691")

    def test_games_without_gog_id_get_a_deterministic_fallback(self) -> None:
        ids = minigalaxy.stable_game_ids(self._scan().games)
        directory = NATIVE / "install" / "Sem Identificador"
        self.assertEqual(ids[directory], "minigalaxy_local_sem-identificador")

    def test_duplicate_gog_ids_include_the_directory(self) -> None:
        game = minigalaxy.MinigalaxyGame(
            gog_id="42",
            name="Copia",
            platform="linux",
            directory=Path("/tmp/Copia"),
            launcher="start_script",
        )
        other = minigalaxy.MinigalaxyGame(
            gog_id="42",
            name="Copia",
            platform="linux",
            directory=Path("/tmp/Outra Copia"),
            launcher="start_script",
        )
        ids = minigalaxy.stable_game_ids((game, other))
        self.assertEqual(ids[Path("/tmp/Copia")], "minigalaxy_42_copia")
        self.assertEqual(ids[Path("/tmp/Outra Copia")], "minigalaxy_42_outra-copia")

    def test_id_is_stable_between_scans(self) -> None:
        first = minigalaxy.stable_game_ids(self._scan().games)
        second = minigalaxy.stable_game_ids(self._scan().games)
        self.assertEqual(first, second)

    def test_unicode_directory_slug_is_ascii(self) -> None:
        game = minigalaxy.MinigalaxyGame(
            gog_id=None,
            name="Ünïcode",
            platform="linux",
            directory=Path("/tmp/Ünïcode Çafé"),
            launcher="start_script",
        )
        ids = minigalaxy.stable_game_ids((game,))
        self.assertEqual(ids[Path("/tmp/Ünïcode Çafé")], "minigalaxy_local_unicode-cafe")


class FixtureHygieneTests(unittest.TestCase):
    def test_no_fixture_contains_a_real_credential(self) -> None:
        for path in FIXTURES.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for line in text.splitlines():
                if "refresh_token" in line:
                    self.assertIn("TOKEN-FICTICIO", line, path)

    def test_fixtures_are_writable_copies_for_scanning(self) -> None:
        """Cada teste que altera uma fixture trabalha numa cópia temporária."""

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "native"
            shutil.copytree(NATIVE, target)
            (target / "install" / "Beneath a Steel Sky" / "gameinfo").write_text(
                "Renomeado\n1\n1\nen\n7\n", encoding="utf-8"
            )
            scan = minigalaxy.scan_install_dir(target / "install")
            self.assertIn("Renomeado", {game.name for game in scan.games})


if __name__ == "__main__":
    unittest.main()
