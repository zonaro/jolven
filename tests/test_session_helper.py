import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


HELPER = Path(__file__).parents[1] / "session" / "jolven-game-mode-setup.in"

# NOTE (issue #42): session installation migrated to the privileged helper
# via polkit triggered from Preferences. The legacy install-game-session
# shell installer was removed, so no test here may reference removed install
# or uninstall shell installers. User-install preference is covered by the
# resolve_session_launcher() tests below; install.sh behavior is covered
# by tests/test_install_sh.py (other lane).

SYSTEM_CANDIDATES = (
    "/usr/local/bin/jolven-session",
    "/usr/bin/jolven-session",
)


def _extract_resolver(helper_text):
    lines = helper_text.splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.startswith("resolve_session_launcher()")
    )
    end = next(i for i in range(start, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start : end + 1])


def _run_resolver(helper_text, env, stub_getent=None):
    function = _extract_resolver(helper_text)
    if stub_getent is not None:
        stub_dir = tempfile.mkdtemp(prefix="jolven-getent-stub-")
        stub = Path(stub_dir) / "getent"
        stub.write_text(stub_getent, encoding="utf-8")
        stub.chmod(0o755)
        env = dict(env, PATH=stub_dir + os.pathsep + env.get("PATH", os.defpath))
    script = function + "\nresolve_session_launcher\n"
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        encoding="utf-8",
        env=env,
    )


class SessionHelperTests(unittest.TestCase):
    def test_login_session_name_is_jolven_session(self):
        helper = Path(__file__).parents[1] / "session" / "jolven-game-mode-setup.in"
        result = subprocess.run(
            [helper, "name"], capture_output=True, encoding="utf-8", check=True
        )
        self.assertEqual(result.stdout.strip(), "Jolven Session")

    def test_managed_marker_stays_at_top(self):
        head = HELPER.read_text(encoding="utf-8").splitlines()[:3]
        self.assertIn("# X-Jolven-Managed=true", head)

    def test_launcher_resolution_uses_pkexec_uid_home(self):
        helper = HELPER.read_text(encoding="utf-8")
        self.assertIn("PKEXEC_UID", helper)
        self.assertIn("getent passwd", helper)
        self.assertIn("/etc/passwd", helper)
        self.assertIn("$invoking_home/.local/bin/jolven-session", helper)

    def test_launcher_candidates_have_fixed_order(self):
        helper = HELPER.read_text(encoding="utf-8")
        user_candidate = ".local/bin/jolven-session"
        self.assertLess(
            helper.index(user_candidate),
            helper.index(SYSTEM_CANDIDATES[0]),
        )
        self.assertLess(
            helper.index(SYSTEM_CANDIDATES[0]),
            helper.index(SYSTEM_CANDIDATES[1]),
        )

    def test_launcher_is_not_derived_from_helper_path(self):
        helper = HELPER.read_text(encoding="utf-8")
        self.assertNotIn("_SETUP_BINDIR", helper)
        self.assertNotIn("@bindir@", helper)
        self.assertNotIn("readlink", helper)
        self.assertNotRegex(helper, r"session_launcher=\"\$1\"")

    def test_missing_launcher_error_mentions_incomplete_install(self):
        helper = HELPER.read_text(encoding="utf-8")
        self.assertIn("Session launcher not found", helper)
        self.assertIn("incomplete", helper.lower())
        self.assertNotIn("install.sh", helper)
        self.assertNotRegex(helper, r"[Rr]un .*\.sh")

    def test_no_polkit_reload_block(self):
        helper = HELPER.read_text(encoding="utf-8")
        self.assertNotIn("systemctl reload", helper)
        self.assertNotIn("polkit.service", helper)

    def test_resolve_prefers_invoking_user_home(self):
        helper = HELPER.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory(prefix="jolven-fake-home-") as tmp:
            fake_home = Path(tmp) / "home"
            launcher = fake_home / ".local" / "bin" / "jolven-session"
            launcher.parent.mkdir(parents=True)
            launcher.write_text("#!/bin/sh\n", encoding="utf-8")
            launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)
            stub_getent = (
                "#!/bin/sh\n"
                'if [ "$1" = "passwd" ] && [ "$2" = "4242" ]; then\n'
                f'  printf \'fakeuser:x:4242:4242:Fake:{fake_home}:/bin/bash\\n\'\n'
                "  exit 0\n"
                "fi\n"
                "exit 2\n"
            )
            env = {"PATH": os.defpath, "PKEXEC_UID": "4242"}
            result = _run_resolver(helper, env, stub_getent=stub_getent)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), str(launcher))

    def test_resolve_without_candidates_stays_in_fixed_list(self):
        helper = HELPER.read_text(encoding="utf-8")
        stub_getent = "#!/bin/sh\nexit 2\n"
        env = {"PATH": os.defpath, "PKEXEC_UID": "59999"}
        result = _run_resolver(helper, env, stub_getent=stub_getent)
        if result.returncode == 0:
            self.assertIn(result.stdout.strip(), SYSTEM_CANDIDATES)
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "")

    def test_resolve_without_pkexec_uid_uses_system_candidates_only(self):
        helper = HELPER.read_text(encoding="utf-8")
        function = _extract_resolver(helper)
        # $HOME may appear in comments, but the executable check must never
        # expand the environment's $HOME.
        self.assertNotIn('"$HOME/', function)
        env = {"PATH": os.defpath}
        env.pop("PKEXEC_UID", None)
        result = _run_resolver(helper, env)
        if result.returncode == 0:
            self.assertIn(result.stdout.strip(), SYSTEM_CANDIDATES)


if __name__ == "__main__":
    unittest.main()
