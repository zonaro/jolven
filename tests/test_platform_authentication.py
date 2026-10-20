# test_platform_authentication.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for the Preferences authentication gate (no GTK, no polkit)."""

import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

from cartridges.platform import authentication
from cartridges.platform.authentication import (
    AUTH_ACTION_ID,
    AuthOutcome,
    authenticate,
    outcome_from_exit_code,
    parse_proc_stat_starttime,
    pkcheck_argv,
    policy_installed,
    process_subject,
    read_process_starttime,
    windows_outcome_from_availability,
    windows_outcome_from_result,
    windows_should_prompt,
)


class ExitCodeTests(unittest.TestCase):
    def test_authorized(self) -> None:
        self.assertEqual(outcome_from_exit_code(0), AuthOutcome.AUTHORIZED)

    def test_denied(self) -> None:
        self.assertEqual(outcome_from_exit_code(1), AuthOutcome.DENIED)
        self.assertEqual(outcome_from_exit_code(3), AuthOutcome.DENIED)

    def test_unavailable(self) -> None:
        for code in (2, 126, 127):
            with self.subTest(code=code):
                self.assertEqual(
                    outcome_from_exit_code(code), AuthOutcome.UNAVAILABLE
                )


class ActionIdTests(unittest.TestCase):
    def test_action_id(self) -> None:
        self.assertEqual(
            AUTH_ACTION_ID, "io.github.zonaro.Jolven.preferences"
        )


class ArgvTests(unittest.TestCase):
    def test_pkcheck_argv(self) -> None:
        subject = process_subject(1234, 1000, 987654)
        self.assertEqual(subject, "1234,987654,1000")
        argv = pkcheck_argv(AUTH_ACTION_ID, subject)
        self.assertIn("--action-id", argv)
        self.assertIn(AUTH_ACTION_ID, argv)
        self.assertIn("--allow-user-interaction", argv)
        self.assertIn("--process", argv)
        index = argv.index("--process")
        self.assertEqual(argv[index + 1], "1234,987654,1000")


class ProcStatTests(unittest.TestCase):
    def test_comm_with_spaces_and_parens(self) -> None:
        # Fields after `)`: state + 19 more, with starttime (field 22)
        # at index 19 of the remainder.
        after = ["R", "1", "2", "3", "4", "5", "6", "7", "8", "9"] + [
            "10",
            "11",
            "12",
            "13",
            "14",
            "15",
            "16",
            "17",
            "18",
            "987654",
            "19",
        ]
        line = f"1234 (my (fancy) app) {' '.join(after)}"
        self.assertEqual(parse_proc_stat_starttime(line), 987654)

    def test_malformed_stat_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_proc_stat_starttime("no parens here")

    def test_missing_proc_entry_is_none(self) -> None:
        self.assertIsNone(read_process_starttime(2**30))


class PolicyInstalledTests(unittest.TestCase):
    def test_absent_policy(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(policy_installed([Path(tmp)]))

    def test_present_policy(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            policy = Path(tmp) / "io.github.zonaro.Jolven.Preferences.policy"
            policy.write_text(
                f'<action id="{AUTH_ACTION_ID}"></action>',
                encoding="utf-8",
            )
            self.assertTrue(policy_installed([Path(tmp)]))

    def test_unrelated_policy_does_not_count(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            policy = Path(tmp) / "other.policy"
            policy.write_text('<action id="org.example.Other"></action>')
            self.assertFalse(policy_installed([Path(tmp)]))


class AuthenticateLinuxTests(unittest.TestCase):
    def _patched(self, run_effect):
        policy = mock.patch.object(
            authentication, "policy_installed", return_value=True
        )
        subject = mock.patch.object(
            authentication, "current_process_subject", return_value="1,2,3"
        )
        run = mock.patch.object(
            authentication.subprocess, "run", side_effect=run_effect
        )
        return policy, subject, run

    def test_missing_pkcheck_is_unavailable(self) -> None:
        policy, subject, run = self._patched(FileNotFoundError("pkcheck"))
        with policy, subject, run:
            self.assertEqual(authenticate("motivo"), AuthOutcome.UNAVAILABLE)

    def test_timeout_is_denied(self) -> None:
        # The prompt was shown and got no yes: staying silent must not
        # defeat the gate.
        policy, subject, run = self._patched(
            subprocess.TimeoutExpired(cmd="pkcheck", timeout=1)
        )
        with policy, subject, run:
            self.assertEqual(authenticate("motivo"), AuthOutcome.DENIED)

    def test_missing_policy_never_spawns_pkcheck(self) -> None:
        with mock.patch.object(
            authentication, "policy_installed", return_value=False
        ), mock.patch.object(
            authentication.subprocess,
            "run",
            side_effect=AssertionError("must not spawn pkcheck"),
        ):
            self.assertEqual(authenticate("motivo"), AuthOutcome.UNAVAILABLE)

    def test_exit_zero_is_authorized(self) -> None:
        policy, subject, _run = self._patched(None)
        with policy, subject, mock.patch.object(
            authentication.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0),
        ):
            self.assertEqual(authenticate("motivo"), AuthOutcome.AUTHORIZED)

    def test_exit_one_is_denied(self) -> None:
        with mock.patch.object(
            authentication, "policy_installed", return_value=True
        ), mock.patch.object(
            authentication, "current_process_subject", return_value="1,2,3"
        ), mock.patch.object(
            authentication.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=1),
        ):
            self.assertEqual(authenticate("motivo"), AuthOutcome.DENIED)

    def test_no_subject_is_unavailable(self) -> None:
        with mock.patch.object(
            authentication, "policy_installed", return_value=True
        ), mock.patch.object(
            authentication, "current_process_subject", return_value=None
        ), mock.patch.object(
            authentication.subprocess,
            "run",
            side_effect=AssertionError("must not spawn pkcheck"),
        ):
            self.assertEqual(authenticate("motivo"), AuthOutcome.UNAVAILABLE)


class WindowsMappingTests(unittest.TestCase):
    def test_should_prompt_only_when_available(self) -> None:
        self.assertTrue(windows_should_prompt(0))
        for value in (1, 2, 3, 4):
            with self.subTest(value=value):
                self.assertFalse(windows_should_prompt(value))

    def test_availability_mapping(self) -> None:
        self.assertIsNone(windows_outcome_from_availability(0))
        for value in (1, 2, 3, 4):
            with self.subTest(value=value):
                self.assertEqual(
                    windows_outcome_from_availability(value),
                    AuthOutcome.UNAVAILABLE,
                )

    def test_result_mapping(self) -> None:
        self.assertEqual(
            windows_outcome_from_result(0), AuthOutcome.AUTHORIZED
        )
        for value in (1, 2, 3, 4):
            with self.subTest(value=value):
                self.assertEqual(
                    windows_outcome_from_result(value),
                    AuthOutcome.UNAVAILABLE,
                )
        for value in (5, 6):
            with self.subTest(value=value):
                self.assertEqual(
                    windows_outcome_from_result(value), AuthOutcome.DENIED
                )


class PolicyTests(unittest.TestCase):
    def test_preferences_policy_is_valid_xml(self) -> None:
        import xml.dom.minidom
        from pathlib import Path

        policy = (
            Path(__file__).parents[1]
            / "data"
            / "io.github.zonaro.Jolven.Preferences.policy.in"
        )
        dom = xml.dom.minidom.parse(str(policy))
        actions = dom.getElementsByTagName("action")
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].getAttribute("id"), AUTH_ACTION_ID)
        text = policy.read_text()
        self.assertIn("auth_admin_keep", text)
        self.assertNotIn("org.freedesktop.policykit.exec.path", text)


if __name__ == "__main__":
    unittest.main()
