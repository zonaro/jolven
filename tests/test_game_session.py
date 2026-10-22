# test_game_session.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for the Jolven Session helper wrapper (no GTK, no polkit)."""

import builtins
import io
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

import cartridges.game_session as game_session
from cartridges.platform import system_integration

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

ACTION = "io.github.zonaro.Jolven.configure-game-mode"


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


def make_helper(directory, name="jolven-game-mode-setup", executable=True):
    helper = Path(directory) / name
    helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    # 0555 = executável e NÃO gravável pelo dono: simula o helper
    # root-owned 0755 de um install correto. 0755 seria gravável pelo
    # dono do teste = arquivo sob controle do usuário = rejeitado.
    helper.chmod(0o555 if executable else 0o644)
    return helper


class FakeProc:
    """Processo falso: stdout controlado e código de saída escolhido."""

    def __init__(self, stdout_text="", returncode=0, timeout=False):
        self.stdout = io.StringIO(stdout_text)
        self.returncode = returncode
        self.killed = False
        self._timeout = timeout

    def wait(self, timeout=None):
        if self._timeout:
            raise subprocess.TimeoutExpired(cmd="pkexec", timeout=timeout)
        return self.returncode

    def kill(self):
        self.killed = True


class GameSessionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        patcher = mock.patch.object(
            system_integration, "POLKIT_ACTION_DIRS", (self.dir,)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_action_id_matches_policy(self):
        self.assertEqual(game_session.GAME_MODE_ACTION_ID, ACTION)
        self.assertEqual(game_session.HELPER_OPERATIONS, ("install", "uninstall"))

    def test_helper_available_and_reason(self):
        # Sem policy: helper ausente e o motivo vem da fonte única.
        self.assertFalse(game_session.helper_available())
        reason = game_session.unavailable_reason()
        self.assertEqual(reason, system_integration.unavailable_message())
        self.assertNotIn("sudo", reason)
        self.assertNotIn("scripts", reason)

        helper = make_helper(self.dir, executable=True)
        write_policy(self.dir, "test.policy", exec_path=str(helper))
        self.assertTrue(game_session.helper_available())
        self.assertIsNone(game_session.unavailable_reason())

    def test_helper_none_when_user_writable(self):
        # Fail-closed: helper gravável por quem invoca é rejeitado.
        helper = make_helper(self.dir, executable=True)
        helper.chmod(0o755)
        write_policy(self.dir, "test.policy", exec_path=str(helper))
        self.assertFalse(game_session.helper_available())

    def test_setup_without_helper_returns_false(self):
        with patch.object(game_session, "_helper_path", return_value=None):
            called = []
            self.assertFalse(game_session.setup_async("install", called.append))
            self.assertEqual(called, [])

    def test_setup_with_invalid_operation_does_nothing(self):
        with (
            patch.object(game_session, "_helper_path", return_value=Path("/tmp/helper")),
            patch.object(game_session.shutil, "which", return_value="/usr/bin/pkexec"),
            patch.object(game_session.subprocess, "Popen") as popen,
            self.assertLogs(game_session.logger, level="ERROR"),
        ):
            called = []
            self.assertFalse(game_session.setup_async("purge", called.append))
            self.assertEqual(called, [])
            popen.assert_not_called()

    def _run_setup(
        self,
        operation="install",
        stdout="",
        returncode=0,
        timeout=False,
        on_output=None,
    ):
        """Roda `setup_async` com um processo falso e devolve o callback."""
        results = []
        done = threading.Event()

        def _done(ok, message):
            results.append((ok, message))
            done.set()

        proc = FakeProc(stdout_text=stdout, returncode=returncode, timeout=timeout)
        with (
            patch.object(
                game_session, "_helper_path", return_value=Path("/tmp/helper")
            ),
            patch.object(game_session.shutil, "which", return_value="/usr/bin/pkexec"),
            patch.object(game_session.subprocess, "Popen", return_value=proc) as popen,
        ):
            started = game_session.setup_async(operation, _done, on_output=on_output)
        self.assertTrue(started)
        self.assertTrue(done.wait(timeout=10), "o callback não chegou")
        popen.assert_called_once()
        return results, proc, popen

    def test_setup_success_calls_back_with_success(self):
        results, _proc, _popen = self._run_setup(
            operation="install", stdout="Jolven Session installed.\n"
        )
        self.assertEqual(len(results), 1)
        ok, message = results[0]
        self.assertTrue(ok)
        self.assertEqual(
            message, "Jolven Session installed. It will appear at the next login."
        )

    def test_setup_success_uninstall(self):
        results, _proc, _popen = self._run_setup(
            operation="uninstall", stdout="Jolven Session removed.\n"
        )
        ok, message = results[0]
        self.assertTrue(ok)
        self.assertEqual(message, "Jolven Session uninstalled")

    def test_setup_runs_pkexec_with_the_helper_and_operation(self):
        _results, _proc, popen = self._run_setup(operation="uninstall")
        command = popen.call_args[0][0]
        self.assertEqual(
            command, ["/usr/bin/pkexec", "/tmp/helper", "uninstall"]
        )

    def test_setup_failure_calls_back_with_error(self):
        results, _proc, _popen = self._run_setup(
            stdout="Error: the display manager user cannot execute it\n",
            returncode=70,
        )
        ok, message = results[0]
        self.assertFalse(ok)
        self.assertIn("cannot execute", message)

    def test_setup_cancelled_is_reported(self):
        results, _proc, _popen = self._run_setup(
            stdout="Error executing command as another user: Request dismissed\n",
            returncode=126,
        )
        ok, message = results[0]
        self.assertFalse(ok)
        self.assertIn("cancel", message.lower())

    def test_setup_streams_output_lines(self):
        seen = []
        results, _proc, _popen = self._run_setup(
            stdout="linha um\n\nlinha dois\n", on_output=seen.append
        )
        self.assertEqual(seen, ["linha um", "linha dois"])
        self.assertTrue(results[0][0])

    def test_setup_timeout_fails_and_kills_the_process(self):
        results, proc, _popen = self._run_setup(timeout=True)
        ok, message = results[0]
        self.assertFalse(ok)
        self.assertIn("tempo", message.lower())
        self.assertTrue(proc.killed)

    def test_setup_without_pkexec_does_not_start(self):
        with (
            patch.object(
                game_session, "_helper_path", return_value=Path("/tmp/helper")
            ),
            patch.object(game_session.shutil, "which", return_value=None),
            patch.object(game_session.subprocess, "Popen") as popen,
            self.assertLogs(game_session.logger, level="ERROR"),
        ):
            called = []
            self.assertFalse(game_session.setup_async("install", called.append))
            self.assertEqual(called, [])
            popen.assert_not_called()

    def test_session_installed_true(self):
        session = self.dir / "io.github.zonaro.Jolven.GameMode.desktop"
        session.write_text("[Desktop Entry]\n", encoding="utf-8")
        with patch.object(game_session, "_session_file", return_value=session):
            self.assertTrue(game_session.session_installed())

    def test_session_installed_false(self):
        with patch.object(
            game_session, "_session_file", return_value=self.dir / "missing.desktop"
        ):
            self.assertFalse(game_session.session_installed())

    def test_session_installed_without_shared(self):
        # Sem `cartridges.shared` (fonte gerada, precisa de GTK) a verificação
        # falha sem estourar: a sessão é tratada como ausente.
        with patch.object(
            game_session, "_session_file", side_effect=ImportError("shared")
        ):
            self.assertFalse(game_session.session_installed())

    def test_module_does_not_import_gi(self):
        # O módulo precisa ser importável sem GTK instalado.
        source = Path(game_session.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import gi", source)


if __name__ == "__main__":
    unittest.main()
