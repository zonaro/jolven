"""Tests for Steam owned-but-never-installed discovery (follow-up to #44).

Drives `SteamSourceIterable` against fake Steam trees (manifests +
librarycache) with the bulk store lookup mocked: no display, no network
and no real Steam install needed. `cartridges.shared` and
`cartridges.game` are stubbed in `sys.modules` before import — the same
approach as `test_shortcuts_source.py` — because the real ones pull the
GTK widget chain, which only exists once the app is built.
"""

import builtins
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from requests.exceptions import RequestException

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]


class _StubGame:
    """Stands in for `Game`: records the values dict it was built with."""

    def __init__(self, values):
        self.values = dict(values)
        for key, value in values.items():
            setattr(self, key, value)


_stub_shared = SimpleNamespace(import_time=1234567890, store=None)

_added_stubs = []
for _mod_name, _stub in (
    ("cartridges.shared", _stub_shared),
    ("cartridges.game", type("game", (), {"Game": _StubGame})),
):
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = _stub
        _added_stubs.append(_mod_name)

from cartridges.importer import steam_source as _steam_source  # noqa: E402
from cartridges.importer.steam_source import SteamSourceIterable  # noqa: E402

for _mod_name in _added_stubs:
    del sys.modules[_mod_name]


class _FakeStore:
    """Minimal `shared.store`: only what the iterable reads (`get`)."""

    def __init__(self, games):
        self._games = {game.game_id: game for game in games}

    def get(self, game_id, default=None):
        return self._games.get(game_id, default)


def _write_libraryfolders(root: Path, steamapps_dirs: list[Path]) -> Path:
    entries = "".join(f'\t"path"\t\t"{directory}"\n' for directory in steamapps_dirs)
    vdf = root / "libraryfolders.vdf"
    vdf.write_text(f'"libraryfolders"\n{{\n{entries}}}\n', encoding="utf-8")
    return vdf


def _write_manifest(steamapps: Path, appid: str, name: str, stateflags: str = "4") -> Path:
    manifest = steamapps / f"appmanifest_{appid}.acf"
    manifest.write_text(
        f'"AppState"\n{{\n'
        f'\t"appid"\t\t"{appid}"\n'
        f'\t"name"\t\t"{name}"\n'
        f'\t"StateFlags"\t\t"{stateflags}"\n'
        f"}}\n",
        encoding="utf-8",
    )
    return manifest


def _make_source(libraryfolders_vdf: Path, librarycache: Path) -> SimpleNamespace:
    return SimpleNamespace(
        source_id="steam",
        game_id_format="steam_{game_id}",
        make_executable=lambda game_id: f"xdg-open steam://rungameid/{game_id}",
        locations=SimpleNamespace(
            data={
                "libraryfolders.vdf": libraryfolders_vdf,
                "librarycache": librarycache,
            }
        ),
    )


class SteamOwnedTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.steamapps = self.root / "steamapps"
        self.steamapps.mkdir(parents=True)
        self.librarycache = self.root / "librarycache"
        self.librarycache.mkdir(parents=True)
        self.vdf = _write_libraryfolders(self.root, [self.root])
        _stub_shared.store = None

    def tearDown(self):
        _stub_shared.store = None

    def _drive(self, bulk_result=None, bulk_error=None):
        source = _make_source(self.vdf, self.librarycache)
        iterable = SteamSourceIterable(source)
        with (
            # Force the import-time stub even when the suite already pulled
            # the real `cartridges.shared` into sys.modules first; without
            # this the store below is never the one the iterable reads.
            mock.patch.object(_steam_source, "shared", _stub_shared),
            mock.patch.object(_steam_source, "SteamAPIHelper") as api_cls,
            mock.patch.object(_steam_source, "SteamRateLimiter"),
        ):
            helper = api_cls.return_value
            if bulk_error is not None:
                helper.get_store_basic_info_bulk.side_effect = bulk_error
            else:
                helper.get_store_basic_info_bulk.return_value = bulk_result or {}
            results = list(iterable)
        return results, helper.get_store_basic_info_bulk

    def test_owned_without_manifest_enters_uninstalled(self):
        (self.librarycache / "620").mkdir()
        (self.librarycache / "620" / "library_600x900.jpg").write_bytes(b"fake")
        (self.librarycache / "temp").mkdir()  # non-numeric dir is ignored
        (self.librarycache / "123").write_text("not a dir")  # file is ignored

        results, bulk = self._drive(
            bulk_result={"620": {"name": "Portal 2", "type": "game"}}
        )

        self.assertEqual(len(results), 1)
        game, additional = results[0]
        self.assertEqual(game.values["game_id"], "steam_620")
        self.assertEqual(game.values["name"], "Portal 2")
        self.assertFalse(game.values["installed"])
        self.assertEqual(game.values["executable"], "xdg-open steam://rungameid/620")
        self.assertEqual(
            game.values["install_executable"], "xdg-open steam://install/620"
        )
        self.assertEqual(additional["steam_appid"], "620")
        self.assertEqual(
            additional["local_image_path"],
            self.librarycache / "620" / "library_600x900.jpg",
        )
        bulk.assert_called_once_with(["620"])

    def test_installed_games_unchanged_without_duplicates(self):
        _write_manifest(self.steamapps, "440", "Team Fortress 2", "4")
        for appid in ("440", "570", "999", "1000", "1001"):
            (self.librarycache / appid).mkdir()
        _stub_shared.store = _FakeStore(
            [SimpleNamespace(game_id="steam_570", name="Dota 2", removed=False)]
        )

        results, bulk = self._drive(
            bulk_result={
                "570": {"name": "Must not be used", "type": "game"},
                "999": {"name": "Some DLC", "type": "dlc"},
                "1000": {"name": "   ", "type": "game"},
            }
        )

        by_id = {
            game.values["game_id"]: (game, additional)
            for game, additional in results
        }
        # The manifest appid is not re-resolved, non-games and nameless
        # entries are dropped, unknown appids resolve to nothing.
        self.assertEqual(set(by_id), {"steam_440", "steam_570"})

        # Installed manifest untouched: real installed flag, no install URI.
        installed, _ = by_id["steam_440"]
        self.assertEqual(installed.values["name"], "Team Fortress 2")
        self.assertTrue(installed.values["installed"])
        self.assertEqual(installed.values["install_executable"], "")

        # Owned via the recorded name, still uninstalled with an install URI.
        owned, _ = by_id["steam_570"]
        self.assertEqual(owned.values["name"], "Dota 2")
        self.assertFalse(owned.values["installed"])
        self.assertEqual(
            owned.values["install_executable"], "xdg-open steam://install/570"
        )
        bulk.assert_called_once_with(["1000", "1001", "999"])

    def test_bulk_failure_skips_owned_step(self):
        _write_manifest(self.steamapps, "440", "Team Fortress 2", "4")
        (self.librarycache / "570").mkdir()

        results, _ = self._drive(bulk_error=RequestException("boom"))

        self.assertEqual(len(results), 1)
        game, _ = results[0]
        self.assertEqual(game.values["game_id"], "steam_440")


if __name__ == "__main__":
    unittest.main()
