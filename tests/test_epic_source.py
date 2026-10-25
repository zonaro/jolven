"""Tests for the native Epic Games Launcher source.

The source reads a launcher's own files from disk, so everything asserted
here runs against temporary directories: no GTK, no GSettings database, no
running launcher and no network. `cartridges.shared` and `cartridges.game`
are stubbed before the module under test is imported, exactly the parts it
touches through `Game(values)`, `shared.import_time` and the schema.

What the suite really guards: the install list is append-only and can be
caught mid-write, and the importer prunes every game a scan did not return.
A partial list must therefore either fall back to the launcher's own backup
or refuse the scan outright — never quietly shrink the library.
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

    def set_string(self, key, value):
        self.strings[key] = value

    def get_boolean(self, key):
        return self.booleans.get(key, False)


class _StubShared:
    def __init__(self, root: Path):
        self.schema = _StubSchema()
        self.import_time = 1234567890
        self.data_dir = root / "data"
        self.host_data_dir = self.data_dir
        self.cache_dir = root / "cache"
        self.host_cache_dir = self.cache_dir
        self.flatpak_dir = root / "var" / "app"


class _StubGame:
    """Records the values dict the way `Game.update_values` would."""

    def __init__(self, values):
        self.values = dict(values)
        for key, value in values.items():
            setattr(self, key, value)


# The declared candidates are never created: every test points the schema at
# a folder of its own, so the machine running the suite contributes nothing.
_STUB_SHARED = _StubShared(Path("/nonexistent/jolven-epic-stub"))
_STUB_GAME_MODULE = type("game", (), {"Game": _StubGame})

# The stubs have to win over the real modules even when another test module
# imported them first: `from cartridges import shared` resolves the package
# attribute, and the modules that bind `shared` keep that binding. So the
# modules are dropped, the stubs are installed, the source is imported
# against them, and the original modules come back afterwards.
import cartridges  # noqa: E402

_STUBBED_MODULES = (
    "cartridges.shared",
    "cartridges.game",
    "cartridges.importer.location",
    "cartridges.importer.source",
    "cartridges.importer.epic_source",
)
_originals = {name: sys.modules.pop(name, None) for name in _STUBBED_MODULES}

sys.modules["cartridges.shared"] = _STUB_SHARED
sys.modules["cartridges.game"] = _STUB_GAME_MODULE
cartridges.shared = _STUB_SHARED
cartridges.game = _STUB_GAME_MODULE

from cartridges.importer.epic_source import (  # noqa: E402
    EpicSource,
    EpicSourceIterable,
    _load_installations,
    _read_catalog,
    _read_installations,
)
from cartridges.importer.location import UnresolvableLocationError  # noqa: E402
from cartridges.importer.source import ExecutableFormatSource, SourceScanError  # noqa: E402

for _name, _module in _originals.items():
    if _module is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _module
if _originals["cartridges.shared"] is not None:
    cartridges.shared = _originals["cartridges.shared"]
if _originals["cartridges.game"] is not None:
    cartridges.game = _originals["cartridges.game"]

ITEM_ID = "d43a176b083c4f92867c2313c6326d26"
INSTALLATION_ID = "45BA7751657C97E95CFE7BF2AB075538"
HEADER = '{"version":1,"writtenAt":"2026-10-22T04:58:09Z","entries":1}'
COVER_MD5 = "64753fed67a14f055ee4e7150fe34daf"
COVER_URL = f"https://cdn1.epicgames.com/item/turtle/Maneater-{COVER_MD5}"

# Deliberately outside any folder a test creates: a record left at this path
# is a stale install, and no test may read the launcher of the machine it
# happens to run on.
STALE_DIR = "/nonexistent/epic-install/Maneater"


def _record(**overrides):
    """A full install record, shaped the way the launcher writes them."""
    record = {
        "installationId": INSTALLATION_ID,
        "complete": False,
        "dir": STALE_DIR,
        "platform": "Windows",
        "namespace": "turtle",
        "itemId": ITEM_ID,
        "artifactId": "Turtle",
        "tags": [""],
        "launchCommand": "",
        "launchExecutable": "Maneater.exe",
        "writtenAt": "2026-10-16T01:16:40Z",
    }
    record.update(overrides)
    return record


def _catalog(item_id: str = ITEM_ID, **overrides):
    """A catalog cache holding one item."""
    item = {
        "id": item_id,
        "namespace": "turtle",
        "title": "Maneater",
        "developer": "Tripwire Interactive",
        "keyImages": [
            {
                "type": "DieselGameBoxTall",
                "url": COVER_URL,
                "md5": COVER_MD5,
                "width": 1200,
                "height": 1600,
            }
        ],
    }
    item.update(overrides)
    return {"items": {item_id: {"item": item, "expiresAt": 0, "cachedAt": 0}}}


class EpicSourceTestCase(unittest.TestCase):
    """Scans over a temporary launcher installation."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

        self.data = self.tmp / "data" / "com.epicgames.eglv2"
        self.cache = self.tmp / "cache" / "com.epicgames.eglv2"
        self.images = self.cache / "images"
        self.install_dir = self.tmp / "games" / "Maneater"
        for folder in (self.data, self.images, self.install_dir):
            folder.mkdir(parents=True, exist_ok=True)

        self._old_data = _STUB_SHARED.schema.strings.get("epic-location")
        self._old_cache = _STUB_SHARED.schema.strings.get("epic-cache-location")
        self.addCleanup(self._restore_locations)
        _STUB_SHARED.schema.set_string("epic-location", str(self.data))
        _STUB_SHARED.schema.set_string("epic-cache-location", str(self.cache))

        self.installs = self.data / "installations.jsonl"
        self.backup = self.installs.with_name("installations.jsonl.prev")
        self.catalog = self.data / "cache" / "prod" / "catalog-cache.json"
        self.catalog.parent.mkdir(parents=True, exist_ok=True)

    def _restore_locations(self):
        for key, previous in (
            ("epic-location", self._old_data),
            ("epic-cache-location", self._old_cache),
        ):
            if previous is None:
                _STUB_SHARED.schema.strings.pop(key, None)
            else:
                _STUB_SHARED.schema.set_string(key, previous)

    # --- helpers ---------------------------------------------------------

    def write_installs(self, *lines, path=None):
        target = path or self.installs
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return target

    def write_backup(self, written_at, *records):
        self.write_installs(
            json.dumps({"version": 1, "writtenAt": written_at, "entries": 0}),
            *(json.dumps(record) for record in records),
            path=self.backup,
        )

    def write_catalog(self, document):
        self.catalog.write_text(json.dumps(document), encoding="utf-8")

    def installed(self, **overrides):
        """A record for the install directory this test created."""
        overrides.setdefault("dir", str(self.install_dir))
        return _record(**overrides)

    def scan(self):
        return list(EpicSource())

    # --- the happy path --------------------------------------------------

    def test_installed_game_comes_in_with_catalog_metadata(self):
        self.write_installs(HEADER, json.dumps(self.installed()))
        self.write_catalog(_catalog())

        games = self.scan()

        self.assertEqual(len(games), 1)
        game, cover = games[0]
        self.assertEqual(game.name, "Maneater")
        self.assertEqual(game.developer, "Tripwire Interactive")
        self.assertEqual(game.source, "epic")
        self.assertEqual(game.game_id, f"epic_{ITEM_ID}")
        self.assertEqual(game.added, 1234567890)
        # The source leaves `installed` to `Game`'s default: an entry in the
        # install list is an install, however incomplete the launcher calls it.
        self.assertTrue(game.values.get("installed", True))
        self.assertEqual(cover, {"online_cover_url": COVER_URL})

    def test_deep_link_is_quoted_so_the_shell_keeps_the_query(self):
        source = EpicSource()

        self.assertEqual(
            source.make_executable(app_id="Turtle"),
            'xdg-open "com.epicgames.launcher://apps/Turtle?action=launch"',
        )

    def test_source_contract(self):
        self.assertIs(EpicSource.iterable_class, EpicSourceIterable)
        self.assertEqual(EpicSource.source_id, "epic")
        self.assertEqual(EpicSource.available_on, {"linux"})
        self.assertTrue(issubclass(EpicSource, ExecutableFormatSource))

    # --- the append-only list -------------------------------------------

    def test_newest_line_for_an_installation_wins(self):
        """The file appends instead of rewriting, so the last line is truth."""
        self.write_installs(
            HEADER,
            json.dumps(_record()),  # stale: the directory is not there
            json.dumps(self.installed()),  # newest: the directory exists
        )
        self.write_catalog(_catalog())

        # First line would be skipped as stale; only a last-line-wins reader
        # finds the installed game.
        games = self.scan()

        self.assertEqual(len(games), 1)
        self.assertEqual(games[0][0].name, "Maneater")

    def test_game_id_is_the_catalog_item_not_the_installation(self):
        """Reinstalling must not hand the game a new identity."""
        other_dir = self.tmp / "games" / "Maneater-2"
        other_dir.mkdir()
        self.write_installs(
            HEADER,
            json.dumps(
                self.installed(installationId="A" * 32, dir=str(self.install_dir))
            ),
            json.dumps(
                self.installed(installationId="B" * 32, dir=str(other_dir))
            ),
        )
        self.write_catalog(_catalog())

        games = self.scan()

        self.assertEqual(len(games), 2)
        self.assertEqual({game.game_id for game, _ in games}, {f"epic_{ITEM_ID}"})

    def test_removal_tombstone_is_not_a_game(self):
        self.write_installs(
            HEADER,
            json.dumps(
                _record(installationId="T" * 32, deleted=True,
                        dir=str(self.install_dir)),
            ),
            json.dumps(self.installed()),
        )
        self.write_catalog(_catalog())

        # The tombstone points at a directory that exists, so only the
        # `deleted` flag can be keeping it out; the real record survives.
        games = self.scan()

        self.assertEqual(len(games), 1)
        self.assertEqual(games[0][0].name, "Maneater")

    def test_record_whose_install_directory_is_gone_is_skipped(self):
        self.write_installs(HEADER, json.dumps(_record()))
        self.write_catalog(_catalog())

        # The launcher drops a record whose directory is gone, and a play
        # button for a folder that is not there would be worse than nothing.
        self.assertEqual(self.scan(), [])

    def test_record_without_an_install_directory_is_not_a_game(self):
        """A tombstone that carries no `dir` at all."""
        self.write_installs(
            HEADER,
            json.dumps(_record(installationId="T" * 32, deleted=True,
                               dir=None)),
            json.dumps(self.installed()),
        )
        self.write_catalog(_catalog())

        self.assertEqual(len(self.scan()), 1)

    def test_the_header_is_not_mistaken_for_a_record(self):
        self.write_installs(HEADER)
        self.write_catalog(_catalog())

        # A header with no records is a legitimately empty library.
        self.assertEqual(self.scan(), [])

    # --- metadata fallbacks ---------------------------------------------

    def test_missing_catalog_falls_back_to_the_executable_name(self):
        self.write_installs(HEADER, json.dumps(self.installed()))

        games = self.scan()

        self.assertEqual(len(games), 1)
        self.assertEqual(games[0][0].name, "Maneater")
        # Nothing to read means nothing to report; `Game` defaults it away.
        self.assertIsNone(games[0][0].values.get("developer"))
        self.assertEqual(games[0][1], {})

    def test_corrupt_catalog_is_not_a_scan_failure(self):
        self.write_installs(HEADER, json.dumps(self.installed()))
        self.catalog.write_text("{not json", encoding="utf-8")

        games = self.scan()

        self.assertEqual(len(games), 1)
        self.assertEqual(games[0][0].name, "Maneater")

    def test_local_cover_is_used_when_the_launcher_cached_it(self):
        image = self.images / f"{COVER_MD5}.jpg"
        image.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
        self.write_installs(HEADER, json.dumps(self.installed()))
        self.write_catalog(_catalog())

        games = self.scan()

        self.assertEqual(games[0][1], {"local_image_path": image})

    def test_cover_falls_back_to_the_url(self):
        self.write_installs(HEADER, json.dumps(self.installed()))
        self.write_catalog(_catalog())

        games = self.scan()

        self.assertEqual(games[0][1], {"online_cover_url": COVER_URL})

    def test_non_https_cover_url_is_rejected(self):
        self.write_installs(HEADER, json.dumps(self.installed()))
        self.write_catalog(
            _catalog(
                keyImages=[
                    {
                        "type": "DieselGameBoxTall",
                        "url": "http://insecure.example/cover.png",
                        "md5": COVER_MD5,
                    }
                ]
            )
        )

        games = self.scan()

        self.assertEqual(games[0][1], {})

    def test_cover_md5_that_is_not_a_plain_name_is_ignored(self):
        """The md5 becomes a path component and must not climb out of it."""
        image = self.images / f"{COVER_MD5}.jpg"
        image.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
        self.write_installs(HEADER, json.dumps(self.installed()))
        self.write_catalog(
            _catalog(
                keyImages=[
                    {
                        "type": "DieselGameBoxTall",
                        "url": COVER_URL,
                        "md5": "../../etc/passwd",
                    }
                ]
            )
        )

        games = self.scan()

        # The traversal is refused, so the local file is never a candidate
        # and the cover falls back to the catalog URL.
        self.assertEqual(games[0][1], {"online_cover_url": COVER_URL})

    def test_cache_location_is_optional(self):
        """No image cache means an import, not a failed scan."""
        _STUB_SHARED.schema.set_string("epic-cache-location", str(self.tmp / "none"))
        self.write_installs(HEADER, json.dumps(self.installed()))
        self.write_catalog(_catalog())

        games = self.scan()

        self.assertEqual(len(games), 1)
        self.assertEqual(games[0][1], {"online_cover_url": COVER_URL})

    # --- a list that must not be published ------------------------------

    def test_torn_list_without_a_newer_backup_withholds_the_source(self):
        """A half-written list must not shrink the library."""
        self.write_installs(
            HEADER,
            json.dumps(self.installed()),
            '{"installationId": "cut off right here',
        )
        self.write_catalog(_catalog())

        with self.assertRaises(SourceScanError):
            self.scan()

    def test_torn_list_falls_back_to_a_newer_backup(self):
        self.write_installs(
            HEADER,
            json.dumps(self.installed()),
            '{"installationId": "cut off right here',
        )
        self.write_backup("2026-10-23T00:00:00Z", self.installed())
        self.write_catalog(_catalog())

        games = self.scan()

        self.assertEqual(len(games), 1)
        self.assertEqual(games[0][0].name, "Maneater")

    def test_torn_list_prefers_a_newer_backup(self):
        self.write_installs(
            '{"version":1,"writtenAt":"2026-10-20T00:00:00Z","entries":1}',
            json.dumps(self.installed()),
            '{"installationId": "cut off right here',
        )
        self.write_backup("2026-10-23T00:00:00Z", self.installed())
        self.write_catalog(_catalog())

        self.assertEqual(len(self.scan()), 1)

    def test_torn_primary_that_is_still_the_newest_copy_is_withheld(self):
        """The backup is complete but older: neither copy speaks alone."""
        self.write_installs(
            '{"version":1,"writtenAt":"2026-10-23T00:00:00Z","entries":1}',
            json.dumps(self.installed()),
            '{"installationId": "cut off right here',
        )
        self.write_backup("2026-10-20T00:00:00Z")
        self.write_catalog(_catalog())

        with self.assertRaises(SourceScanError):
            self.scan()

    def test_undecodable_primary_uses_the_backup(self):
        self.installs.write_bytes(b"\xff\xfe\x00 not utf-8 at all")
        self.write_backup("2026-10-16T01:16:40Z", self.installed())
        self.write_catalog(_catalog())

        self.assertEqual(len(self.scan()), 1)

    def test_undecodable_primary_without_a_backup_withholds_the_source(self):
        self.installs.write_bytes(b"\xff\xfe\x00 not utf-8 at all")
        self.write_catalog(_catalog())

        with self.assertRaises(SourceScanError):
            self.scan()

    def test_missing_list_is_withheld_not_read_as_empty(self):
        """The location requires the file, so its absence is a race."""
        # setUp creates the data folder but never the list itself.
        self.assertFalse(self.installs.exists())

        with self.assertRaises(SourceScanError):
            _load_installations(self.installs)

    def test_unresolvable_location_withholds_the_source(self):
        """A folder picked in the preferences that was deleted."""
        _STUB_SHARED.schema.set_string("epic-location", str(self.tmp / "nowhere"))

        with self.assertRaises(UnresolvableLocationError):
            self.scan()

    # --- unit seams ------------------------------------------------------

    def test_reading_keeps_one_record_per_installation(self):
        self.write_installs(
            HEADER,
            json.dumps(_record(writtenAt="2026-10-16T01:16:40Z",
                               launchExecutable="Old.exe")),
            json.dumps(_record(writtenAt="2026-10-22T05:00:59Z",
                               launchExecutable="Maneater.exe")),
        )

        parsed = _load_installations(self.installs)

        self.assertEqual(list(parsed), [INSTALLATION_ID])
        self.assertEqual(parsed[INSTALLATION_ID]["writtenAt"],
                         "2026-10-22T05:00:59Z")
        self.assertEqual(parsed[INSTALLATION_ID]["launchExecutable"],
                         "Maneater.exe")

    def test_reading_an_absent_copy_reports_it_as_absent(self):
        parsed = _read_installations(self.tmp / "never-written.jsonl")

        self.assertTrue(parsed.absent)
        self.assertFalse(parsed.usable)
        self.assertEqual(parsed.entries, {})

    def test_catalog_read_joins_items_only(self):
        self.write_catalog(
            {
                "items": {
                    ITEM_ID: {"item": {"title": "Maneater"}},
                    "broken": {"item": "not an object"},
                    "bogus": "not a wrapper",
                },
                "schemaVersion": 1,
            }
        )

        catalog = _read_catalog(self.data)

        self.assertEqual(list(catalog), [ITEM_ID])
        self.assertEqual(catalog[ITEM_ID]["title"], "Maneater")


if __name__ == "__main__":
    unittest.main()
