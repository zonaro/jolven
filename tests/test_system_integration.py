# test_system_integration.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for privileged-helper resolution (no GTK, no polkit)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cartridges.platform import system_integration

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
    # root-owned 0755 de um install correto (o dono do teste não pode
    # escrever, então helper_for aceita). 0755 seria gravável pelo dono
    # do teste = arquivo sob controle do usuário = deve ser rejeitado.
    helper.chmod(0o555 if executable else 0o644)
    return helper


class SystemIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        patcher = mock.patch.object(
            system_integration, "POLKIT_ACTION_DIRS", (self.dir,)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_find_policy_present(self):
        expected = write_policy(self.dir, "test.policy", exec_path="/usr/bin/x")
        self.assertEqual(system_integration.find_policy(ACTION), expected)

    def test_find_policy_absent(self):
        self.assertIsNone(system_integration.find_policy(ACTION))

    def test_find_policy_ignores_filename(self):
        # O nome do arquivo pode ser `.Devel.` enquanto a action id é a base:
        # o que vale é o conteúdo parseado, não o nome.
        expected = write_policy(
            self.dir,
            "io.github.zonaro.Jolven.Devel.XCloudDeps.policy",
            exec_path="/usr/bin/x",
        )
        self.assertEqual(system_integration.find_policy(ACTION), expected)

    def test_find_policy_filename_match_does_not_count(self):
        write_policy(
            self.dir,
            "io.github.zonaro.Jolven.XCloudDeps.policy",
            action_id="org.example.Other",
            exec_path="/usr/bin/x",
        )
        self.assertIsNone(system_integration.find_policy(ACTION))

    def test_find_policy_unrelated_action_does_not_count(self):
        write_policy(
            self.dir, "other.policy", action_id="org.example.Other"
        )
        self.assertIsNone(system_integration.find_policy(ACTION))

    def test_find_policy_first_dir_wins(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        first = write_policy(self.dir, "a.policy", exec_path="/usr/bin/a")
        write_policy(other.name, "a.policy", exec_path="/usr/bin/b")
        with mock.patch.object(
            system_integration,
            "POLKIT_ACTION_DIRS",
            (self.dir, Path(other.name)),
        ):
            self.assertEqual(system_integration.find_policy(ACTION), first)

    def test_exec_path_present(self):
        write_policy(self.dir, "a.policy", exec_path="/usr/libexec/helper")
        self.assertEqual(
            system_integration.exec_path(ACTION),
            Path("/usr/libexec/helper"),
        )

    def test_exec_path_absent(self):
        write_policy(self.dir, "a.policy")
        self.assertIsNone(system_integration.exec_path(ACTION))

    def test_exec_path_without_policy(self):
        self.assertIsNone(system_integration.exec_path(ACTION))

    def test_helper_for_executable(self):
        helper = make_helper(self.dir, executable=True)
        write_policy(self.dir, "a.policy", exec_path=str(helper))
        self.assertEqual(system_integration.helper_for(ACTION), helper)

    def test_helper_for_missing_binary(self):
        write_policy(
            self.dir, "a.policy", exec_path=str(self.dir / "no-such-helper")
        )
        self.assertIsNone(system_integration.helper_for(ACTION))

    def test_helper_for_not_executable(self):
        helper = make_helper(self.dir, executable=False)
        write_policy(self.dir, "a.policy", exec_path=str(helper))
        self.assertIsNone(system_integration.helper_for(ACTION))

    def test_helper_for_user_writable_is_none(self):
        # Arquivo sob controle do usuário (gravável por quem invoca):
        # mesmo executável, helper_for deve rejeitar (fail-closed).
        helper = make_helper(self.dir)
        helper.chmod(0o755)
        write_policy(self.dir, "a.policy", exec_path=str(helper))
        self.assertIsNone(system_integration.helper_for(ACTION))

    def test_helper_for_without_policy(self):
        self.assertIsNone(system_integration.helper_for(ACTION))

    def test_broken_xml_is_none(self):
        broken = self.dir / "broken.policy"
        broken.write_text("<policyconfig><action id=", encoding="utf-8")
        self.assertIsNone(system_integration.find_policy(ACTION))
        self.assertIsNone(system_integration.exec_path(ACTION))
        self.assertIsNone(system_integration.helper_for(ACTION))

    def test_policy_path_as_directory_is_none(self):
        (self.dir / "dir.policy").mkdir()
        self.assertIsNone(system_integration.find_policy(ACTION))
        self.assertIsNone(system_integration.exec_path(ACTION))
        self.assertIsNone(system_integration.helper_for(ACTION))


if __name__ == "__main__":
    unittest.main()
