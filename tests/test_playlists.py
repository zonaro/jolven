# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline game-id playlist behavior."""

import tempfile
import unittest
from pathlib import Path

from cartridges.utils.playlists import PlaylistStore


class PlaylistStoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "playlists.json"
        self.store = PlaylistStore(self.path)

    def test_create_member_reorder_and_reload(self):
        playlist = self.store.create("Retro")
        self.store.set_member(playlist["id"], "retroarch_a", True)
        self.store.set_member(playlist["id"], "steam_42", True)
        self.store.set_member(playlist["id"], "retroarch_a", True)
        self.store.reorder(playlist["id"], ["steam_42", "retroarch_a"])
        reloaded = PlaylistStore(self.path).all()[0]
        self.assertEqual(reloaded["games"], ["steam_42", "retroarch_a"])
        self.store.set_member(playlist["id"], "steam_42", False)
        self.assertEqual(self.store.all()[0]["games"], ["retroarch_a"])

    def test_rename_delete_dont_touch_game_files(self):
        game_data = self.path.parent / "game.json"
        game_data.write_text('{"test":true}')
        playlist = self.store.create("Old")
        self.store.rename(playlist["id"], "New")
        self.assertEqual(self.store.all()[0]["title"], "New")
        self.store.delete(playlist["id"])
        self.assertEqual(self.store.all(), [])
        self.assertEqual(game_data.read_text(), '{"test":true}')

    def test_invalid_existing_json_is_not_destroyed(self):
        self.path.write_text("{broken")
        with self.assertRaises(ValueError):
            self.store.create("Any")
        self.assertEqual(self.path.read_text(), "{broken")

    def test_duplicate_titles_and_bad_reorder_rejected(self):
        playlist = self.store.create("Favorites")
        with self.assertRaises(ValueError):
            self.store.create("favorites")
        self.store.set_member(playlist["id"], "steam_42", True)
        with self.assertRaises(ValueError):
            self.store.reorder(playlist["id"], ["wrong_game"])
        self.assertEqual(self.store.all()[0]["games"], ["steam_42"])


if __name__ == "__main__":
    unittest.main()
