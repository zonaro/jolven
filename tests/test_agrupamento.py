import unittest
from types import SimpleNamespace

from cartridges.utils import agrupamento


def make_game(name, game_id=None, base_source="", **overrides):
    data = {
        "name": name,
        "game_id": game_id or f"id_{name}",
        "removed": False,
        "blacklisted": False,
        "hidden": False,
        "is_launcher": False,
        "last_played": 0,
        "added": 0,
        "base_source": base_source,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class FakeStore:
    def __init__(self, games):
        self.games = games
        self.revision = 0
        self.iters = 0

    def __iter__(self):
        self.iters += 1
        return iter(self.games)


class BaseAgrupamento:
    """Preparação comum: schema ligado, preferências vazias e store falsa."""

    def setUp(self):
        import cartridges.utils.agrupamento as ag
        from cartridges import shared

        self.ag = ag
        self._old_store = getattr(shared, "store", None)
        self._old_schema = getattr(shared, "schema", None)
        shared.schema = SimpleNamespace(get_boolean=lambda _k: True)
        ag._prefs = {"preferidos": {}, "desagrupados": []}
        ag.limpar_indice()

    def tearDown(self):
        from cartridges import shared

        if self._old_store is None:
            try:
                delattr(shared, "store")
            except AttributeError:
                pass
        else:
            shared.store = self._old_store
        if self._old_schema is None:
            try:
                delattr(shared, "schema")
            except AttributeError:
                pass
        else:
            shared.schema = self._old_schema
        self.ag._prefs = None
        self.ag.limpar_indice()

    def _use(self, games):
        from cartridges import shared

        shared.store = FakeStore(games)
        return shared.store


class AgrupamentoIndexTests(BaseAgrupamento, unittest.TestCase):
    def test_same_name_groups(self):
        games = [make_game("Hollow Knight", "a"), make_game("Hollow Knight", "b")]
        self._use(games)
        members = self.ag.membros(games[0])
        self.assertEqual({g.game_id for g in members}, {"a", "b"})

    def test_ineligible_are_alone(self):
        games = [make_game("Doom", "a"), make_game("Doom", "b", hidden=True)]
        self._use(games)
        self.assertEqual(self.ag.membros(games[1]), [games[1]])

    def test_desagrupada_stays_alone(self):
        games = [make_game("Celeste", "a"), make_game("Celeste", "b")]
        store = self._use(games)
        chave = self.ag.atualizar(games[0])
        self.ag._carregar()["desagrupados"].append(chave)
        self.ag.limpar_indice()
        self.assertEqual(self.ag.membros(games[0]), [games[0]])
        self.assertGreaterEqual(store.iters, 0)

    def test_reagrupar_chave_devolve_os_membros(self):
        games = [make_game("Celeste", "a"), make_game("Celeste", "b")]
        self._use(games)
        chave = self.ag.atualizar(games[0])
        self.ag.desagrupar_chave(chave)
        self.assertEqual(self.ag.membros(games[0]), [games[0]])

        self.ag.reagrupar_chave(chave)

        self.assertFalse(self.ag.desagrupada(chave))
        self.assertEqual(
            {g.game_id for g in self.ag.membros(games[0])}, {"a", "b"}
        )

    def test_reagrupar_chave_ausente_nao_muda_nada(self):
        games = [make_game("Celeste", "a"), make_game("Celeste", "b")]
        self._use(games)
        chave = self.ag.atualizar(games[0])
        self.ag.reagrupar_chave(chave)
        self.assertEqual(self.ag._carregar()["desagrupados"], [])
        self.assertEqual(len(self.ag.membros(games[0])), 2)

    def test_n_lookups_scan_once(self):
        games = [make_game(f"Game {i}", f"g{i}") for i in range(30)]
        store = self._use(games)
        for game in games:
            self.ag.membros(game)
        self.assertLessEqual(store.iters, 2)

    def test_revision_bump_rescans(self):
        games = [make_game("It Takes Two", "a")]
        store = self._use(games)
        self.ag.membros(games[0])
        first = store.iters
        games.append(make_game("It Takes Two", "b"))
        store.revision += 1
        members = self.ag.membros(games[0])
        self.assertEqual({g.game_id for g in members}, {"a", "b"})
        self.assertGreater(store.iters, first)

    def test_rename_invalidates(self):
        games = [make_game("Hades", "a"), make_game("Hades", "b")]
        store = self._use(games)
        self.assertEqual(len(self.ag.membros(games[0])), 2)
        scans = store.iters
        games[1].name = "Hades II"
        self.ag.atualizar(games[1])
        members = self.ag.membros(games[0])
        self.assertEqual(members, [games[0]])
        self.assertGreater(store.iters, scans)


class LinhaProdutoTests(BaseAgrupamento, unittest.TestCase):
    def test_doom_1993_e_doom_2016_nao_se_agrupam(self):
        classico = make_game("Doom", "classico", base_source="uzdoom")
        relancamento = make_game("Doom", "steam", base_source="steam")
        self._use([classico, relancamento])
        self.assertEqual(self.ag.membros(classico), [classico])
        self.assertEqual(self.ag.membros(relancamento), [relancamento])

    def test_steam_e_xcloud_se_agrupam(self):
        steam = make_game("Doom", "steam", base_source="steam")
        xcloud = make_game("Doom", "xcloud", base_source="xcloud")
        self._use([steam, xcloud])
        members = self.ag.membros(steam)
        self.assertEqual({g.game_id for g in members}, {"steam", "xcloud"})

    def test_duas_copias_do_uzdoom_se_agrupam(self):
        primeira = make_game("Doom", "a", base_source="uzdoom")
        segunda = make_game("Doom", "b", base_source="uzdoom")
        self._use([primeira, segunda])
        members = self.ag.membros(primeira)
        self.assertEqual({g.game_id for g in members}, {"a", "b"})

    def test_chave_sem_linha_permanece_igual(self):
        self.assertEqual(self.ag.chave_para("Doom"), "||doom")
        self.assertNotEqual(
            self.ag.chave_para("Doom", "motor"),
            self.ag.chave_para("Doom"),
        )

    def test_sem_fonte_agrupa_por_nome(self):
        sem_fonte = make_game("Doom", "a")
        del sem_fonte.base_source
        outro = make_game("Doom", "b")
        del outro.base_source
        self._use([sem_fonte, outro])
        members = self.ag.membros(sem_fonte)
        self.assertEqual({g.game_id for g in members}, {"a", "b"})

    def test_linha_vem_do_source_quando_falta_base_source(self):
        jogo = make_game("Doom", "a", source="uzdoom_iwad")
        del jogo.base_source
        self.assertEqual(self.ag.linha_de(jogo), "motor")
        self.assertEqual(self.ag.linha_de(make_game("Doom", "b")), "")


if __name__ == "__main__":
    unittest.main()
