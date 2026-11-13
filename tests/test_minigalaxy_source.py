"""Testes puros para a Source do Minigalaxy (issue #158).

O módulo sob teste fica atrás de imports do GTK/GSettings (``cartridges.game``,
``cartridges.shared``) que não existem em uma árvore nua, então as duas
dependências são stubadas em ``sys.modules`` antes do import — exatamente as
partes que o código exercitado só toca por meio de ``Game(values)`` e
``shared.import_time``/``shared.schema``/``shared.flatpak_dir``/``shared.config_dir``.
Tudo aqui roda sem display, sem GTK, sem GSettings e sem subprocesso.
"""

import builtins
import json
import sys
import tempfile
import unittest
from pathlib import Path

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]


class _StubSchema:
    def __init__(self):
        self.strings = {}
        self.booleans = {}

    def get_string(self, key):
        return self.strings.get(key, "")

    def get_boolean(self, key):
        return self.booleans.get(key, False)

    def set_string(self, key, value):
        self.strings[key] = value


class _StubShared:
    def __init__(self):
        self.schema = _StubSchema()
        self.import_time = 1234567890
        # Ponteiros que não existem: uma fonte só é resolvível quando o teste
        # escanear explicitamente o diretório de configuração.
        self.flatpak_dir = Path("/nonexistent/jolven-flatpak")
        self.config_dir = Path("/nonexistent/jolven-config")
        self.host_config_dir = Path("/nonexistent/jolven-host-config")
        self.host_data_dir = Path("/nonexistent/jolven-host-data")
        self.host_cache_dir = Path("/nonexistent/jolven-host-cache")


class _StubGame:
    """Registra o values de ``Game(values)`` como atributos.

    Também carrega os campos com default do modelo que as fontes usam
    (``game_mode_use_gamemode`` e afins) para que os testes possam
    consultar o estado resultante.
    """

    def __init__(self, values):
        self.values = dict(values)
        self.controller_support = None
        self.game_mode_use_gamemode = None
        self.game_mode_use_mangohud = None
        self.launch_environment = {}
        self.launch_working_directory = ""
        # os valores da fonte ganham dos padrões do modelo
        for key, value in values.items():
            setattr(self, key, value)


_STUB_SHARED = _StubShared()
_STUB_GAME_MODULE = type("game", (), {"Game": _StubGame})

import cartridges  # noqa: E402

# O pacote é um namespace (sem __init__.py): os submódulos aparecem como
# atributos apenas depois de importados. Guarde o estado anterior para
# devolvê-lo mesmo quando o módulo real nunca chegou a ``sys.modules`` —
# sem isso, os apontadores stub vazariam para os testes seguintes.
_prior_package_attrs = {
    _name: hasattr(cartridges, _name) for _name in ("shared", "game")
}
_prior_attr_values = {
    _name: getattr(cartridges, _name, None) for _name in ("shared", "game")
}

_STUBBED_MODULES = (
    "cartridges.shared",
    "cartridges.game",
    "cartridges.importer.minigalaxy_source",
)
_originals = {name: sys.modules.pop(name, None) for name in _STUBBED_MODULES}

sys.modules["cartridges.shared"] = _STUB_SHARED
sys.modules["cartridges.game"] = _STUB_GAME_MODULE
cartridges.shared = _STUB_SHARED
cartridges.game = _STUB_GAME_MODULE

from cartridges.importer import minigalaxy_source  # noqa: E402
from cartridges.importer.location import UnresolvableLocationError  # noqa: E402
from cartridges.importer.minigalaxy_source import (  # noqa: E402
    MinigalaxySource,
    MinigalaxySourceIterable,
)
from cartridges.importer import minigalaxy  # noqa: E402

for _name, _module in _originals.items():
    if _module is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _module
for _name in ("shared", "game"):
    if _prior_package_attrs[_name]:
        setattr(cartridges, _name, _prior_attr_values[_name])
    else:
        try:
            delattr(cartridges, _name)
        except AttributeError:
            pass

# As instâncias stub continuam referenciadas pelos módulos importados; os
# testes trocam os apontadores para pastas temporárias.
_shared_stub = minigalaxy_source.shared

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "minigalaxy"


class MinigalaxySourceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self._restore_ = (
            _shared_stub.flatpak_dir,
            _shared_stub.config_dir,
            _shared_stub.host_config_dir,
            _shared_stub.host_data_dir,
            _shared_stub.host_cache_dir,
        )
        self.addCleanup(self._restore_shared)
        _shared_stub.flatpak_dir = self.tmp / "flatpak"
        _shared_stub.config_dir = self.tmp / "config"
        _shared_stub.host_config_dir = self.tmp / "host-config"
        _shared_stub.host_data_dir = self.tmp / "host-data"
        _shared_stub.host_cache_dir = self.tmp / "host-cache"

        self.schema = _shared_stub.schema
        self._old_schema = dict(self.schema.strings)
        self._old_booleans = dict(self.schema.booleans)
        self.addCleanup(self._restore_schema)
        self.schema.strings.clear()
        self.schema.booleans.clear()

        # A detecção de launcher consulta o PATH do host; os testes fixam os
        # programas como presentes para mapear o launcher de forma determinística.
        self._old_programs = minigalaxy_source._available_programs
        self.addCleanup(setattr, minigalaxy_source, "_available_programs", self._old_programs)
        minigalaxy_source._available_programs = lambda: ("wine", "dosbox", "scummvm")

    def _restore_shared(self):
        (
            _shared_stub.flatpak_dir,
            _shared_stub.config_dir,
            _shared_stub.host_config_dir,
            _shared_stub.host_data_dir,
            _shared_stub.host_cache_dir,
        ) = self._restore_

    def _restore_schema(self):
        self.schema.strings.clear()
        self.schema.strings.update(self._old_schema)
        self.schema.booleans.clear()
        self.schema.booleans.update(self._old_booleans)

    def make_native(self, **preferences_by_game) -> Path:
        """Cópia da fixture nativa com preferências opcionais sobrescritas."""

        native_install = self.tmp / "install"
        self.tmp.mkdir(exist_ok=True)
        (self.tmp / "config" / "minigalaxy" / "games").mkdir(parents=True)
        install_copy = self.tmp / "install"

        import shutil

        shutil.copytree(FIXTURE_ROOT / "native" / "install", install_copy)
        config = self.tmp / "config" / "minigalaxy" / "config.json"
        config.write_text(
            json.dumps(
                {
                    "install_dir": str(install_copy),
                    "refresh_token": "TOKEN-FICTICIO-TESTE",
                    "username": "jogador",
                }
            ),
            encoding="utf-8",
        )
        games_dir = self.tmp / "config" / "minigalaxy" / "games"
        for name, values in preferences_by_game.items():
            (games_dir / f"{name}.json").write_text(
                json.dumps(values), encoding="utf-8"
            )
        return install_copy

    def source(self) -> MinigalaxySource:
        return MinigalaxySource()

    def games(self, source: MinigalaxySource | None = None):
        source = source or self.source()
        return list(iter(source))

    def use_default_library(self) -> Path:
        """Cria a biblioteca padrão temporária e aponta o padrão para ela.

        O ``default_install_dir`` real usa ``Path.home()``, que pertence ao
        usuário: o teste fixa o padrão em uma pasta temporária com a fixture
        nativa copiada, e o teste de candidatos puros consulta o caminho sem
        resolver nada.
        """

        import shutil

        default_dir = self.tmp / "GOG Games"
        shutil.copytree(FIXTURE_ROOT / "native" / "install", default_dir)
        original = minigalaxy_source.default_install_dir
        minigalaxy_source.default_install_dir = lambda: default_dir
        self.addCleanup(
            setattr, minigalaxy_source, "default_install_dir", original
        )
        return default_dir

    def write_config(self, raw: str) -> Path:
        """Escreve um ``config.json`` nativo com conteúdo arbitrário."""

        config_dir = self.tmp / "config" / "minigalaxy"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "games").mkdir(exist_ok=True)
        config = config_dir / "config.json"
        config.write_text(raw, encoding="utf-8")
        return config


class SourceMetadataTests(MinigalaxySourceTestCase):
    def test_source_metadata(self) -> None:
        source = self.source()
        self.assertEqual(source.source_id, "minigalaxy")
        self.assertEqual(source.name, "Minigalaxy")
        self.assertEqual(source.available_on, {"linux"})
        self.assertIs(source.iterable_class, MinigalaxySourceIterable)

    def test_the_source_has_config_and_install_locations(self) -> None:
        source = self.source()
        self.assertEqual(list(source.locations._asdict()), ["config", "install"])

    def test_the_flatpak_config_candidate_is_present_and_last(self) -> None:
        """A ordem dos clientes é determinística: nativo, host e Flatpak."""

        source = self.source()
        self.assertEqual(
            list(source.locations.config.candidates),
            [
                _shared_stub.config_dir / "minigalaxy",
                _shared_stub.host_config_dir / "minigalaxy",
                _shared_stub.flatpak_dir
                / "io.github.sharkwouter.Minigalaxy"
                / "config"
                / "minigalaxy",
            ],
        )


class IterationTests(MinigalaxySourceTestCase):
    def test_native_games_are_imported_with_stable_ids(self) -> None:
        install = self.make_native()
        import shlex

        games, additional = zip(*self.games())
        by_name = {
            game.values["name"]: (game, data)
            for game, data in zip(games, additional)
        }

        self.assertIn("Beneath a Steel Sky", by_name)
        game, extra = by_name["Beneath a Steel Sky"]
        self.assertEqual(game.values["source"], "minigalaxy")
        self.assertEqual(game.values["game_id"], "minigalaxy_1207658691")
        self.assertEqual(game.values["added"], 1234567890)
        self.assertEqual(
            shlex.split(game.values["executable"]),
            [str(install / "Beneath a Steel Sky" / "start.sh")],
        )
        self.assertEqual(
            game.launch_working_directory, str(install / "Beneath a Steel Sky")
        )
        self.assertEqual(extra["external_ids"], {"gog": "1207658691"})
        self.assertTrue(str(extra["local_image_path"]).endswith("thumbnail.jpg"))

    def test_sem_identificador_gets_a_deterministic_fallback(self) -> None:
        self.make_native()
        games = [game for game, _ in self.games()]
        by_id = {game.values["game_id"]: game for game in games}
        self.assertIn("minigalaxy_local_sem-identificador", by_id)
        self.assertIn("minigalaxy_local_sem-linha-de-id", by_id)

    def test_dosbox_and_scummvm_launchers_are_mapped(self) -> None:
        self.make_native()
        games = {
            game.values["name"]: game for game, _ in self.games()
        }
        self.assertIn("dosbox", games["Duke Nukem 3D"].values["executable"])
        self.assertIn("scummvm", games["Broken Sword"].values["executable"])

    def test_minigalaxy_preferences_do_not_reach_the_game(self) -> None:
        """Um jogo sem preferências não ganha GameMode forçado pelo Jolven."""

        self.make_native()
        games = {
            game.values["name"]: game for game, _ in self.games()
        }
        self.assertIsNone(games["Beneath a Steel Sky"].game_mode_use_gamemode)
        self.assertIsNone(games["Beneath a Steel Sky"].game_mode_use_mangohud)

    def test_minigalaxy_preferences_reach_the_game(self) -> None:
        self.make_native(
            **{
                "Beneath a Steel Sky": {
                    "use_gamemode": True,
                    "use_mangohud": True,
                    "show_fps": True,
                    "hide_game": True,
                }
            }
        )
        games = {
            game.values["name"]: game for game, _ in self.games()
        }
        game = games["Beneath a Steel Sky"]
        self.assertTrue(game.game_mode_use_gamemode)
        self.assertTrue(game.game_mode_use_mangohud)
        self.assertEqual(game.values["hidden"], True)
        self.assertEqual(
            game.launch_environment["__GL_SHOW_GRAPHICS_OSD"], "1"
        )

    def test_an_incomplete_scan_withholds_the_source(self) -> None:
        self.make_native()

        def fake_scan(*_args, **_kwargs):
            return minigalaxy.MinigalaxyScan(
                install_dir=Path("/nonexistent"),
                games=(),
                failures=(),
                complete=False,
                reason="pasta de instalação indisponível",
            )

        original = minigalaxy_source.scan_install_dir
        minigalaxy_source.scan_install_dir = fake_scan
        self.addCleanup(setattr, minigalaxy_source, "scan_install_dir", original)
        with self.assertRaises(minigalaxy_source.SourceScanError):
            list(iter(self.source()))


class WineIterationTests(MinigalaxySourceTestCase):
    def _copy_wine(self) -> Path:
        import shutil

        install = self.tmp / "wine-install"
        shutil.copytree(FIXTURE_ROOT / "wine" / "install", install)
        config_dir = self.tmp / "config" / "minigalaxy"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "games").mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text(
            json.dumps({"install_dir": str(install), "refresh_token": "TOKEN-FICTICIO"}),
            encoding="utf-8",
        )
        return install

    def test_wine_game_uses_the_goggame_primary_task(self) -> None:
        self._copy_wine()
        games = {
            game.values["name"]: game for game, _ in self.games()
        }
        game = games["Disco Elysium"]
        self.assertEqual(game.values["game_id"], "minigalaxy_1423049311")
        executable = game.values["executable"]
        self.assertIn("start /b /wait", executable)
        self.assertIn("c:\\game\\game/bin", executable)
        self.assertIn("Disco Elysium.exe", executable)
        self.assertEqual(
            game.launch_environment["WINEPREFIX"],
            str(self.tmp / "wine-install" / "Disco Elysium" / "prefix"),
        )
        self.assertEqual(
            game.launch_working_directory,
            str(self.tmp / "wine-install" / "Disco Elysium"),
        )

    def test_partial_installation_is_skipped(self) -> None:
        self._copy_wine()
        names = {game.values["name"] for game, _ in self.games()}
        self.assertNotIn("Instalacao Parcial", names)


class ConfigResilienceTests(MinigalaxySourceTestCase):
    """Config ausente, truncado ou ilegível nunca pode quebrar nem podar."""

    def test_the_pure_candidates_point_at_gog_games(self) -> None:
        """Sem config resolvível, os candidatos são o padrão ``~/GOG Games``."""

        source = self.source()  # nenhum candidato de config existe
        self.assertEqual(
            tuple(
                minigalaxy_source._install_candidates(
                    source.locations.config
                )
            ),
            (Path.home() / "GOG Games",),
        )

    def test_a_config_without_install_dir_uses_the_default_library(
        self,
    ) -> None:
        default_dir = self.use_default_library()
        self.write_config("{}")
        source = self.source()
        games = [game for game, _ in self.games(source)]
        self.assertEqual(source.locations.install.root, default_dir)
        self.assertIn(
            "minigalaxy_1207658691",
            {game.values["game_id"] for game in games},
        )

    def test_a_truncated_or_invalid_config_falls_back_to_the_default(
        self,
    ) -> None:
        default_dir = self.use_default_library()
        config = self.write_config("placeholder")
        for raw in ('{"install_dir": "/tmp/trunc', '{"install_dir": 123}', "[]"):
            with self.subTest(raw=raw):
                config.write_text(raw, encoding="utf-8")
                source = self.source()
                games = [game for game, _ in self.games(source)]
                self.assertEqual(source.locations.install.root, default_dir)
                self.assertTrue(games)

    def test_an_unreadable_config_withholds_the_source(self) -> None:
        """Sem leitura do config.json, a fonte fica retida e a poda não roda."""

        import os

        self.use_default_library()
        config = self.write_config("{}")
        os.chmod(config, 0o000)
        self.addCleanup(os.chmod, config, 0o644)
        with self.assertRaises(minigalaxy_source.SourceScanError):
            list(iter(self.source()))

    def test_an_unreadable_config_directory_is_not_iterable(self) -> None:
        """Pasta de config ilegível: a fonte não é iterável (poda retida)."""

        import os

        self.use_default_library()
        config_dir = self.tmp / "config" / "minigalaxy"
        self.write_config("{}")
        os.chmod(config_dir, 0o000)
        self.addCleanup(os.chmod, config_dir, 0o755)
        with self.assertRaises(UnresolvableLocationError):
            list(iter(self.source()))


class PathSafetyTests(MinigalaxySourceTestCase):
    """O ``install_dir`` derivado nunca vira varredura fora do domínio."""

    def test_a_relative_escape_install_dir_falls_back_to_the_default(
        self,
    ) -> None:
        default_dir = self.use_default_library()
        self.write_config('{"install_dir": "../../.."}')
        source = self.source()
        games = [game for game, _ in self.games(source)]
        self.assertEqual(source.locations.install.root, default_dir)
        self.assertTrue(games)

    def test_the_home_directory_is_never_used_as_install_root(self) -> None:
        default_dir = self.use_default_library()
        for raw in ('{"install_dir": "~"}', '{"install_dir": "~/"}'):
            with self.subTest(raw=raw):
                self.write_config(raw)
                source = self.source()
                self.games(source)
                self.assertEqual(source.locations.install.root, default_dir)
                self.assertNotEqual(
                    source.locations.install.root, Path.home()
                )

    def test_an_absolute_system_path_is_enumerated_one_level_only(
        self,
    ) -> None:
        """Um caminho absoluto alheio é usado só como diretório de um nível."""

        self.write_config('{"install_dir": "/etc"}')
        source = self.source()
        games = [game for game, _ in self.games(source)]
        self.assertEqual(source.locations.install.root, Path("/etc"))
        self.assertEqual(games, [])

    def test_an_install_dir_pointing_to_a_file_falls_back_to_the_default(
        self,
    ) -> None:
        default_dir = self.use_default_library()
        config = self.write_config("{}")
        self.write_config(json.dumps({"install_dir": str(config)}))
        source = self.source()
        games = [game for game, _ in self.games(source)]
        self.assertEqual(source.locations.install.root, default_dir)
        self.assertTrue(games)


class DeterministicClientTests(MinigalaxySourceTestCase):
    """Dois clientes presentes nunca são misturados: o primeiro vence."""

    def test_two_config_candidates_are_not_merged(self) -> None:
        native_install = self.make_native()
        flatpak_config = (
            _shared_stub.flatpak_dir
            / "io.github.sharkwouter.Minigalaxy"
            / "config"
            / "minigalaxy"
        )
        flatpak_config.mkdir(parents=True, exist_ok=True)
        (flatpak_config / "games").mkdir()
        other_install = self.tmp / "flatpak-install"
        other_install.mkdir()
        (flatpak_config / "config.json").write_text(
            json.dumps({"install_dir": str(other_install)}),
            encoding="utf-8",
        )

        source = self.source()
        games = [game for game, _ in self.games(source)]
        self.assertEqual(
            source.locations.config.root, self.tmp / "config" / "minigalaxy"
        )
        self.assertEqual(source.locations.install.root, native_install)
        self.assertTrue(games)
        for game in games:
            self.assertTrue(
                str(game.launch_working_directory).startswith(
                    str(native_install)
                )
            )


if __name__ == "__main__":
    unittest.main()
