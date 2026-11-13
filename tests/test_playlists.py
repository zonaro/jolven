# test_playlists.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Playlists pessoais (issue #155): modelo puro, sem GTK.

Cobre criar/renomear/apagar, adicionar/remover/reordenar/mover/prune,
estabilidade de id (nunca reutilizado), arquivo corrompido, gravação
atômica, preservação de campos desconhecidos, ``for_game`` e o round-trip
do JSON. O módulo é importado sem GTK: nenhum teste toca em ``gi``.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from cartridges.utils import playlists


class BasePlaylists(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self._tmp.name)
        self.path = self.directory / "playlists.json"
        self.store = playlists.PlaylistStore(path=self.path)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class PlaylistCrudTests(BasePlaylists):
    def test_create_returns_a_playlist(self) -> None:
        playlist = self.store.create("Favoritas do fim de semana")
        self.assertEqual(playlist.name, "Favoritas do fim de semana")
        self.assertEqual(playlist.game_ids, [])
        self.assertEqual(self.store.playlists, (playlist,))
        self.assertEqual(self.store.playlist_ids(), (playlist.playlist_id,))

    def test_ids_are_stable_slugs(self) -> None:
        primeira = self.store.create("Favoritas")
        self.assertEqual(primeira.playlist_id, "favoritas")
        segunda = self.store.create("Favoritas")
        self.assertEqual(segunda.playlist_id, "favoritas-2")

    def test_slug_strips_accents_and_symbols(self) -> None:
        playlist = self.store.create("Ação & Aventura!!")
        self.assertEqual(playlist.playlist_id, "acao-aventura")

    def test_deleted_ids_are_never_reused(self) -> None:
        primeira = self.store.create("Favoritas")
        self.store.delete(primeira.playlist_id)
        segunda = self.store.create("Favoritas")
        self.assertNotEqual(segunda.playlist_id, primeira.playlist_id)

    def test_no_id_reuse_across_stores(self) -> None:
        """O contador vive no arquivo: reabrir a store não reemite ids."""
        primeira = self.store.create("Favoritas")
        self.store.delete(primeira.playlist_id)
        self.store.save()

        reaberta = playlists.PlaylistStore(path=self.path)
        segunda = reaberta.create("Favoritas")
        self.assertNotEqual(segunda.playlist_id, primeira.playlist_id)

    def test_rename_keeps_the_id_and_order(self) -> None:
        playlist = self.store.create("Favoritas")
        self.store.add(playlist.playlist_id, ["a", "b"])
        self.store.rename(playlist.playlist_id, "Melhores")
        self.assertEqual(playlist.name, "Melhores")
        self.assertEqual(playlist.playlist_id, "favoritas")
        self.assertEqual(playlist.game_ids, ["a", "b"])

    def test_rename_unknown_or_empty_is_a_noop(self) -> None:
        playlist = self.store.create("Favoritas")
        self.store.rename(playlist.playlist_id, "   ")
        self.assertEqual(playlist.name, "Favoritas")
        self.store.rename("inexistente", "Outro")
        self.assertEqual(len(self.store.playlists), 1)

    def test_delete_unknown_is_a_noop(self) -> None:
        self.store.delete("inexistente")
        self.assertEqual(self.store.playlists, ())

    def test_create_never_raises_on_empty_name(self) -> None:
        playlist = self.store.create("   ")
        self.assertTrue(playlist.playlist_id)


class PlaylistMembershipTests(BasePlaylists):
    def setUp(self) -> None:
        super().setUp()
        self.playlist = self.store.create("Favoritas")

    def test_add_appends_without_duplicates(self) -> None:
        self.store.add(self.playlist.playlist_id, ["a", "b"])
        self.store.add(self.playlist.playlist_id, ["b", "c"])
        self.assertEqual(self.playlist.game_ids, ["a", "b", "c"])

    def test_remove_keeps_the_rest_in_order(self) -> None:
        self.store.add(self.playlist.playlist_id, ["a", "b", "c"])
        self.store.remove(self.playlist.playlist_id, ["b"])
        self.assertEqual(self.playlist.game_ids, ["a", "c"])

    def test_reorder_sets_the_full_order(self) -> None:
        self.store.add(self.playlist.playlist_id, ["a", "b", "c", "d"])
        self.store.reorder(self.playlist.playlist_id, ["d", "a", "c", "b"])
        self.assertEqual(self.playlist.game_ids, ["d", "a", "c", "b"])

    def test_reorder_deduplicates(self) -> None:
        self.store.add(self.playlist.playlist_id, ["a"])
        self.store.reorder(self.playlist.playlist_id, ["a", "a", "a"])
        self.assertEqual(self.playlist.game_ids, ["a"])

    def test_move_inserts_at_index(self) -> None:
        self.store.add(self.playlist.playlist_id, ["a", "b", "c"])
        self.store.move(self.playlist.playlist_id, "c", 0)
        self.assertEqual(self.playlist.game_ids, ["c", "a", "b"])

    def test_move_clamps_at_the_edges(self) -> None:
        self.store.add(self.playlist.playlist_id, ["a", "b", "c"])
        self.store.move(self.playlist.playlist_id, "a", 99)
        self.assertEqual(self.playlist.game_ids, ["b", "c", "a"])
        self.store.move(self.playlist.playlist_id, "a", -5)
        self.assertEqual(self.playlist.game_ids, ["a", "b", "c"])

    def test_move_unknown_game_is_a_noop(self) -> None:
        self.store.add(self.playlist.playlist_id, ["a", "b"])
        self.store.move(self.playlist.playlist_id, "z", 0)
        self.assertEqual(self.playlist.game_ids, ["a", "b"])

    def test_prune_drops_missing_games_but_keeps_the_playlist(self) -> None:
        self.store.add(self.playlist.playlist_id, ["a", "b", "c"])
        self.store.prune({"a", "c", "d"})
        self.assertEqual(self.playlist.game_ids, ["a", "c"])
        self.assertEqual(len(self.store.playlists), 1)

    def test_prune_rewrites_the_file(self) -> None:
        self.store.add(self.playlist.playlist_id, ["a", "b"])
        self.store.prune({"a"})
        reaberta = playlists.PlaylistStore(path=self.path)
        self.assertEqual(
            reaberta.get(self.playlist.playlist_id).game_ids, ["a"]
        )

    def test_bad_input_never_raises(self) -> None:
        self.store.add(self.playlist.playlist_id, None)
        self.store.add("inexistente", ["a"])
        self.store.add(self.playlist.playlist_id, [123, "ok", None])
        self.assertEqual(self.playlist.game_ids, ["ok"])
        self.store.remove(self.playlist.playlist_id, 42)
        # Uma string solta é um game_id só: entra na playlist como qualquer
        # outro, e não derruba nada.
        self.store.reorder(self.playlist.playlist_id, "texto-solto")
        self.assertEqual(self.playlist.game_ids, ["texto-solto"])

    def test_for_game_lists_only_playlists_that_have_it(self) -> None:
        outra = self.store.create("RPGs")
        self.store.add(self.playlist.playlist_id, ["a", "b"])
        self.store.add(outra.playlist_id, ["b"])
        self.assertEqual(
            [p.playlist_id for p in self.store.for_game("a")],
            [self.playlist.playlist_id],
        )
        self.assertEqual(
            {p.playlist_id for p in self.store.for_game("b")},
            {self.playlist.playlist_id, outra.playlist_id},
        )
        self.assertEqual(self.store.for_game("z"), ())


class PlaylistFileTests(BasePlaylists):
    def test_round_trip(self) -> None:
        primeira = self.store.create("Favoritas")
        self.store.add(primeira.playlist_id, ["a", "b"])
        self.store.move(primeira.playlist_id, "b", 0)
        self.store.rename(primeira.playlist_id, "Melhores")

        reaberta = playlists.PlaylistStore(path=self.path)
        playlist = reaberta.get(primeira.playlist_id)
        self.assertIsNotNone(playlist)
        self.assertEqual(playlist.name, "Melhores")
        self.assertEqual(playlist.game_ids, ["b", "a"])
        self.assertEqual(playlist.created_at, primeira.created_at)
        self.assertEqual(playlist.updated_at, primeira.updated_at)
        self.assertEqual(reaberta.playlist_ids(), primeira.playlist_id and (primeira.playlist_id,))

    def test_save_is_atomic_and_leaves_no_temp_file(self) -> None:
        self.store.create("Favoritas")
        self.store.save()
        arquivos = sorted(item.name for item in self.directory.iterdir())
        self.assertEqual(arquivos, ["playlists.json"])
        dados = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(dados["version"], playlists.PLAYLISTS_VERSION)

    def test_unknown_top_level_fields_are_preserved(self) -> None:
        original = {
            "version": playlists.PLAYLISTS_VERSION,
            "playlists": [],
            "used_ids": [],
            "counter": 0,
            "toque_personalizado": {"cor": "roxo"},
        }
        self.path.write_text(json.dumps(original), encoding="utf-8")
        store = playlists.PlaylistStore(path=self.path)
        store.create("Nova")
        dados = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(dados["toque_personalizado"], {"cor": "roxo"})

    def test_unknown_playlist_fields_are_preserved(self) -> None:
        original = {
            "version": playlists.PLAYLISTS_VERSION,
            "playlists": [
                {
                    "id": "favoritas",
                    "name": "Favoritas",
                    "game_ids": ["a"],
                    "created_at": 10,
                    "updated_at": 20,
                    "cor_destaque": "verde",
                }
            ],
            "used_ids": ["favoritas"],
            "counter": 0,
        }
        self.path.write_text(json.dumps(original), encoding="utf-8")
        store = playlists.PlaylistStore(path=self.path)
        playlist = store.get("favoritas")
        self.assertEqual(playlist.extra, {"cor_destaque": "verde"})
        self.assertEqual(playlist.game_ids, ["a"])
        store.rename("favoritas", "Renomeada")
        dados = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(
            dados["playlists"][0]["cor_destaque"], "verde"
        )
        self.assertEqual(dados["playlists"][0]["name"], "Renomeada")

    def test_corrupt_file_yields_empty_store_and_is_quarantined(self) -> None:
        self.path.write_text("{ isto não é json", encoding="utf-8")
        store = playlists.PlaylistStore(path=self.path)
        self.assertEqual(store.playlists, ())
        # A leitura de novo continua igual: o arquivo não foi tocado.
        self.assertIn("isto não é json", self.path.read_text(encoding="utf-8"))

        store.create("Nova")
        self.assertTrue(self.path.is_file())
        corrupto = self.directory / "playlists.json.corrupt"
        self.assertTrue(corrupto.is_file())
        self.assertIn("isto não é json", corrupto.read_text(encoding="utf-8"))
        dados = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(dados["playlists"][0]["name"], "Nova")

    def test_corrupt_file_quarantine_never_overwrites_an_old_quarantine(self) -> None:
        self.path.write_text("{ ruim 1", encoding="utf-8")
        store = playlists.PlaylistStore(path=self.path)
        store.create("Nova")
        self.assertTrue((self.directory / "playlists.json.corrupt").is_file())

        self.path.write_text("{ ruim 2", encoding="utf-8")
        outra = playlists.PlaylistStore(path=self.path)
        outra.create("Outra")
        guardado = (self.directory / "playlists.json.corrupt2").read_text(
            encoding="utf-8"
        )
        self.assertIn("ruim 2", guardado)

    def test_missing_file_starts_empty(self) -> None:
        store = playlists.PlaylistStore(path=self.directory / "ausente.json")
        self.assertEqual(store.playlists, ())
        self.assertEqual(os.listdir(self.directory), [])


if __name__ == "__main__":
    unittest.main()
