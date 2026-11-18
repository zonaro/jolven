# test_console_adapter.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Adaptador da biblioteca Jolven para DTOs do ConsoleUI (issue #183)."""

import unittest
from types import SimpleNamespace

from cartridges import console_adapter


def make_game(**kwargs):
    defaults = {
        "name": "Game",
        "game_id": "game_1",
        "source": "steam_42",
        "base_source": "steam",
        "description": "Desc",
        "developer": "Dev",
        "publisher": "Pub",
        "release_date": "2020",
        "genre": "Action",
        "controller_support": "full",
        "gamepad_recommended": True,
        "rating": 4,
        "added": 10,
        "last_played": 0,
        "playtime": 0,
        "hidden": False,
        "removed": False,
        "blacklisted": False,
        "tags": ["RPG", "Action"],
        "track_updates": False,
        "update_available_ts": 0,
        "update_url": "",
        "status": "",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class SummaryTests(unittest.TestCase):
    def test_to_summary_roundtrip(self):
        game = make_game(name="Hollow Knight", game_id="a", rating=5)
        summary = console_adapter.to_summary(game)
        self.assertEqual(summary.game_id, "a")
        self.assertEqual(summary.name, "Hollow Knight")
        self.assertEqual(summary.stars, 5)
        self.assertEqual(summary.tags, ("RPG", "Action"))
        self.assertFalse(summary.has_update)

    def test_missing_fields_default(self):
        game = SimpleNamespace(game_id="x", name="Y", source="z")
        summary = console_adapter.to_summary(game)
        self.assertEqual(summary.base_source, "z")
        self.assertIsNone(summary.description)
        self.assertEqual(summary.installed, True)

    def test_rating_clamped(self):
        game = make_game(rating="not a number")
        self.assertEqual(console_adapter.to_summary(game).stars, 0)

    def test_has_update_requires_track_and_ts(self):
        game = make_game(track_updates=True, update_available_ts=123)
        self.assertTrue(console_adapter.to_summary(game).has_update)
        game.update_available_ts = 0
        self.assertFalse(console_adapter.to_summary(game).has_update)

    def test_zerado_only_when_status_beaten(self):
        game = make_game(status="beaten", removed=True)
        self.assertTrue(console_adapter.to_summary(game).zerado)
        game.status = ""
        self.assertFalse(console_adapter.to_summary(game).zerado)


class DetailsTests(unittest.TestCase):
    def test_to_details_includes_summary(self):
        game = make_game(name="Celeste", game_id="b")
        details = console_adapter.to_details(game)
        self.assertEqual(details.summary.game_id, "b")
        self.assertEqual(details.summary.name, "Celeste")

    def test_to_details_missing_fields(self):
        game = SimpleNamespace(game_id="x", name="Y")
        details = console_adapter.to_details(game)
        self.assertIsNone(details.steam_appid)
        self.assertEqual(details.tgdb_screenshots, ())


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.games = [
            make_game(name="Alpha", game_id="a", last_played=100),
            make_game(name="Beta", game_id="b", last_played=50),
            make_game(name="Gamma", game_id="c", hidden=True, last_played=999),
            make_game(name="Delta", game_id="d", removed=True, last_played=200),
            make_game(name="Epsilon", game_id="e", blacklisted=True, last_played=300),
        ]

    def test_hidden_and_removed_excluded_by_default(self):
        snapshot = console_adapter.list_snapshot(self.games, revision=7)
        ids = [item.game_id for item in snapshot.items]
        self.assertEqual(ids, ["a", "b"])
        self.assertEqual(snapshot.revision, 7)
        self.assertEqual(snapshot.total, 2)

    def test_include_hidden_keeps_visible(self):
        snapshot = console_adapter.list_snapshot(self.games, include_hidden=True)
        ids = {item.game_id for item in snapshot.items}
        self.assertIn("c", ids)
        self.assertNotIn("d", ids)  # removed continua fora
        self.assertNotIn("e", ids)  # blacklisted continua fora

    def test_pagination(self):
        snapshot = console_adapter.list_snapshot(self.games, offset=1, limit=1)
        self.assertEqual(len(snapshot.items), 1)
        self.assertEqual(snapshot.items[0].game_id, "b")
        self.assertEqual(snapshot.offset, 1)

    def test_sort_by_last_playedThen_name(self):
        fresh = [
            make_game(name="Zulu", game_id="z", last_played=10),
            make_game(name="Bravo", game_id="b", last_played=50),
            make_game(name="Alpha", game_id="a", last_played=50),
            make_game(name="The Outer Worlds", game_id="o", last_played=5),
        ]
        snapshot = console_adapter.list_snapshot(fresh)
        ids = [item.game_id for item in snapshot.items]
        self.assertEqual(ids, ["a", "b", "z", "o"])

    def test_list_summaries_returns_plain(self):
        summaries = console_adapter.list_summaries(self.games)
        self.assertIsInstance(summaries, list)
        self.assertTrue(all(isinstance(s, console_adapter.GameSummary) for s in summaries))

    def test_find_by_id(self):
        game = console_adapter.find_by_id(self.games, "b")
        self.assertEqual(game.name, "Beta")
        self.assertIsNone(console_adapter.find_by_id(self.games, "missing"))

    def test_details_by_id(self):
        details = console_adapter.details_by_id(self.games, "a")
        self.assertEqual(details.summary.game_id, "a")
        self.assertIsNone(console_adapter.details_by_id(self.games, "missing"))


class GroupingTests(unittest.TestCase):
    def setUp(self):
        self._orig = console_adapter._carregar_agrupamento

    def tearDown(self):
        console_adapter._carregar_agrupamento = self._orig

    @staticmethod
    def _fake_ag(mapping):
        """Fake mínimo do módulo agrupamento para testes headless."""

        class FakeAg:
            @staticmethod
            def ativo():
                return True

            @staticmethod
            def elegivel(game):
                return not (
                    getattr(game, "removed", False)
                    or getattr(game, "blacklisted", False)
                    or getattr(game, "hidden", False)
                    or getattr(game, "is_launcher", False)
                )

            @staticmethod
            def construir_indice(all_games, agrupar=True):
                grupos = {}
                for game in all_games:
                    if not agrupar or not FakeAg.elegivel(game):
                        continue
                    key = mapping.get(game.game_id, game.game_id)
                    grupos.setdefault(key, []).append(game)
                return {key: members for key, members in grupos.items()}

            @staticmethod
            def primario(members):
                return members[0]

        return FakeAg

    def test_variant_group_shows_only_primary(self):
        mapping = {"a": "DOOM", "b": "DOOM"}
        console_adapter._carregar_agrupamento = lambda: self._fake_ag(mapping)
        games = [
            make_game(name="DOOM", game_id="a", base_source="uzdoom"),
            make_game(name="DOOM", game_id="b", base_source="steam"),
        ]
        snapshot = console_adapter.list_snapshot(games)
        self.assertEqual([item.game_id for item in snapshot.items], ["a"])

    def test_grouping_fallback_without_module(self):
        console_adapter._carregar_agrupamento = lambda: None
        games = [
            make_game(name="DOOM", game_id="a", base_source="uzdoom"),
            make_game(name="DOOM", game_id="b", base_source="steam"),
        ]
        snapshot = console_adapter.list_snapshot(games)
        self.assertEqual({item.game_id for item in snapshot.items}, {"a", "b"})

    def test_grouping_disabled_by_param(self):
        mapping = {"a": "DOOM", "b": "DOOM"}
        console_adapter._carregar_agrupamento = lambda: self._fake_ag(mapping)
        games = [
            make_game(name="DOOM", game_id="a", base_source="uzdoom"),
            make_game(name="DOOM", game_id="b", base_source="steam"),
        ]
        snapshot = console_adapter.list_snapshot(games, usar_agrupamento=False)
        self.assertEqual({item.game_id for item in snapshot.items}, {"a", "b"})


class FilterParityTests(unittest.TestCase):
    def setUp(self):
        self._orig_restauracao = console_adapter._restauracao_pendente
        console_adapter._restauracao_pendente = lambda _id: False

    def tearDown(self):
        console_adapter._restauracao_pendente = self._orig_restauracao

    def test_launcher_hidden_from_main_library(self):
        games = [
            make_game(name="Steam", game_id="l", is_launcher=True),
            make_game(name="Quake", game_id="q"),
        ]
        snapshot = console_adapter.list_snapshot(games, usar_agrupamento=False)
        self.assertEqual([item.game_id for item in snapshot.items], ["q"])

    def test_hidden_launcher_appears_in_include_hidden(self):
        games = [make_game(name="Steam", game_id="l", is_launcher=True, hidden=True)]
        snapshot = console_adapter.list_snapshot(games, include_hidden=True, usar_agrupamento=False)
        self.assertEqual([item.game_id for item in snapshot.items], ["l"])

    def test_xcloud_hidden_without_schema_flag(self):
        games = [make_game(name="xCloud Game", game_id="x", base_source="xcloud", source="xcloud_gamepass")]
        snapshot = console_adapter.list_snapshot(games, xcloud_enabled=False, usar_agrupamento=False)
        self.assertEqual(snapshot.items, ())
        snapshot = console_adapter.list_snapshot(games, xcloud_enabled=True, usar_agrupamento=False)
        self.assertEqual([item.game_id for item in snapshot.items], ["x"])

    def test_restore_pending_filtered(self):
        console_adapter._restauracao_pendente = lambda game_id: game_id == "p"
        games = [make_game(name="Pending", game_id="p"), make_game(name="Other", game_id="o")]
        snapshot = console_adapter.list_snapshot(games, usar_agrupamento=False)
        self.assertEqual([item.game_id for item in snapshot.items], ["o"])

    def test_metadata_refresh_between_snapshots(self):
        game = make_game(name="Late", game_id="t", playtime=10)
        first = console_adapter.to_summary(game)
        game.playtime = 40
        game.last_played = 123
        second = console_adapter.to_summary(game)
        self.assertEqual(first.playtime, 10)
        self.assertEqual(second.playtime, 40)
        self.assertEqual(second.last_played, 123)


if __name__ == "__main__":
    unittest.main()
