"""Pure-python tests for the Quiver Launcher source.

The module under test lives behind Gtk/GSettings imports (`cartridges.game`,
`cartridges.shared`) that do not exist in a bare source tree, so those two
dependencies are stubbed in `sys.modules` before import — exactly the parts
the exercised code only touches through `Game(values)` and
`shared.import_time`/`shared.schema`/`shared.home`/`shared.flatpak_dir`.
Everything asserted here (library parsing, id stability, executable
resolution, runner expansion, cover validation) runs with no display, no GTK
and no GSettings database, and without touching the network.
"""

import builtins
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from shlex import quote as shell_quote
from typing import Optional
from unittest.mock import patch

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
        # Pointers that do not exist, so a source is only resolvable when a
        # test explicitly places a library inside one of them.
        self.home = Path("/nonexistent/jolven-home")
        self.flatpak_dir = Path("/nonexistent/jolven-flatpak")


class _StubGame:
    """Records the values dict like `Game.update_values` would."""

    def __init__(self, values):
        self.values = dict(values)
        for key, value in values.items():
            setattr(self, key, value)


_STUB_SHARED = _StubShared()
_STUB_GAME_MODULE = type("game", (), {"Game": _StubGame})

# The stubs must win over the real modules even when another test module
# already imported them: `from cartridges import shared` resolves the
# attribute of the package first, and the location/source modules bind
# `shared` at import time. So the stubs are installed, the modules that
# bind them are re-imported, and the environment is restored afterwards.
import cartridges  # noqa: E402

_STUBBED_MODULES = (
    "cartridges.shared",
    "cartridges.game",
    "cartridges.importer.location",
    "cartridges.importer.source",
)
_originals = {name: sys.modules.pop(name, None) for name in _STUBBED_MODULES}

sys.modules["cartridges.shared"] = _STUB_SHARED
sys.modules["cartridges.game"] = _STUB_GAME_MODULE
setattr(cartridges, "shared", _STUB_SHARED)
setattr(cartridges, "game", _STUB_GAME_MODULE)

from cartridges.importer import quiver_source  # noqa: E402
from cartridges.importer.location import UnresolvableLocationError  # noqa: E402
from cartridges.importer.quiver_source import (  # noqa: E402
    QuiverSource,
    QuiverSourceIterable,
)
from cartridges.importer.source import SourceScanError  # noqa: E402
from cartridges.utils.quiver_catalog import QuiverEnrichment  # noqa: E402

for _name, _module in _originals.items():
    if _module is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _module
if _originals["cartridges.shared"] is not None:
    setattr(cartridges, "shared", _originals["cartridges.shared"])
if _originals["cartridges.game"] is not None:
    setattr(cartridges, "game", _originals["cartridges.game"])

# The stub instances are still referenced by the imported modules, so the
# tests can retarget the candidate roots.
_shared_stub = quiver_source.shared


class QuiverSourceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self._old_shared = (
            _shared_stub.home,
            _shared_stub.flatpak_dir,
        )
        self.addCleanup(self._restore_shared)
        _shared_stub.home = self.tmp / "home"
        _shared_stub.flatpak_dir = self.tmp / "flatpak"
        # The XDG variable wins over the home folder in the candidate list,
        # so it is pointed at a folder that does not exist.
        self._old_xdg = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_DATA_HOME"] = str(self.tmp / "xdg-data")
        self.addCleanup(self._restore_xdg)

        # The schema of the stub: the enrichment is on by default, as it is
        # in the real schema, and the catalog itself is replaced below.
        self._old_booleans = dict(_shared_stub.schema.booleans)
        self.addCleanup(self._restore_booleans)
        _shared_stub.schema.booleans.clear()
        _shared_stub.schema.booleans["quiver-enrich"] = True

        # The catalog talks to the network: every test replaces it, so no
        # request ever leaves the machine.
        self.enrich_calls: list[dict] = []
        self.enrich_result = None
        self.enrich_error: Optional[BaseException] = None
        patcher = patch(
            "cartridges.importer.quiver_source.enrich_entry",
            side_effect=self._fake_enrich,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _fake_enrich(self, entry, **_kwargs):
        """Stand-in for the catalog: records the call, answers a fixture."""
        self.enrich_calls.append(entry)
        if self.enrich_error is not None:
            raise self.enrich_error
        return self.enrich_result

    def _restore_booleans(self):
        _shared_stub.schema.booleans.clear()
        _shared_stub.schema.booleans.update(self._old_booleans)

    def _restore_xdg(self):
        if self._old_xdg is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = self._old_xdg

    def _restore_shared(self):
        (
            _shared_stub.home,
            _shared_stub.flatpak_dir,
        ) = self._old_shared

    def make_root(self) -> Path:
        """Create the data root of the launcher and return it."""
        root = _shared_stub.home / ".local" / "share" / "QuiverLauncher"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def write_library(self, root: Path, document) -> None:
        """Write the library file of the launcher."""
        content = document if isinstance(document, str) else json.dumps(document)
        (root / "apps.json").write_text(content, encoding="utf-8")

    def write_settings(self, root: Path, document) -> None:
        """Write the settings file of the launcher."""
        (root / "settings.json").write_text(json.dumps(document), encoding="utf-8")

    def make_program(self, path: Path) -> Path:
        """Write an executable file and return its path."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
        return path


class SourceMetadataTests(QuiverSourceTestCase):
    def test_source_metadata(self):
        self.assertEqual(QuiverSource.source_id, "quiver")
        self.assertEqual(QuiverSource.name, "Quiver")
        self.assertEqual(QuiverSource.available_on, {"linux"})
        self.assertIs(QuiverSource.iterable_class, QuiverSourceIterable)
        self.assertEqual(QuiverSource().locations.data.schema_key, "quiver-location")


class LibraryParsingTests(QuiverSourceTestCase):
    def test_imports_installed_and_not_installed_entries(self):
        root = self.make_root()
        app_dir = root / "Apps" / "MyGame"
        program = self.make_program(app_dir / "MyGame.x86_64")
        (app_dir / "version.txt").write_text("v1.2.3\n", encoding="utf-8")
        self.write_library(
            root,
            {
                "apps": [
                    {
                        "name": "My Game",
                        "project": "Some Studio",
                        "repository": "owner/repo",
                        "folderName": "MyGame",
                    },
                    {
                        "name": "Other Game",
                        "repository": "owner/other",
                        "folderName": "OtherGame",
                    },
                ]
            },
        )

        results = list(QuiverSourceIterable(QuiverSource()))
        self.assertEqual(len(results), 2)

        game, additional = results[0]
        self.assertEqual(game.values["game_id"], "quiver_MyGame")
        self.assertEqual(game.values["name"], "My Game")
        self.assertEqual(game.values["source"], "quiver")
        self.assertEqual(game.values["developer"], "Some Studio")
        self.assertTrue(game.values["installed"])
        self.assertEqual(game.values["executable"], shell_quote(str(program)))
        self.assertEqual(additional["quiver_installed_version"], "v1.2.3")

        other, _additional = results[1]
        self.assertEqual(other.values["game_id"], "quiver_OtherGame")
        self.assertFalse(other.values["installed"])
        self.assertEqual(other.values["executable"], "")

    def test_accepts_a_bare_list(self):
        root = self.make_root()
        self.write_library(root, [{"name": "A", "folderName": "A"}])
        results = list(QuiverSourceIterable(QuiverSource()))
        self.assertEqual([game.values["game_id"] for game, _ in results], ["quiver_A"])

    def test_accepts_the_legacy_sections(self):
        root = self.make_root()
        self.write_library(
            root,
            {
                "standard": [{"name": "A", "folderName": "A"}],
                "experimental": [{"name": "B", "folderName": "B"}],
                "custom": [{"name": "C", "folderName": "C"}],
            },
        )
        results = list(QuiverSourceIterable(QuiverSource()))
        self.assertEqual(
            [game.values["game_id"] for game, _ in results],
            ["quiver_A", "quiver_B", "quiver_C"],
        )

    def test_skips_invalid_entries(self):
        root = self.make_root()
        self.write_library(
            root,
            {
                "apps": [
                    "not an entry",
                    {"folderName": "NoName"},
                    {"name": "Good", "folderName": "Good"},
                ]
            },
        )
        results = list(QuiverSourceIterable(QuiverSource()))
        self.assertEqual(
            [game.values["game_id"] for game, _ in results], ["quiver_Good"]
        )

    def test_skips_duplicated_folder_names(self):
        root = self.make_root()
        self.write_library(
            root,
            {
                "apps": [
                    {"name": "First", "folderName": "Same"},
                    {"name": "Second", "folderName": "Same"},
                ]
            },
        )
        results = list(QuiverSourceIterable(QuiverSource()))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0].values["name"], "First")

    def test_id_falls_back_to_the_repository_and_then_to_the_name(self):
        root = self.make_root()
        self.write_library(
            root,
            {
                "apps": [
                    {"name": "No folder", "repository": "owner/repo"},
                    {"name": "Nothing else"},
                ]
            },
        )
        results = list(QuiverSourceIterable(QuiverSource()))
        self.assertEqual(
            [game.values["game_id"] for game, _ in results],
            ["quiver_owner_repo", "quiver_Nothing-else"],
        )

    def test_an_entry_without_a_folder_is_not_installed(self):
        root = self.make_root()
        # The install root exists, but it is not the folder of an app.
        (root / "Apps").mkdir(parents=True, exist_ok=True)
        self.write_library(root, {"apps": [{"name": "No folder"}]})
        results = list(QuiverSourceIterable(QuiverSource()))
        self.assertEqual(len(results), 1)
        game, _additional = results[0]
        self.assertFalse(game.values["installed"])
        self.assertEqual(game.values["executable"], "")

    def test_corrupt_library_raises_a_scan_error(self):
        root = self.make_root()
        self.write_library(root, "{not json")
        with self.assertRaises(SourceScanError):
            list(QuiverSourceIterable(QuiverSource()))

    def test_unknown_root_raises_a_scan_error(self):
        root = self.make_root()
        self.write_library(root, {"unexpected": []})
        with self.assertRaises(SourceScanError):
            list(QuiverSourceIterable(QuiverSource()))

    def test_absent_launcher_yields_nothing(self):
        # No data root at all: the location cannot be resolved.
        source = QuiverSource()
        with self.assertRaises(UnresolvableLocationError):
            iter(source)
        self.assertEqual(list(QuiverSourceIterable(source)), [])


class InstallFolderTests(QuiverSourceTestCase):
    def test_install_path_overrides_the_app_folder(self):
        root = self.make_root()
        elsewhere = self.tmp / "elsewhere"
        program = self.make_program(elsewhere / "Game.x86_64")
        self.write_library(
            root,
            {
                "apps": [
                    {
                        "name": "Game",
                        "folderName": "Game",
                        "installPath": str(elsewhere),
                    }
                ]
            },
        )
        results = list(QuiverSourceIterable(QuiverSource()))
        self.assertEqual(len(results), 1)
        game, _additional = results[0]
        self.assertTrue(game.values["installed"])
        self.assertEqual(game.values["executable"], shell_quote(str(program)))

    def test_settings_apps_path_overrides_the_install_folder(self):
        root = self.make_root()
        apps_folder = self.tmp / "other-apps"
        program = self.make_program(apps_folder / "Game" / "Game.x86_64")
        self.write_settings(root, {"AppsPath": str(apps_folder)})
        self.write_library(
            root, {"apps": [{"name": "Game", "folderName": "Game"}]}
        )
        results = list(QuiverSourceIterable(QuiverSource()))
        self.assertEqual(len(results), 1)
        game, _additional = results[0]
        self.assertTrue(game.values["installed"])
        self.assertEqual(game.values["executable"], shell_quote(str(program)))

    def test_missing_apps_path_falls_back_to_the_default_folder(self):
        root = self.make_root()
        program = self.make_program(root / "Apps" / "Game" / "Game.x86_64")
        self.write_settings(root, {"AppsPath": str(self.tmp / "nowhere")})
        self.write_library(
            root, {"apps": [{"name": "Game", "folderName": "Game"}]}
        )
        results = list(QuiverSourceIterable(QuiverSource()))
        game, _additional = results[0]
        self.assertTrue(game.values["installed"])
        self.assertEqual(game.values["executable"], shell_quote(str(program)))


class ExecutableResolutionTests(QuiverSourceTestCase):
    def _library_with_program(self, program: Path, **entry) -> list:
        root = self.make_root()
        app_dir = root / "Apps" / "Game"
        app_dir.mkdir(parents=True, exist_ok=True)
        program = program if program.is_absolute() else app_dir / program
        self.make_program(program)
        payload = {"name": "Game", "folderName": "Game"}
        payload.update(entry)
        self.write_library(root, {"apps": [payload]})
        return list(QuiverSourceIterable(QuiverSource()))

    def test_selected_executable_is_honored(self):
        root = self.make_root()
        app_dir = root / "Apps" / "Game"
        app_dir.mkdir(parents=True, exist_ok=True)
        chosen = self.make_program(app_dir / "bin" / "launch.sh")
        # A program that the choice must win over.
        self.make_program(app_dir / "Game.x86_64")
        (app_dir / "selected_executable.txt").write_text(
            "bin/launch.sh", encoding="utf-8"
        )
        self.write_library(
            root, {"apps": [{"name": "Game", "folderName": "Game"}]}
        )
        results = list(QuiverSourceIterable(QuiverSource()))
        game, _additional = results[0]
        self.assertEqual(game.values["executable"], shell_quote(str(chosen)))

    def test_selected_executable_outside_of_the_app_folder_is_rejected(self):
        root = self.make_root()
        app_dir = root / "Apps" / "Game"
        app_dir.mkdir(parents=True, exist_ok=True)
        outside = self.make_program(root / "evil.sh")
        (app_dir / "selected_executable.txt").write_text(
            "../../evil.sh", encoding="utf-8"
        )
        self.write_library(
            root, {"apps": [{"name": "Game", "folderName": "Game"}]}
        )
        results = list(QuiverSourceIterable(QuiverSource()))
        game, _additional = results[0]
        self.assertEqual(game.values["executable"], "")
        self.assertNotIn(str(outside), game.values["executable"])

    def test_scan_finds_a_single_candidate(self):
        results = self._library_with_program(Path("Game.x86_64"))
        game, _additional = results[0]
        self.assertTrue(game.values["executable"].endswith("Game.x86_64"))

    def test_scan_finds_a_program_in_a_sub_folder(self):
        results = self._library_with_program(Path("bin/Game"))
        game, _additional = results[0]
        self.assertTrue(game.values["executable"].endswith("bin/Game"))

    def test_ambiguous_candidates_have_no_executable(self):
        root = self.make_root()
        app_dir = root / "Apps" / "Game"
        app_dir.mkdir(parents=True, exist_ok=True)
        self.make_program(app_dir / "One.x86_64")
        self.make_program(app_dir / "Two.x86_64")
        self.write_library(
            root, {"apps": [{"name": "Game", "folderName": "Game"}]}
        )
        results = list(QuiverSourceIterable(QuiverSource()))
        game, _additional = results[0]
        self.assertEqual(game.values["executable"], "")

    def test_a_folder_without_a_program_has_no_executable(self):
        root = self.make_root()
        app_dir = root / "Apps" / "Game"
        app_dir.mkdir(parents=True, exist_ok=True)
        (app_dir / "readme.txt").write_text("hello", encoding="utf-8")
        self.write_library(
            root, {"apps": [{"name": "Game", "folderName": "Game"}]}
        )
        results = list(QuiverSourceIterable(QuiverSource()))
        game, _additional = results[0]
        self.assertTrue(game.values["installed"])
        self.assertEqual(game.values["executable"], "")


class RunnerTests(QuiverSourceTestCase):
    def _library_with_windows_program(self, **entry) -> list:
        root = self.make_root()
        app_dir = root / "Apps" / "Game"
        app_dir.mkdir(parents=True, exist_ok=True)
        program = app_dir / "game.exe"
        program.write_bytes(b"MZ")
        payload = {"name": "Game", "folderName": "Game"}
        payload.update(entry)
        self.write_library(root, {"apps": [payload]})
        return list(QuiverSourceIterable(QuiverSource()))

    def test_custom_command_expands_the_placeholders(self):
        results = self._library_with_windows_program(
            linuxRunner="custom",
            linuxCustomLaunchCommand="wine --prefix {gamePath} {exe}",
        )
        game, _additional = results[0]
        executable = game.values["executable"]
        self.assertIn("wine", executable)
        self.assertIn("--prefix", executable)
        self.assertNotIn("{exe}", executable)
        self.assertNotIn("{gamePath}", executable)
        self.assertIn("game.exe", executable)

    def test_custom_command_without_a_placeholder_has_no_executable(self):
        results = self._library_with_windows_program(
            linuxRunner="custom",
            linuxCustomLaunchCommand="run-the-game",
        )
        game, _additional = results[0]
        self.assertEqual(game.values["executable"], "")

    def test_custom_command_with_an_unknown_placeholder_has_no_executable(self):
        results = self._library_with_windows_program(
            linuxRunner="custom",
            linuxCustomLaunchCommand="wine {unknown}",
        )
        game, _additional = results[0]
        self.assertEqual(game.values["executable"], "")

    def test_wine_runner_wraps_the_windows_program(self):
        results = self._library_with_windows_program(linuxRunner="wine")
        game, _additional = results[0]
        self.assertTrue(game.values["executable"].startswith("wine "))
        self.assertIn("game.exe", game.values["executable"])

    def test_proton_runner_without_a_path_has_no_executable(self):
        results = self._library_with_windows_program(linuxRunner="proton")
        game, _additional = results[0]
        self.assertEqual(game.values["executable"], "")

    def test_proton_runner_uses_the_configured_path(self):
        proton = self.make_program(self.tmp / "proton" / "proton")
        results = self._library_with_windows_program(
            linuxRunner="proton", linuxProtonPath=str(proton)
        )
        game, _additional = results[0]
        self.assertIn("waitforexitandrun", game.values["executable"])
        self.assertIn("game.exe", game.values["executable"])

    def test_a_program_without_a_runner_has_no_executable(self):
        results = self._library_with_windows_program()
        game, _additional = results[0]
        self.assertEqual(game.values["executable"], "")


class CoverTests(QuiverSourceTestCase):
    def _library_with_icon(self, icon) -> list:
        root = self.make_root()
        self.write_library(
            root,
            {
                "apps": [
                    {
                        "name": "Game",
                        "folderName": "Game",
                        "appIconUrl": icon,
                    }
                ]
            },
        )
        return list(QuiverSourceIterable(QuiverSource()))

    def test_http_cover_is_kept(self):
        results = self._library_with_icon("https://example.com/icon.png")
        _game, additional = results[0]
        self.assertEqual(
            additional["online_cover_url"], "https://example.com/icon.png"
        )

    def test_the_game_icon_is_the_fallback(self):
        root = self.make_root()
        self.write_library(
            root,
            {
                "apps": [
                    {
                        "name": "Game",
                        "folderName": "Game",
                        "appIconUrl": None,
                        "gameIconUrl": "http://example.com/icon.png",
                    }
                ]
            },
        )
        results = list(QuiverSourceIterable(QuiverSource()))
        _game, additional = results[0]
        self.assertEqual(
            additional["online_cover_url"], "http://example.com/icon.png"
        )

    def test_unsafe_schemes_are_dropped(self):
        for icon in (
            "javascript:alert(1)",
            "file:///etc/passwd",
            "data:image/png;base64,AA",
        ):
            results = self._library_with_icon(icon)
            _game, additional = results[0]
            self.assertNotIn("online_cover_url", additional)

    def test_a_missing_cover_is_not_reported(self):
        results = self._library_with_icon(None)
        _game, additional = results[0]
        self.assertNotIn("online_cover_url", additional)


class EnrichmentTests(QuiverSourceTestCase):
    """The catalog layer: the network is always a stub here."""

    def _library(self, **entry) -> list:
        root = self.make_root()
        payload = {
            "name": "Game",
            "folderName": "Game",
            "repository": "owner/repo",
        }
        payload.update(entry)
        self.write_library(root, {"apps": [payload]})
        return list(QuiverSourceIterable(QuiverSource()))

    def test_the_catalog_is_not_asked_when_the_toggle_is_off(self):
        _shared_stub.schema.booleans["quiver-enrich"] = False
        results = self._library()
        self.assertEqual(len(results), 1)
        self.assertEqual(self.enrich_calls, [])

    def test_the_catalog_is_asked_with_the_whole_entry(self):
        results = self._library(catalogEntryId="slug-of-the-game")
        self.assertEqual(len(results), 1)
        self.assertEqual(len(self.enrich_calls), 1)
        self.assertEqual(self.enrich_calls[0]["catalogEntryId"], "slug-of-the-game")
        self.assertEqual(self.enrich_calls[0]["repository"], "owner/repo")

    def test_an_entry_without_identity_is_not_asked_about(self):
        root = self.make_root()
        self.write_library(root, {"apps": [{"name": "   ", "folderName": "Game"}]})
        # The entry has no name, so it is skipped before the catalog.
        results = list(QuiverSourceIterable(QuiverSource()))
        self.assertEqual(results, [])
        self.assertEqual(self.enrich_calls, [])

    def test_a_catalog_without_an_answer_keeps_the_local_icon(self):
        self.enrich_result = None
        results = self._library(appIconUrl="https://example.com/icon.png")
        game, additional = results[0]
        self.assertEqual(
            additional["online_cover_url"], "https://example.com/icon.png"
        )
        self.assertNotIn("description", game.values)
        self.assertNotIn("developer", game.values)

    def test_the_catalog_fills_the_cover_the_description_and_the_developer(self):
        self.enrich_result = QuiverEnrichment(
            cover_url="https://catalog.example/cover.png",
            description="A game with a catalog entry.",
            developer="Catalog Studio",
            tags=["n64"],
            version="v2",
        )
        results = self._library()
        game, additional = results[0]
        self.assertEqual(
            additional["online_cover_url"], "https://catalog.example/cover.png"
        )
        self.assertEqual(
            game.values["description"], "A game with a catalog entry."
        )
        self.assertEqual(game.values["developer"], "Catalog Studio")

    def test_the_local_entry_wins_over_the_catalog(self):
        self.enrich_result = QuiverEnrichment(
            cover_url="https://catalog.example/cover.png",
            description="The catalog description.",
            developer="Catalog Studio",
        )
        results = self._library(
            project="Local Studio", appIconUrl="https://example.com/icon.png"
        )
        game, additional = results[0]
        self.assertEqual(game.values["developer"], "Local Studio")
        self.assertEqual(
            additional["online_cover_url"], "https://catalog.example/cover.png"
        )

    def test_an_unsafe_catalog_cover_is_dropped(self):
        self.enrich_result = QuiverEnrichment(
            cover_url="javascript:alert(1)",
        )
        results = self._library(appIconUrl="https://example.com/icon.png")
        _game, additional = results[0]
        self.assertEqual(
            additional["online_cover_url"], "https://example.com/icon.png"
        )

    def test_a_failing_catalog_does_not_break_the_scan(self):
        self.enrich_error = RuntimeError("the catalog is down")
        results = self._library(appIconUrl="https://example.com/icon.png")
        self.assertEqual(len(results), 1)
        game, additional = results[0]
        self.assertEqual(game.values["game_id"], "quiver_Game")
        self.assertEqual(
            additional["online_cover_url"], "https://example.com/icon.png"
        )

    def test_the_installed_version_is_not_replaced_by_the_catalog(self):
        root = self.make_root()
        app_dir = root / "Apps" / "Game"
        app_dir.mkdir(parents=True, exist_ok=True)
        (app_dir / "version.txt").write_text("v1.2.3\n", encoding="utf-8")
        self.write_library(
            root,
            {"apps": [{"name": "Game", "folderName": "Game"}]},
        )
        self.enrich_result = QuiverEnrichment(version="v9")
        results = list(QuiverSourceIterable(QuiverSource()))
        _game, additional = results[0]
        self.assertEqual(additional["quiver_installed_version"], "v1.2.3")


class TagsMappingTests(QuiverSourceTestCase):
    """The tags of a game: the local entry first, the catalog after it."""

    def _library(self, **entry) -> list:
        root = self.make_root()
        payload = {
            "name": "Game",
            "folderName": "Game",
            "repository": "owner/repo",
        }
        payload.update(entry)
        self.write_library(root, {"apps": [payload]})
        return list(QuiverSourceIterable(QuiverSource()))

    def test_the_local_tags_are_imported(self):
        results = self._library(tags=["n64", "retro"])
        game, _additional = results[0]
        self.assertEqual(game.values["tags"], ["n64", "retro"])

    def test_the_local_tags_are_cleaned_up(self):
        results = self._library(tags=["  n64  ", "", "   ", "N64", "retro"])
        game, _additional = results[0]
        self.assertEqual(game.values["tags"], ["n64", "retro"])

    def test_a_tag_that_is_not_a_string_is_dropped(self):
        results = self._library(tags=["n64", 42, None, {"tag": "x"}, ["nested"]])
        game, _additional = results[0]
        self.assertEqual(game.values["tags"], ["n64"])

    def test_a_long_tag_is_cut(self):
        results = self._library(tags=["x" * 80])
        game, _additional = results[0]
        self.assertEqual(game.values["tags"], ["x" * 40])

    def test_too_many_tags_are_dropped(self):
        results = self._library(tags=[f"tag{index}" for index in range(30)])
        game, _additional = results[0]
        self.assertEqual(len(game.values["tags"]), 16)
        self.assertEqual(game.values["tags"][0], "tag0")

    def test_a_game_without_tags_has_no_tags(self):
        results = self._library()
        game, _additional = results[0]
        self.assertNotIn("tags", game.values)

    def test_tags_that_are_not_a_list_are_ignored(self):
        results = self._library(tags="n64")
        game, _additional = results[0]
        self.assertNotIn("tags", game.values)

    def test_the_catalog_tags_are_used_when_the_entry_has_none(self):
        self.enrich_result = QuiverEnrichment(tags=["n64", "retro"])
        results = self._library()
        game, _additional = results[0]
        self.assertEqual(game.values["tags"], ["n64", "retro"])

    def test_the_local_tags_win_over_the_catalog(self):
        self.enrich_result = QuiverEnrichment(tags=["catalog"])
        results = self._library(tags=["local"])
        game, _additional = results[0]
        self.assertEqual(game.values["tags"], ["local"])

    def test_the_catalog_tags_are_used_when_the_local_ones_are_empty(self):
        self.enrich_result = QuiverEnrichment(tags=["n64"])
        results = self._library(tags=["  ", ""])
        game, _additional = results[0]
        self.assertEqual(game.values["tags"], ["n64"])

    def test_the_catalog_tags_are_cleaned_up(self):
        self.enrich_result = QuiverEnrichment(tags=["  n64  ", "N64", 42, "retro"])
        results = self._library()
        game, _additional = results[0]
        self.assertEqual(game.values["tags"], ["n64", "retro"])

    def test_the_catalog_is_not_asked_when_the_toggle_is_off(self):
        _shared_stub.schema.booleans["quiver-enrich"] = False
        results = self._library(tags=["local"])
        game, _additional = results[0]
        self.assertEqual(game.values["tags"], ["local"])
        self.assertEqual(self.enrich_calls, [])

    def test_without_the_catalog_the_game_has_no_tags(self):
        _shared_stub.schema.booleans["quiver-enrich"] = False
        results = self._library()
        game, _additional = results[0]
        self.assertNotIn("tags", game.values)
        self.assertEqual(self.enrich_calls, [])


if __name__ == "__main__":
    unittest.main()
