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


if __name__ == "__main__":
    unittest.main()
