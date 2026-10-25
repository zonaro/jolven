import builtins
import subprocess
import tempfile
import unittest
from pathlib import Path

from cartridges.utils import browser as browsers_module
from cartridges.utils.browser import (
    Browser,
    classify_browser,
    default_browser,
    detect_browsers,
    kiosk_command,
    launch_kiosk,
    profile_dir_for,
    resolve_browser,
)

builtins._ = lambda text: text  # type: ignore[assignment]


class FakeAppInfo:
    def __init__(self, desktop_id, name, executable, commandline=""):
        self._id = desktop_id
        self._name = name
        self._executable = executable
        self._commandline = commandline

    def get_id(self):
        return self._id

    def get_display_name(self):
        return self._name

    def get_executable(self):
        return self._executable

    def get_commandline(self):
        return self._commandline


def fake_which(mapping):
    def which(binary):
        return mapping.get(binary)

    return which


NATIVE_EDGE = FakeAppInfo(
    "com.microsoft.Edge.desktop",
    "Microsoft Edge",
    "/usr/bin/microsoft-edge-stable",
    "/usr/bin/microsoft-edge-stable %U",
)
DUPLICATE_EDGE = FakeAppInfo(
    "microsoft-edge.desktop",
    "Microsoft Edge",
    "/usr/bin/microsoft-edge-stable",
    "/usr/bin/microsoft-edge-stable %U",
)
FLATPAK_FIREFOX = FakeAppInfo(
    "org.mozilla.firefox.desktop",
    "Firefox",
    "/usr/bin/flatpak",
    "/usr/bin/flatpak run --branch=stable org.mozilla.firefox %u",
)
CHATGPT = FakeAppInfo(
    "chatgpt.desktop", "ChatGPT", "chatgpt", "chatgpt %U"
)
DMS = FakeAppInfo("dms-open.desktop", "DMS", "dms", "dms %U")


class ClassifyTests(unittest.TestCase):
    def test_families(self):
        self.assertEqual(classify_browser("Google Chrome"), "chromium")
        self.assertEqual(classify_browser("org.chromium.Chromium"), "chromium")
        self.assertEqual(classify_browser("Brave Browser"), "chromium")
        self.assertEqual(classify_browser("Mozilla Firefox"), "firefox")
        self.assertEqual(classify_browser("LibreWolf"), "firefox")
        self.assertEqual(classify_browser("GNOME Web"), "other")
        self.assertEqual(classify_browser(""), "other")


class DetectTests(unittest.TestCase):
    def test_gio_entries_are_deduplicated_and_non_browsers_dropped(self):
        result = detect_browsers(
            app_infos=[NATIVE_EDGE, DUPLICATE_EDGE, CHATGPT, DMS],
            which=fake_which({}),
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "com.microsoft.Edge")
        self.assertEqual(result[0].kind, "chromium")
        self.assertTrue(result[0].kiosk)
        self.assertEqual(result[0].command, ("/usr/bin/microsoft-edge-stable",))

    def test_flatpak_entry_builds_flatpak_run_command(self):
        result = detect_browsers(app_infos=[FLATPAK_FIREFOX], which=fake_which({}))
        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0].command, ("flatpak", "run", "org.mozilla.firefox")
        )
        self.assertEqual(result[0].kind, "firefox")

    def test_path_binaries_are_detected_with_pretty_names(self):
        result = detect_browsers(
            app_infos=[],
            which=fake_which(
                {
                    "firefox": "/usr/bin/firefox",
                    "chromium": "/usr/bin/chromium",
                }
            ),
        )
        names = {item.name for item in result}
        self.assertEqual(names, {"Firefox", "Chromium"})
        firefox = next(item for item in result if item.name == "Firefox")
        self.assertEqual(firefox.command, ("/usr/bin/firefox",))
        self.assertTrue(firefox.kiosk)

    def test_path_duplicate_of_gio_entry_is_skipped(self):
        result = detect_browsers(
            app_infos=[NATIVE_EDGE],
            which=fake_which({"microsoft-edge-stable": "/usr/bin/microsoft-edge-stable"}),
        )
        self.assertEqual(len(result), 1)
        self.assertIn("Edge", result[0].name)

    def test_unknown_https_handler_is_kept_when_it_mentions_browser(self):
        zen = FakeAppInfo(
            "app.zen_browser.zen.desktop",
            "Zen Browser",
            "/usr/bin/zen-browser",
            "/usr/bin/zen-browser %u",
        )
        result = detect_browsers(app_infos=[zen], which=fake_which({}))
        self.assertEqual(result[0].kind, "other")
        self.assertFalse(result[0].kiosk)

    def test_unresolved_executable_is_ignored(self):
        result = detect_browsers(
            app_infos=[
                FakeAppInfo("org.mozilla.firefox.desktop", "Firefox", "firefox")
            ],
            which=fake_which({}),
        )
        self.assertEqual(result, [])


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.edge = Browser(
            "com.microsoft.Edge",
            "Microsoft Edge",
            "chromium",
            ("/usr/bin/microsoft-edge-stable",),
            True,
        )
        self.firefox = Browser(
            "org.mozilla.firefox",
            "Firefox",
            "firefox",
            ("/usr/bin/firefox",),
            True,
        )

    def test_default_matches_desktop_id(self):
        self.assertEqual(
            default_browser([self.edge, self.firefox], default_app_id="com.microsoft.Edge.desktop"),
            self.edge,
        )

    def test_default_falls_back_to_first(self):
        self.assertEqual(default_browser([self.edge, self.firefox]), self.edge)

    def test_configured_id_wins(self):
        self.assertEqual(
            resolve_browser("org.mozilla.firefox", [self.edge, self.firefox]),
            self.firefox,
        )

    def test_unknown_id_falls_back_to_default(self):
        self.assertEqual(
            resolve_browser("removido", [self.edge, self.firefox], default_app_id="org.mozilla.firefox"),
            self.firefox,
        )

    def test_empty_list_returns_none(self):
        self.assertIsNone(default_browser([]))
        self.assertIsNone(resolve_browser("qualquer", []))


class CommandTests(unittest.TestCase):
    def test_chromium_kiosk_argv(self):
        item = Browser("chrome", "Chrome", "chromium", ("/usr/bin/chrome",), True)
        argv = kiosk_command(item, "https://www.xbox.com/play/launch/ABC", Path("/tmp/p"))
        self.assertEqual(
            argv,
            [
                "/usr/bin/chrome",
                "--user-data-dir=/tmp/p",
                "--no-first-run",
                "--no-default-browser-check",
                "--kiosk",
                "https://www.xbox.com/play/launch/ABC",
            ],
        )

    def test_firefox_kiosk_argv(self):
        item = Browser("firefox", "Firefox", "firefox", ("/usr/bin/firefox",), True)
        argv = kiosk_command(item, "https://www.xbox.com/play/launch/ABC", Path("/tmp/p"))
        self.assertEqual(
            argv,
            [
                "/usr/bin/firefox",
                "-no-remote",
                "-profile",
                "/tmp/p",
                "-kiosk",
                "https://www.xbox.com/play/launch/ABC",
            ],
        )

    def test_other_browser_just_opens_new_window(self):
        item = Browser("epiphany", "Web", "other", ("/usr/bin/epiphany",), False)
        self.assertEqual(
            kiosk_command(item, "https://example.test", Path("/tmp/p")),
            ["/usr/bin/epiphany", "https://example.test"],
        )


class ProfileTests(unittest.TestCase):
    def test_non_flatpak_profile_is_sanitized(self):
        item = Browser("app/zen browser", "Zen", "other", ("/usr/bin/zen",), False)
        self.assertEqual(profile_dir_for(item, Path("/base")), Path("/base/app-zen-browser"))

    def test_flatpak_profile_lives_inside_sandbox_home(self):
        item = Browser(
            "org.mozilla.firefox",
            "Firefox",
            "firefox",
            ("flatpak", "run", "org.mozilla.firefox"),
            True,
        )
        expected = Path.home() / ".local/share/jolven/browser-profiles/org.mozilla.firefox"
        self.assertEqual(profile_dir_for(item), expected)

    def test_flatpak_host_profile_maps_into_var_app(self):
        item = Browser(
            "org.mozilla.firefox",
            "Firefox",
            "firefox",
            ("flatpak", "run", "org.mozilla.firefox"),
            True,
        )
        sandbox = profile_dir_for(item)
        host = browsers_module._host_profile_dir(item, sandbox)
        self.assertEqual(
            host,
            Path.home()
            / ".var/app/org.mozilla.firefox/.local/share/jolven/browser-profiles/org.mozilla.firefox",
        )


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.firefox = Browser(
            "org.mozilla.firefox",
            "Firefox",
            "firefox",
            ("/usr/bin/firefox",),
            True,
        )
        self.url = "https://www.xbox.com/play/launch/ABC"

    def test_launch_builds_command_creates_profile_and_detaches(self):
        calls = []

        def fake_popen(argv, **kwargs):
            calls.append((argv, kwargs))
            return object()

        with tempfile.TemporaryDirectory() as directory:
            ok, message = launch_kiosk(
                "org.mozilla.firefox",
                self.url,
                browsers=[self.firefox],
                popen=fake_popen,
                profile_base=Path(directory),
            )
            profile = Path(directory) / "org.mozilla.firefox"
            self.assertEqual(message, "")
            self.assertTrue(ok)
            self.assertTrue(profile.is_dir())
            self.assertTrue((profile / "user.js").is_file())
        argv, kwargs = calls[0]
        self.assertEqual(argv[-1], self.url)
        self.assertIn("-kiosk", argv)
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertTrue(kwargs["start_new_session"])

    def test_invalid_url_is_rejected_without_spawning(self):
        called = []
        ok, message = launch_kiosk(
            "org.mozilla.firefox",
            "javascript:alert(1)",
            browsers=[self.firefox],
            popen=lambda *args, **kwargs: called.append(args),
        )
        self.assertFalse(ok)
        self.assertTrue(message)
        self.assertEqual(called, [])

    def test_no_browser_reports_clear_message(self):
        called = []
        ok, message = launch_kiosk(
            "",
            self.url,
            browsers=[],
            popen=lambda *args, **kwargs: called.append(args),
        )
        self.assertFalse(ok)
        self.assertIn("navegador", message.casefold())
        self.assertEqual(called, [])

    def test_popen_failure_is_returned_as_message(self):
        def failing_popen(*_args, **_kwargs):
            raise OSError("boom")

        with tempfile.TemporaryDirectory() as directory:
            ok, message = launch_kiosk(
                "org.mozilla.firefox",
                self.url,
                browsers=[self.firefox],
                popen=failing_popen,
                profile_base=Path(directory),
            )
        self.assertFalse(ok)
        self.assertIn("boom", message)


if __name__ == "__main__":
    unittest.main()
