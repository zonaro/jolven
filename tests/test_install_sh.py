import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
DATA_DIR = REPO_ROOT / "data"

HELPERS = ("jolven-game-mode-setup",)

POLICIES = (
    (
        "io.github.zonaro.Jolven.GameMode.policy",
        "io.github.zonaro.Jolven.configure-game-mode",
    ),
    (
        "io.github.zonaro.Jolven.Preferences.policy",
        "io.github.zonaro.Jolven.preferences",
    ),
)

BASH = shutil.which("bash") or "/bin/bash"


def _promote_function(text):
    lines = text.splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.startswith("promote_system_integration()")
    )
    end = next(i for i in range(start, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start : end + 1])


class InstallShContractTests(unittest.TestCase):
    def test_promotes_exactly_the_helper_with_mode_0755(self):
        text = INSTALL_SH.read_text(encoding="utf-8")
        function = _promote_function(text)
        self.assertIn("for helper in jolven-game-mode-setup", function)
        self.assertIn("-m 0755", function)
        # Only the helper is installed or removed; the search-provider
        # is merely mentioned in a comment explaining it stays in place.
        for line in function.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "install " in line or stripped.startswith("rm ") or " rm " in line:
                self.assertNotIn("jolven-search-provider", line)
                self.assertNotIn("jolven-session", line)
        self.assertIn(
            'rm -f -- "$src_prefix/libexec/jolven-game-mode-setup"',
            function,
        )

    def test_installs_the_two_policies_with_mode_0644(self):
        text = INSTALL_SH.read_text(encoding="utf-8")
        function = _promote_function(text)
        for policy, action in POLICIES:
            self.assertIn(policy, function)
            self.assertIn(action, function)
        self.assertIn("-m 0644", function)

    def test_never_removes_search_provider_or_session_launcher(self):
        text = INSTALL_SH.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"(?m)^[^#]*\brm\b.*jolven-search-provider")
        self.assertNotRegex(text, r"(?m)^[^#]*\brm\b.*jolven-session")

    def test_skips_promotion_for_system_prefixes(self):
        text = INSTALL_SH.read_text(encoding="utf-8")
        function = _promote_function(text)
        self.assertIn("$src_prefix == /usr", function)
        self.assertIn("$src_prefix == /usr/local", function)
        self.assertIn("promocao dispensada", function)

    def test_has_no_dead_top_level_destination_variables(self):
        text = INSTALL_SH.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"(?m)^SYSTEM_LIBEXECDIR=")
        self.assertNotRegex(text, r"(?m)^POLKIT_DIR=")
        function = _promote_function(text)
        self.assertIn("CARTRIDGES_SYSTEM_LIBEXECDIR", function)
        self.assertIn("CARTRIDGES_POLKIT_DIR", function)

    def test_verification_checks_ownership_and_writability(self):
        text = INSTALL_SH.read_text(encoding="utf-8")
        function = _promote_function(text)
        self.assertIn("stat -c '%u'", function)
        self.assertIn("-perm /022", function)
        self.assertIn("-w $exec_path", function)
        self.assertNotIn("-perm -o=w", text)
        self.assertIn("nao pertence a root", function)
        self.assertIn("gravavel por grupo ou outros", function)
        self.assertIn("gravavel pelo usuario corrente", function)

    def test_has_no_legacy_installer_references(self):
        text = INSTALL_SH.read_text(encoding="utf-8")
        self.assertNotIn("scripts/install-", text)
        self.assertNotIn("scripts/uninstall-", text)
        self.assertNotIn("configure_shortcut", text)


def _write_executable(path, content, mode):
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)


class InstallShFunctionalTests(unittest.TestCase):
    def test_promote_only_end_to_end_without_sudo(self):
        with tempfile.TemporaryDirectory(prefix="jolven-promote-test-") as tmp:
            tmp_path = Path(tmp)
            prefix = tmp_path / "prefix"
            sys_dir = tmp_path / "sys"
            polkit_dir = tmp_path / "polkit"
            exec_dir = tmp_path / "exec"

            (prefix / "libexec").mkdir(parents=True)
            (prefix / "bin").mkdir(parents=True)
            (prefix / "share" / "polkit-1" / "actions").mkdir(parents=True)
            sys_dir.mkdir()
            polkit_dir.mkdir()
            exec_dir.mkdir()

            # The promoted helpers carry the managed marker.
            helper_contents = {}
            for helper in HELPERS:
                content = (
                    "#!/bin/sh\n# X-Jolven-Managed=true\n"
                    f"echo fake {helper}\n"
                )
                helper_contents[helper] = content
                _write_executable(prefix / "libexec" / helper, content, 0o755)

            # The search-provider has no marker on purpose: it must be
            # preserved even though it looks unmanaged.
            provider_content = "#!/bin/sh\necho fake search provider\n"
            _write_executable(
                prefix / "libexec" / "jolven-search-provider", provider_content, 0o755
            )
            session_content = "#!/bin/sh\necho fake session\n"
            _write_executable(prefix / "bin" / "jolven-session", session_content, 0o755)

            # exec.path targets must model the real root-owned system files:
            # executable but not writable by the invoking user.
            for helper in HELPERS:
                _write_executable(exec_dir / helper, "#!/bin/sh\nexit 0\n", 0o555)

            policy_contents = {}
            for policy, _action in POLICIES:
                template = (DATA_DIR / f"{policy}.in").read_text(encoding="utf-8")
                rendered = template.replace("@system_libexecdir@", str(exec_dir))
                policy_contents[policy] = rendered
                (prefix / "share" / "polkit-1" / "actions" / policy).write_text(
                    rendered, encoding="utf-8"
                )

            # Alien files without the marker/action id must be backed up.
            alien_helper = "alien helper without marker\n"
            (sys_dir / "jolven-game-mode-setup").write_text(
                alien_helper, encoding="utf-8"
            )
            alien_policy = "<policyconfig><vendor>alien</vendor></policyconfig>\n"
            (polkit_dir / POLICIES[0][0]).write_text(alien_policy, encoding="utf-8")

            # A sudo stub that fails loudly proves the promotion below never
            # needs sudo: destinations live in /tmp, never under /usr/*.
            stub_dir = tmp_path / "stubs"
            stub_dir.mkdir()
            sudo_stub = stub_dir / "sudo"
            sudo_stub.write_text(
                "#!/bin/sh\necho 'sudo must not be called' >&2\nexit 99\n",
                encoding="utf-8",
            )
            sudo_stub.chmod(0o755)

            env = dict(
                os.environ,
                CARTRIDGES_PROMOTE_ONLY=str(prefix),
                CARTRIDGES_SYSTEM_LIBEXECDIR=str(sys_dir),
                CARTRIDGES_POLKIT_DIR=str(polkit_dir),
                PATH=str(stub_dir) + os.pathsep + os.environ.get("PATH", os.defpath),
            )
            result = subprocess.run(
                [BASH, str(INSTALL_SH)],
                capture_output=True,
                encoding="utf-8",
                env=env,
                cwd=str(tmp_path),
                timeout=120,
            )
            self.assertEqual(
                result.returncode,
                0,
                msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            )
            self.assertIn("Integracao de sistema verificada.", result.stdout)

            # The helper is promoted with 0755 and nothing else besides backups.
            sys_names = {path.name for path in sys_dir.iterdir()}
            for helper in HELPERS:
                self.assertIn(helper, sys_names)
                promoted = sys_dir / helper
                self.assertEqual(
                    stat.S_IMODE(promoted.stat().st_mode),
                    0o755,
                    msg=f"{helper} mode",
                )
                self.assertEqual(
                    promoted.read_text(encoding="utf-8"), helper_contents[helper]
                )
            non_backup = {name for name in sys_names if ".bak-" not in name}
            self.assertEqual(non_backup, set(HELPERS))
            helper_backups = [
                name
                for name in sys_names
                if name.startswith("jolven-game-mode-setup.bak-")
            ]
            self.assertEqual(len(helper_backups), 1)
            self.assertEqual(
                (sys_dir / helper_backups[0]).read_text(encoding="utf-8"),
                alien_helper,
            )

            # Both policies installed with 0644; the alien one backed up.
            polkit_names = {path.name for path in polkit_dir.iterdir()}
            for policy, _action in POLICIES:
                self.assertIn(policy, polkit_names)
                installed = polkit_dir / policy
                self.assertEqual(
                    stat.S_IMODE(installed.stat().st_mode),
                    0o644,
                    msg=f"{policy} mode",
                )
                self.assertEqual(
                    installed.read_text(encoding="utf-8"), policy_contents[policy]
                )
            policy_backups = [
                name
                for name in polkit_names
                if name.startswith(f"{POLICIES[0][0]}.bak-")
            ]
            self.assertEqual(len(policy_backups), 1)
            self.assertEqual(
                (polkit_dir / policy_backups[0]).read_text(encoding="utf-8"),
                alien_policy,
            )

            # The user prefix keeps the search-provider and the session
            # launcher but loses the promoted helpers and the inert policies.
            self.assertEqual(
                (prefix / "libexec" / "jolven-search-provider").read_text(
                    encoding="utf-8"
                ),
                provider_content,
            )
            self.assertEqual(
                (prefix / "bin" / "jolven-session").read_text(encoding="utf-8"),
                session_content,
            )
            for helper in HELPERS:
                self.assertFalse((prefix / "libexec" / helper).exists())
            self.assertFalse((prefix / "share" / "polkit-1").exists())

    def test_promote_only_skips_system_prefixes(self):
        for system_prefix in ("/usr", "/usr/local"):
            with self.subTest(prefix=system_prefix):
                env = dict(os.environ, CARTRIDGES_PROMOTE_ONLY=system_prefix)
                env.pop("CARTRIDGES_SYSTEM_LIBEXECDIR", None)
                env.pop("CARTRIDGES_POLKIT_DIR", None)
                result = subprocess.run(
                    [BASH, str(INSTALL_SH)],
                    capture_output=True,
                    encoding="utf-8",
                    env=env,
                    timeout=120,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
                )
                self.assertIn("promocao dispensada", result.stdout)


if __name__ == "__main__":
    unittest.main()
