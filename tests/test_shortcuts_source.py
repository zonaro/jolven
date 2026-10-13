"""Pure-python tests for the Windows shortcuts source.

The module under test lives behind Gtk/GSettings imports (`cartridges.game`,
`cartridges.shared`) that do not exist in a bare source tree, so those two
dependencies are stubbed in `sys.modules` before import — exactly the parts
the exercised code only touches through `Game(values)` and
`shared.import_time`/`shared.schema`. Everything asserted here (parsing,
quoting guards, id stability, folder policy) runs with no display, no
Windows and no GSettings database.

If `cartridges.importer.source` does not provide `SourceScanError` yet (it
lands via a sibling lane), a fallback exception is shimmed onto it so the
module import stays green; remove the shim once the interface exists.
"""

import builtins
import sys
import tempfile
import unittest
from hashlib import sha256
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


class _StubShared:
    def __init__(self):
        self.schema = _StubSchema()
        self.import_time = 1234567890


class _StubGame:
    """Records the values dict like `Game.update_values` would."""

    def __init__(self, values):
        self.values = dict(values)
        for key, value in values.items():
            setattr(self, key, value)


_added_stubs = []
for _mod_name, _stub in (
    ("cartridges.shared", _StubShared()),
    ("cartridges.game", type("game", (), {"Game": _StubGame})),
):
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = _stub
        _added_stubs.append(_mod_name)

from cartridges.importer import source as _source_module  # noqa: E402

# Pending cross-lane interface: `SourceScanError` is defined in
# `cartridges.importer.source` by a sibling lane. Shim a fallback so these
# tests (and the module import) work before it lands.
NEEDS_SCAN_ERROR_SHIM = not hasattr(_source_module, "SourceScanError")
if NEEDS_SCAN_ERROR_SHIM:
    _source_module.SourceScanError = type(  # type: ignore[attr-defined]
        "SourceScanError", (Exception,), {}
    )

from cartridges.importer import shortcuts_source  # noqa: E402
from cartridges.importer.shortcuts_source import (  # noqa: E402
    ShortcutsSource,
    ShortcutsSourceIterable,
    args_safe,
    atalhos_da_pasta,
    cmd_safe,
    steam_appid_from_url,
)

for _mod_name in _added_stubs:
    del sys.modules[_mod_name]


def _make_iterable():
    return ShortcutsSourceIterable(ShortcutsSource())


class CmdSafeTests(unittest.TestCase):
    def test_accepts_plain_paths_and_urls(self):
        self.assertTrue(cmd_safe(r"C:\Games\Doom\doom.exe"))
        self.assertTrue(cmd_safe("steam://run/440"))
        self.assertTrue(cmd_safe("com.epicgames.launcher://apps/ABC?action=launch"))

    def test_rejects_quotes_and_control_chars(self):
        self.assertFalse(cmd_safe('C:\\game.exe" & calc.exe'))
        self.assertFalse(cmd_safe("steam://run/440\ncalc.exe"))
        self.assertFalse(cmd_safe("a\x00b"))


class ArgsSafeTests(unittest.TestCase):
    def test_accepts_plain_arguments(self):
        self.assertTrue(args_safe("-windowed -novid +exec autoexec"))
        self.assertTrue(args_safe(""))

    def test_rejects_unquoted_metacharacters(self):
        self.assertFalse(args_safe("& calc.exe"))
        self.assertFalse(args_safe("game.exe|calc.exe"))
        self.assertFalse(args_safe("a > b"))
        self.assertFalse(args_safe("(calc)"))

    def test_accepts_quoted_metacharacters(self):
        # GOG / Battle.net / emulator style, quoted runs are literal for cmd
        self.assertTrue(args_safe('/path="D:\\GOG Games\\X"'))
        self.assertTrue(args_safe('--exec="launch Pro"'))
        self.assertTrue(args_safe('"C:\\ROMs\\Game (USA).sfc"'))

    def test_rejects_unbalanced_quotes_and_expansions(self):
        self.assertFalse(args_safe('"unbalanced'))
        self.assertFalse(args_safe("%WINDIR%\\game"))
        self.assertFalse(args_safe("!var!"))


class SteamAppidTests(unittest.TestCase):
    def test_extracts_plain_appids(self):
        self.assertEqual(steam_appid_from_url("steam://run/440"), "440")
        self.assertEqual(steam_appid_from_url("steam://rungameid/620"), "620")

    def test_rejects_composite_and_foreign_urls(self):
        self.assertIsNone(steam_appid_from_url("steam://rungameid/12345678901234567"))
        self.assertIsNone(steam_appid_from_url("com.epicgames.launcher://x"))
        self.assertIsNone(steam_appid_from_url(""))
        self.assertIsNone(steam_appid_from_url(None))


class GameIdTests(unittest.TestCase):
    def test_id_is_stable_for_a_fixed_identity(self):
        iterable = _make_iterable()
        first = iterable._game_id("steam://run/440")
        self.assertEqual(first, iterable._game_id("steam://run/440"))
        expected = "shortcuts_" + sha256("steam://run/440".encode()).hexdigest()[:16]
        self.assertEqual(first, expected)

    def test_distinct_identities_hash_distinctly(self):
        iterable = _make_iterable()
        self.assertNotEqual(
            iterable._game_id("steam://run/440"), iterable._game_id("steam://run/440 ")
        )


class BuildFromUrlTests(unittest.TestCase):
    def _write_url(self, directory, stem, url):
        entry = Path(directory) / f"{stem}.url"
        entry.write_text(f"[InternetShortcut]\nURL={url}\n", encoding="utf-8")
        return entry

    def test_steam_url_builds_game_with_appid(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = self._write_url(tmp, "Team Fortress 2", "steam://run/440")
            iterable = _make_iterable()
            result = iterable.build_from_url(entry)
            self.assertIsNotNone(result)
            game, additional = result
            self.assertEqual(game.values["executable"], 'start "" "steam://run/440"')
            self.assertEqual(additional["steam_appid"], "440")
            self.assertEqual(additional["identity_anchor"], str(entry))
            self.assertEqual(game.values["shortcut_path"], str(entry))
            self.assertIsInstance(game.values["shortcut_mtime"], int)
            self.assertEqual(
                game.values["game_id"], iterable._game_id("steam://run/440")
            )

    def test_web_bookmark_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = self._write_url(tmp, "Store", "https://example.com/game")
            self.assertIsNone(_make_iterable().build_from_url(entry))

    def test_unsafe_url_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = self._write_url(tmp, "Evil", 'steam://run/440" & calc.exe')
            self.assertIsNone(_make_iterable().build_from_url(entry))

    def test_non_game_name_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = self._write_url(tmp, "CoolGame Uninstall", "steam://run/440")
            self.assertIsNone(_make_iterable().build_from_url(entry))


class BuildFromLnkTests(unittest.TestCase):
    def test_classic_target_uses_file_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "game.exe"
            target.write_bytes(b"x")
            entry = Path(tmp) / "MyGame.lnk"
            entry.write_bytes(b"x")
            data = {
                "Target": str(target),
                "Arguments": "-windowed",
                "Icon": "",
                "WorkingDirectory": tmp,
                "Aumid": "",
            }
            result = _make_iterable().build_from_lnk(entry, data)
            self.assertIsNotNone(result)
            game, additional = result
            self.assertIn(f'"{target}"', game.values["executable"])
            self.assertIn("-windowed", game.values["executable"])
            self.assertEqual(additional["identity_anchor"], str(entry))
            self.assertEqual(game.values["shortcut_path"], str(entry))

    def test_unsafe_target_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = Path(tmp) / "MyGame.lnk"
            entry.write_bytes(b"x")
            data = {
                "Target": 'C:\\game.exe" & calc.exe',
                "Arguments": "",
                "Icon": "",
                "WorkingDirectory": "",
                "Aumid": "",
            }
            self.assertIsNone(_make_iterable().build_from_lnk(entry, data))

    def test_unsafe_arguments_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "game.exe"
            target.write_bytes(b"x")
            entry = Path(tmp) / "MyGame.lnk"
            entry.write_bytes(b"x")
            data = {
                "Target": str(target),
                "Arguments": "& calc.exe",
                "Icon": "",
                "WorkingDirectory": "",
                "Aumid": "",
            }
            self.assertIsNone(_make_iterable().build_from_lnk(entry, data))

    def test_uwp_aumid_launches_through_apps_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = Path(tmp) / "Halo.lnk"
            entry.write_bytes(b"x")
            aumid = "Microsoft.Halo_8wekyb3d8bbwe!Halo"
            data = {
                "Target": "",
                "Arguments": "",
                "Icon": "",
                "WorkingDirectory": "",
                "Aumid": aumid,
            }
            result = _make_iterable().build_from_lnk(entry, data)
            self.assertIsNotNone(result)
            game, _additional = result
            self.assertEqual(
                game.values["executable"], f"explorer.exe shell:AppsFolder\\{aumid}"
            )
            self.assertEqual(
                game.values["game_id"], _make_iterable()._game_id(f"uwp:{aumid}")
            )

    def test_http_target_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = Path(tmp) / "Link.lnk"
            entry.write_bytes(b"x")
            data = {
                "Target": "https://example.com/game",
                "Arguments": "",
                "Icon": "",
                "WorkingDirectory": "",
                "Aumid": "",
            }
            self.assertIsNone(_make_iterable().build_from_lnk(entry, data))


class FolderPolicyTests(unittest.TestCase):
    def test_source_metadata(self):
        self.assertEqual(ShortcutsSource.source_id, "shortcuts")
        self.assertEqual(ShortcutsSource.available_on, {"win32"})
        self.assertIs(ShortcutsSource.iterable_class, ShortcutsSourceIterable)

    @unittest.skipIf(sys.platform == "win32", "Linux-only behaviour")
    def test_folder_helper_returns_empty_on_linux(self):
        from cartridges.importer import shortcuts_source as module

        self.assertEqual(module._shortcuts_folder_candidates(), [])
        self.assertEqual(atalhos_da_pasta(), [])
        self.assertFalse(module._shortcuts_recursive())
        self.assertFalse(ShortcutsSource().is_available)


if __name__ == "__main__":
    unittest.main()
