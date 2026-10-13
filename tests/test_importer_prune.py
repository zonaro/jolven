"""Regression tests for importer prune semantics (issue #36).

A source whose scan raises SourceScanError mid-scan must be withheld from
pruning (its id stays out of ``scanned_source_ids``); a scan that only hits
per-entry noise still counts as complete.

These tests drive the real ``Importer.source_task_thread_func`` and
``Importer.remove_games``. Importing them pulls the GTK widget chain
(``cartridges.game`` -> ``cartridges.game_cover``), whose placeholder
textures are loaded from the compiled GResource at import time. That
resource only exists once the app has been built, so without it the import
aborts the process (fatal Gdk-ERROR, uncatchable from Python). The GResource
is therefore registered first from the in-tree build or an installed data
dir; when none is available the tests skip explicitly instead of faking the
importer logic.
"""

import builtins
import unittest
from pathlib import Path
from types import SimpleNamespace

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gio  # noqa: E402


def _register_gresource():
    """Register the compiled app GResource so widget modules can import.

    :raise unittest.SkipTest: when no built/installed GResource is found,
        i.e. the harness cannot drive the Importer without the built app.
    """
    root = Path(__file__).resolve().parent.parent
    candidates = [
        root / "build" / "data" / "jolven.gresource",
        Path.home() / ".local" / "share" / "jolven" / "jolven.gresource",
        Path("/usr/local/share/jolven/jolven.gresource"),
        Path("/usr/share/jolven/jolven.gresource"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            Gio.Resource.load(str(candidate))._register()
            return
    raise unittest.SkipTest(
        "needs the built app: no jolven.gresource found, "
        "the Importer cannot be driven without it"
    )


class ImporterPruneTests(unittest.TestCase):
    def setUp(self):
        _register_gresource()
        from cartridges import shared
        from cartridges.errors.error_producer import ErrorProducer
        from cartridges.importer.importer import Importer
        from cartridges.importer.source import Source, SourceIterable

        self.shared = shared
        self._old_store = getattr(shared, "store", None)
        self._old_schema = getattr(shared, "schema", None)
        self._had_store = hasattr(shared, "store")
        self._had_schema = hasattr(shared, "schema")

        class ScriptedIterable(SourceIterable):
            """Yields scripted entries, raising scripted errors in turn."""

            def __iter__(self):
                for step in self.script:
                    if isinstance(step, BaseException):
                        raise step
                    yield step

        class ScriptedSource(Source):
            """Headless source: always available, no locations to resolve."""

            name = "Scripted"
            iterable_class = ScriptedIterable

            def __init__(self, source_id, script):
                super().__init__()
                self.source_id = source_id
                self.locations = []
                self.script = script

            @property
            def is_available(self):
                return True

            def __iter__(self):
                iterable = self.iterable_class(self)
                iterable.script = self.script
                return iter(iterable)

        self.ScriptedSource = ScriptedSource

        importer = Importer.__new__(Importer)
        ErrorProducer.__init__(importer)
        importer.scanned_source_ids = set()
        importer.game_pipelines = set()
        importer.removed_game_ids = set()
        self.importer = importer

    def tearDown(self):
        if self._had_store:
            self.shared.store = self._old_store
        else:
            try:
                delattr(self.shared, "store")
            except AttributeError:
                pass
        if self._had_schema:
            self.shared.schema = self._old_schema
        else:
            try:
                delattr(self.shared, "schema")
            except AttributeError:
                pass

    @staticmethod
    def _make_game(game_id, base_source):
        calls = []
        return SimpleNamespace(
            name=game_id,
            game_id=game_id,
            source=base_source,
            base_source=base_source,
            removed=False,
            blacklisted=False,
            status="",
            save=lambda: calls.append("save"),
            update=lambda: calls.append("update"),
            calls=calls,
        )

    class _FakeStore:
        def __init__(self, games):
            self.games = games
            self.new_game_ids = set()
            self.duplicate_game_ids = set()

        def __iter__(self):
            return iter(self.games)

        def get(self, game_id, default=None):
            for game in self.games:
                if game.game_id == game_id:
                    return game
            return default

    class _FakeSchema:
        def get_boolean(self, _key):
            return True

        def list_keys(self):
            return []

    def test_scan_error_withholds_source_from_pruning(self):
        from cartridges.importer.source import SourceScanError

        source = self.ScriptedSource(
            "failing",
            (None, SourceScanError("Title", "Subtitle")),
        )
        self.importer.source_task_thread_func((source,))

        self.assertNotIn("failing", self.importer.scanned_source_ids)
        self.assertTrue(
            any(
                isinstance(error, SourceScanError)
                for error in self.importer.collect_errors()
            )
        )

        # The failed scan must not prune that source's games
        game = self._make_game("failing_old", "failing")
        self.shared.schema = self._FakeSchema()
        self.shared.store = self._FakeStore([game])
        self.importer.remove_games()
        self.assertFalse(game.removed)

    def test_generic_entry_error_still_counts_as_complete(self):
        source = self.ScriptedSource(
            "noisy",
            (None, ValueError("bad entry"), None),
        )
        self.importer.source_task_thread_func((source,))

        self.assertIn("noisy", self.importer.scanned_source_ids)
        self.assertTrue(self.importer.collect_errors())

    def test_clean_scan_prunes_disappeared_game(self):
        source = self.ScriptedSource("clean", (None,))
        self.importer.source_task_thread_func((source,))
        self.assertIn("clean", self.importer.scanned_source_ids)

        game = self._make_game("clean_old", "clean")
        self.shared.schema = self._FakeSchema()
        self.shared.store = self._FakeStore([game])
        self.importer.remove_games()
        self.assertTrue(game.removed)
        self.assertIn("clean_old", self.importer.removed_game_ids)


if __name__ == "__main__":
    unittest.main()
