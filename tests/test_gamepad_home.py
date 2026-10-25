"""Gamepad home/library behaviour: pure-logic tests + source guards.

The pure helpers live in ``cartridges.controller`` (no GTK) so they run
without a display. Behavioural wiring is checked with source-text guards,
following the pattern of the other template/wiring tests.
"""

import unittest
from pathlib import Path

from cartridges.controller import (
    GAMEPAD_CONFIRM_HOLD_SECONDS,
    confirm_hold_exceeded,
    focus_class,
    should_confine_gamepad,
)

ROOT = Path(__file__).parents[1]
WINDOW_PY = ROOT / "cartridges" / "window.py"
MAIN_PY = ROOT / "cartridges" / "main.py"
STYLE_CSS = ROOT / "data" / "gtk" / "style.css"


class GamepadPureLogicTests(unittest.TestCase):
    def test_confine_only_with_closed_sidebar_on_library_pages(self):
        for page in ("library", "hidden", "zerados"):
            self.assertTrue(should_confine_gamepad(False, page), page)
            self.assertFalse(should_confine_gamepad(True, page), page)

    def test_no_confine_off_library(self):
        for page in ("", "details", "home", "game-mode"):
            self.assertFalse(should_confine_gamepad(False, page), page)
            self.assertFalse(should_confine_gamepad(True, page), page)

    def test_hold_threshold(self):
        self.assertAlmostEqual(GAMEPAD_CONFIRM_HOLD_SECONDS, 0.6)
        self.assertFalse(confirm_hold_exceeded(0.0))
        self.assertFalse(confirm_hold_exceeded(0.59))
        self.assertTrue(confirm_hold_exceeded(0.6))
        self.assertTrue(confirm_hold_exceeded(1.2))

    def test_hold_custom_threshold(self):
        self.assertTrue(confirm_hold_exceeded(0.3, 0.2))
        self.assertFalse(confirm_hold_exceeded(0.3, 0.5))

    def test_focus_class_names(self):
        self.assertEqual(focus_class(True), "gamepad-tile-focus-rgb")
        self.assertEqual(focus_class(False), "gamepad-tile-focus")


class GamepadHomeWiringTests(unittest.TestCase):
    """Source guards: the behaviour exists without needing a display."""

    def test_home_toggles_sidebar_like_guide(self):
        text = MAIN_PY.read_text(encoding="utf-8")
        self.assertIn("case ControllerAction.HOME:", text)
        self.assertIn("gamepad_toggle_sidebar()", text)

    def test_confirm_hold_wiring(self):
        text = MAIN_PY.read_text(encoding="utf-8")
        for name in (
            "_gamepad_confirm_press",
            "_on_gamepad_confirm_hold",
            "_gamepad_confirm_release",
            "gamepad_confirm_pressed",
            "gamepad_confirm_hold",
            "gamepad_confirm_released",
            "GAMEPAD_CONFIRM_HOLD_SECONDS",
            "confirm_hold_exceeded",
            "monotonic",
        ):
            self.assertIn(name, text)

    def test_tap_never_uses_cover_launches_game(self):
        text = WINDOW_PY.read_text(encoding="utf-8")
        start = text.index("def gamepad_confirm_tap(")
        end = text.index("def gamepad_confirm_pressed(")
        self.assertNotIn("cover-launches-game", text[start:end])
        self.assertIn("show_details_page", text[start:end])
        self.assertIn("on_launcher_clicked", text[start:end])

    def test_window_helpers_exist(self):
        text = WINDOW_PY.read_text(encoding="utf-8")
        for name in (
            "def _gamepad_sidebar_open(",
            "def _is_library_page(",
            "def _gamepad_focus_classes(",
            "def gamepad_confirm_pressed(",
            "def gamepad_confirm_hold(",
            "def gamepad_confirm_released(",
            "def show_gamepad_keyboard(",
            "should_confine_gamepad",
            "focus_class",
            "GAMEPAD_TILE_FOCUS_RGB_CLASS",
            "GAMEPAD_TILE_FOCUS_CLASS",
        ):
            self.assertIn(name, text)

    def test_search_ends_with_onscreen_keyboard(self):
        text = WINDOW_PY.read_text(encoding="utf-8")
        start = text.index("def gamepad_search(")
        end = text.index("def _game_from_widget(")
        body = text[start:end]
        self.assertIn("show_gamepad_keyboard", body)
        self.assertIn("set_search_mode(True)", body)

    def test_main_menu_stays_on_library_pages(self):
        text = WINDOW_PY.read_text(encoding="utf-8")
        start = text.index("def gamepad_main_menu(")
        end = text.index("def _focus_app_menu_popover(")
        body = text[start:end]
        self.assertIn("primary_menu_button", body)
        self.assertIn("hidden_primary_menu_button", body)
        self.assertIn("zerados_primary_menu_button", body)
        self.assertIn("popup()", body)
        self.assertIn("grab_focus()", body)

    def test_focus_css_classes_exist(self):
        css = STYLE_CSS.read_text(encoding="utf-8")
        self.assertIn(".gamepad-tile-focus", css)
        self.assertIn(".gamepad-tile-focus-rgb", css)

    def test_no_new_css_class_names(self):
        text = WINDOW_PY.read_text(encoding="utf-8")
        self.assertNotIn("gamepad-focus", text.replace("gamepad-tile-focus", ""))
        self.assertNotIn("gamepad_highlight", text)
        self.assertNotIn("gamepad-highlight", text)


if __name__ == "__main__":
    unittest.main()
