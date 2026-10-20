import builtins
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

import cartridges.xcloud_deps as deps
from cartridges.platform import system_integration

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

ACTION = "io.github.zonaro.Jolven.install-xcloud-deps"


def write_policy(directory, filename, action_id=ACTION, exec_path=None):
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<policyconfig>",
        f'  <action id="{action_id}">',
        "    <description>test</description>",
        "    <message>test</message>",
        "    <defaults>",
        "      <allow_any>no</allow_any>",
        "      <allow_inactive>no</allow_inactive>",
        "      <allow_active>auth_admin_keep</allow_active>",
        "    </defaults>",
    ]
    if exec_path is not None:
        lines.append(
            '    <annotate key="org.freedesktop.policykit.exec.path">'
            f"{exec_path}</annotate>"
        )
    lines += ["  </action>", "</policyconfig>"]
    path = Path(directory) / filename
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def make_helper(directory, name="jolven-xcloud-deps", executable=True):
    helper = Path(directory) / name
    helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    # 0555 = executável e NÃO gravável pelo dono: simula o helper
    # root-owned 0755 de um install correto. 0755 seria gravável pelo
    # dono do teste = arquivo sob controle do usuário = rejeitado.
    helper.chmod(0o555 if executable else 0o644)
    return helper


class FakeRegistry:
    def __init__(self, available):
        self._available = set(available)

    def find_feature(self, name, _kind):
        return object() if name in self._available else None


class FakeGst:
    ElementFactory = object()
    available = set()

    @staticmethod
    def init(_args):
        return None

    class Registry:
        @staticmethod
        def get():
            return FakeRegistry(FakeGst.available)


class XCloudDepsTests(unittest.TestCase):
    def test_missing_reports_absent_elements(self):
        with patch.object(deps, "_Gst", FakeGst):
            FakeGst.available = {"nicesrc"}
            self.assertEqual(
                deps.missing_elements(("nicesrc", "nicesink")), ["nicesink"]
            )

    def test_nothing_missing_when_all_present(self):
        with patch.object(deps, "_Gst", FakeGst):
            FakeGst.available = {"nicesrc", "nicesink"}
            self.assertEqual(
                deps.missing_elements(("nicesrc", "nicesink")), []
            )

    def test_everything_missing_without_gst(self):
        with patch.object(deps, "_Gst", None):
            self.assertEqual(
                deps.missing_elements(("nicesrc", "nicesink")),
                ["nicesrc", "nicesink"],
            )

    def test_default_probe_requires_sctp_and_a_decoder(self):
        with patch.object(deps, "_Gst", FakeGst):
            FakeGst.available = set(deps.REQUIRED_ELEMENTS)
            self.assertEqual(deps.missing_elements(), ["h264-decoder"])
            FakeGst.available.add("openh264dec")
            self.assertEqual(deps.missing_elements(), [])

    def test_helper_resolved_from_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper = make_helper(tmp, executable=True)
            write_policy(tmp, "test.policy", exec_path=str(helper))
            with mock.patch.object(
                system_integration, "POLKIT_ACTION_DIRS", (Path(tmp),)
            ):
                self.assertEqual(deps._helper_path(), helper)

    def test_helper_none_without_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                system_integration, "POLKIT_ACTION_DIRS", (Path(tmp),)
            ):
                self.assertIsNone(deps._helper_path())
                self.assertFalse(deps.policy_registered())

    def test_helper_ignores_repo_session_fallback(self):
        # Fail-closed: mesmo existindo `session/jolven-xcloud-deps.in` no
        # repositório, sem policy instalada o helper é None.
        repo_fallback = (
            Path(__file__).parents[1] / "session" / "jolven-xcloud-deps.in"
        )
        self.assertTrue(repo_fallback.is_file())
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                system_integration, "POLKIT_ACTION_DIRS", (Path(tmp),)
            ):
                self.assertIsNone(deps._helper_path())

    def test_helper_none_when_not_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper = make_helper(tmp, executable=False)
            write_policy(tmp, "test.policy", exec_path=str(helper))
            with mock.patch.object(
                system_integration, "POLKIT_ACTION_DIRS", (Path(tmp),)
            ):
                self.assertIsNone(deps._helper_path())

    def test_helper_none_when_user_writable(self):
        # Arquivo sob controle do usuário (gravável por quem invoca):
        # mesmo executável, o helper deve ser rejeitado (fail-closed).
        with tempfile.TemporaryDirectory() as tmp:
            helper = make_helper(tmp, executable=True)
            helper.chmod(0o755)
            write_policy(tmp, "test.policy", exec_path=str(helper))
            with mock.patch.object(
                system_integration, "POLKIT_ACTION_DIRS", (Path(tmp),)
            ):
                self.assertIsNone(deps._helper_path())

    def test_policy_registered_matches_action_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_policy(
                tmp,
                "io.github.zonaro.Jolven.Devel.XCloudDeps.policy",
                exec_path="/usr/bin/x",
            )
            with mock.patch.object(
                system_integration, "POLKIT_ACTION_DIRS", (Path(tmp),)
            ):
                self.assertTrue(deps.policy_registered())

    def test_unavailable_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                system_integration, "POLKIT_ACTION_DIRS", (Path(tmp),)
            ):
                reason = deps.unavailable_reason()
                self.assertIsInstance(reason, str)
                self.assertNotIn("scripts", reason)
                self.assertNotIn("sudo", reason)
                self.assertFalse(deps.helper_available())
            helper = make_helper(tmp, executable=True)
            write_policy(tmp, "test.policy", exec_path=str(helper))
            with mock.patch.object(
                system_integration, "POLKIT_ACTION_DIRS", (Path(tmp),)
            ):
                self.assertIsNone(deps.unavailable_reason())
                self.assertTrue(deps.helper_available())

    def test_install_without_helper_returns_false(self):
        with patch.object(deps, "_helper_path", return_value=None):
            called = []
            self.assertFalse(deps.install_async(called.append))
            self.assertEqual(called, [])

    def test_output_streams_line_by_line(self):
        import io
        import threading

        class FakeStdout(io.StringIO):
            pass

        class FakeProc:
            def __init__(self):
                self.stdout = io.StringIO("linha um\n\nlinha dois\n")
                self.returncode = 0

            def wait(self, timeout=None):
                self.stdout.seek(0)
                return self.returncode

        seen_lines = []
        results = []
        started = threading.Event()

        real_popen = deps.subprocess.Popen

        def fake_popen(*args, **kwargs):
            started.set()
            return FakeProc()

        with (
            patch.object(deps, "_helper_path", return_value="/tmp/helper"),
            patch.object(deps.shutil, "which", return_value="/usr/bin/pkexec"),
            patch.object(deps.subprocess, "Popen", side_effect=fake_popen),
        ):
            self.assertTrue(
                deps.install_async(
                    lambda ok, msg: results.append((ok, msg)),
                    on_output=seen_lines.append,
                )
            )
            self.assertTrue(started.wait(timeout=5))
            deadline = 50
            while not results and deadline > 0:
                import time as _time

                _time.sleep(0.1)
                deadline -= 1
        self.assertEqual(seen_lines, ["linha um", "linha dois"])
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0][0])

    def test_build_restart_command_relaunches_argv(self):
        cmd = deps.build_restart_command(["/home/u/.local/bin/jolven", "--game-mode"])
        self.assertEqual(cmd[:3], ["setsid", "nohup", "sh"])
        self.assertIn("sleep 2", cmd[4])
        self.assertIn("/home/u/.local/bin/jolven", cmd[4])
        self.assertIn("--game-mode", cmd[4])

    def test_policy_file_is_valid_xml(self):
        import xml.dom.minidom

        policy = (
            Path(__file__).parents[1]
            / "data"
            / "io.github.zonaro.Jolven.XCloudDeps.policy.in"
        )
        dom = xml.dom.minidom.parse(str(policy))
        actions = dom.getElementsByTagName("action")
        self.assertEqual(len(actions), 1)
        self.assertEqual(
            actions[0].getAttribute("id"),
            "io.github.zonaro.Jolven.install-xcloud-deps",
        )

    def test_helper_rejects_arbitrary_operations(self):
        helper = (
            Path(__file__).parents[1] / "session" / "jolven-xcloud-deps.in"
        ).read_text()
        self.assertIn('"$action" != install-xcloud-deps', helper)
        self.assertIn("EUID", helper)
        self.assertIn("libnice-gstreamer1", helper)


if __name__ == "__main__":
    unittest.main()
