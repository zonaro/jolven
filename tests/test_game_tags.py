"""Tests for the tags field of the game model and its persistence.

The game model lives behind Gtk/GSettings imports (`cartridges.game`) that
do not exist in a bare source tree, so the parts that decide the tags are
extracted from the source with `ast` and run in a plain class — the same
approach the tests of the serialization of the game model already use.
Everything asserted here (the default of the field, the copy of the list,
the trip through the file of the game) runs with no display, no GTK and
no GSettings database.
"""

import ast
import json
import shlex
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parents[1]


def _parse(relative: str) -> ast.Module:
    return ast.parse((ROOT / relative).read_text(encoding="utf-8"))


def _class_node(tree: ast.Module, name: str) -> ast.ClassDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == name
    )


def _function_node(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _serialized_names(function: ast.FunctionDef) -> set[str]:
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "attrs"
            for target in node.targets
        ):
            return {
                item.value
                for item in node.value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            }
    return set()


def _build_game_class() -> type:
    """A stand-in for the game model, with the real rules of the tags.

    The real class needs GTK and GSettings, so only the parts that
    decide the tags are extracted: the field, the normalizer and the
    method that fills the values of a game.
    """
    tree = _parse("cartridges/game.py")
    game_class = _class_node(tree, "Game")
    field = next(
        node
        for node in game_class.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "tags"
    )
    update_values = next(
        node
        for node in game_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "update_values"
    )
    normalize = _function_node(tree, "normalize_tags")
    synthetic = ast.ClassDef(
        name="TestGame",
        bases=[],
        keywords=[],
        body=[field, update_values],
        decorator_list=[],
    )
    module = ast.fix_missing_locations(
        ast.Module(body=[normalize, synthetic], type_ignores=[])
    )
    namespace: dict[str, Any] = {"shlex": shlex, "Any": Any}
    exec(compile(module, "game.py", "exec"), namespace)  # pylint: disable=exec-used
    return namespace["TestGame"]


class _FakeGame:
    """Stand-in game whose missing fields serialize as ``None``."""

    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)

    def __getattr__(self, _name: str) -> None:
        return None


class GameTagsTests(unittest.TestCase):
    """The field of the model: the default, the copy and the updates."""

    def setUp(self) -> None:
        self.game_class = _build_game_class()

    def test_a_game_without_tags_has_no_tags(self) -> None:
        game = self.game_class()
        game.update_values({"name": "Legacy Game"})
        self.assertEqual(game.tags, [])

    def test_the_tags_are_applied(self) -> None:
        game = self.game_class()
        game.update_values({"name": "Game", "tags": ["n64", "retro"]})
        self.assertEqual(game.tags, ["n64", "retro"])

    def test_a_tag_that_is_not_a_string_is_dropped(self) -> None:
        game = self.game_class()
        game.update_values({"name": "Game", "tags": ["n64", 42, None]})
        self.assertEqual(game.tags, ["n64"])

    def test_tags_that_are_not_a_list_are_ignored(self) -> None:
        game = self.game_class()
        game.update_values({"name": "Game", "tags": None})
        self.assertEqual(game.tags, [])

    def test_two_games_do_not_share_the_same_tags(self) -> None:
        first = self.game_class()
        second = self.game_class()
        first.update_values({"name": "First"})
        second.update_values({"name": "Second"})
        first.tags.append("n64")
        self.assertEqual(second.tags, [])
        self.assertIsNot(first.tags, second.tags)

    def test_the_default_of_the_class_is_never_shared(self) -> None:
        game = self.game_class()
        game.update_values({"name": "Game"})
        game.tags.append("n64")
        self.assertEqual(self.game_class.tags, [])

    def test_the_list_of_the_caller_is_not_shared(self) -> None:
        tags = ["n64"]
        game = self.game_class()
        game.update_values({"name": "Game", "tags": tags})
        game.tags.append("retro")
        self.assertEqual(tags, ["n64"])

    def test_an_update_keeps_the_tags(self) -> None:
        game = self.game_class()
        game.update_values({"name": "Game", "tags": ["n64"]})
        game.update_values({"blacklisted": True})
        self.assertEqual(game.tags, ["n64"])


class FileManagerTagsTests(unittest.TestCase):
    """The trip of the tags through the file of the game."""

    def setUp(self) -> None:
        tree = _parse("cartridges/store/managers/file_manager.py")
        self.main = next(
            node
            for node in _class_node(tree, "FileManager").body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        self.game_class = _build_game_class()

    def test_tags_are_serialized(self) -> None:
        self.assertIn("tags", _serialized_names(self.main))

    def _save(self, games_dir: Path, **values: Any) -> dict:
        """Save a game with the real manager and return the file."""
        namespace: dict[str, Any] = {
            "json": json,
            "shared": types.SimpleNamespace(games_dir=games_dir),
            "Game": object,
        }
        module = ast.fix_missing_locations(ast.Module(body=[self.main], type_ignores=[]))
        exec(compile(module, "file_manager.py", "exec"), namespace)  # pylint: disable=exec-used
        namespace["main"](None, _FakeGame(**values), {"skip_save": False})
        path = games_dir / f"{values['game_id']}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_the_tags_survive_the_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            games_dir = Path(directory)
            saved = self._save(
                games_dir, game_id="rt-1", name="Game", tags=["n64", "retro"]
            )
            self.assertEqual(saved["tags"], ["n64", "retro"])

            game = self.game_class()
            game.update_values(saved)
            self.assertEqual(game.tags, ["n64", "retro"])

    def test_an_old_file_without_tags_loads_with_no_tags(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            games_dir = Path(directory)
            path = games_dir / "old-1.json"
            path.write_text(
                json.dumps({"game_id": "old-1", "name": "Old Game"}), encoding="utf-8"
            )
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("tags", saved)

            game = self.game_class()
            game.update_values(saved)
            self.assertEqual(game.tags, [])

    def test_a_broken_tag_in_the_file_does_not_break_the_game(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            games_dir = Path(directory)
            path = games_dir / "broken-1.json"
            path.write_text(
                json.dumps({"game_id": "broken-1", "name": "Broken", "tags": "n64"}),
                encoding="utf-8",
            )
            saved = json.loads(path.read_text(encoding="utf-8"))

            game = self.game_class()
            game.update_values(saved)
            self.assertEqual(game.tags, ["n64"])


class DetailsDialogTagsTests(unittest.TestCase):
    """The row of the tags in the details dialog.

    The dialog is a GTK template: the widget has to be declared in the
    blueprint and in the class, with the same name, or the dialog does
    not open. There is no headless test of the widget itself, so the
    contract is checked in the source, the way the other templates are
    checked in this repository.
    """

    def setUp(self) -> None:
        self.python = (ROOT / "cartridges" / "details_dialog.py").read_text(
            encoding="utf-8"
        )
        self.blp = (ROOT / "data" / "gtk" / "details-dialog.blp").read_text(
            encoding="utf-8"
        )

    def test_the_row_is_declared_in_the_class_and_in_the_blueprint(self) -> None:
        self.assertIn("tags: Adw.EntryRow = Gtk.Template.Child()", self.python)
        self.assertIn("Adw.EntryRow tags {", self.blp)

    def test_the_row_is_hidden_until_the_game_has_tags(self) -> None:
        block = self.blp[self.blp.index("Adw.EntryRow tags {") :]
        block = block[: block.index("}")]
        self.assertIn("visible: false;", block)
        self.assertIn("editable: false;", block)

    def test_the_tags_are_shown_joined(self) -> None:
        self.assertIn('self.tags.set_text(", ".join(self.game.tags))', self.python)
        self.assertIn("self.tags.set_visible(True)", self.python)

    def test_the_dialog_is_in_the_translation_list(self) -> None:
        potfiles = (ROOT / "po" / "POTFILES").read_text(encoding="utf-8")
        self.assertIn("data/gtk/details-dialog.blp", potfiles)
        self.assertIn("cartridges/details_dialog.py", potfiles)


if __name__ == "__main__":
    unittest.main()
