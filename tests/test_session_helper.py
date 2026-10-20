import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HELPER = Path(__file__).parents[1] / "session" / "jolven-game-mode-setup.in"
RELAY_PATH = "@game_session_libexecdir@/jolven-session"


def run_helper(*args, env=None):
    return subprocess.run(
        [HELPER, *args],
        capture_output=True,
        encoding="utf-8",
        env=env,
    )


def clean_environment():
    # Nao deixe o runner (sudo/pkexec) interferir na deteccao da home.
    return {
        key: value
        for key, value in os.environ.items()
        if key not in ("PKEXEC_UID", "SUDO_UID")
    }


class SessionHelperTests(unittest.TestCase):
    def test_login_session_name_is_jolven_session(self):
        result = subprocess.run(
            [HELPER, "name"], capture_output=True, encoding="utf-8", check=True
        )
        self.assertEqual(result.stdout.strip(), "Jolven Session")

    def test_installer_prefers_the_user_installation(self):
        installer = (
            Path(__file__).parents[1] / "scripts" / "install-game-session.sh"
        ).read_text(encoding="utf-8")
        local_bin_check = '[[ -x "$HOME/.local/bin/jolven" ]]'
        path_lookup = 'command -v jolven'
        self.assertLess(
            installer.index(local_bin_check), installer.index(path_lookup)
        )
        self.assertIn("JOLVEN_EXECUTABLE", installer)

    def test_session_file_uses_the_relay_for_a_home_launcher(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            os.chmod(home, 0o700)
            launcher = home / ".local" / "bin" / "jolven-session"
            launcher.parent.mkdir(parents=True)
            launcher.write_text("#!/bin/sh\n", encoding="utf-8")
            launcher.chmod(0o755)

            result = run_helper(
                "session-file", str(launcher), env=clean_environment()
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertIn(f"Exec={RELAY_PATH}", lines)
        self.assertIn(f"TryExec={RELAY_PATH}", lines)
        self.assertIn("Name=Jolven Session", lines)
        self.assertIn("X-Jolven-Managed=true", lines)
        self.assertFalse(any("X-GDM-SessionRegisters" in line for line in lines))

    def test_session_file_uses_a_system_launcher_directly(self):
        result = run_helper(
            "session-file", "/usr/bin/jolven-session", env=clean_environment()
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertIn("Exec=/usr/bin/jolven-session", lines)
        self.assertIn("TryExec=/usr/bin/jolven-session", lines)
        self.assertFalse(any("X-GDM-SessionRegisters" in line for line in lines))

    def test_relay_output_is_fixed_and_prefers_the_user_installation(self):
        result = run_helper("relay")

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertTrue(lines[0].startswith("#!"))
        self.assertEqual(lines[1], "# X-Jolven-Managed=true")
        self.assertIn('exec "$candidate" "$@"', result.stdout)

        candidates = [
            "$HOME/.local/bin/jolven-session",
            "/usr/bin/jolven-session",
            "/usr/local/bin/jolven-session",
        ]
        positions = [result.stdout.index(candidate) for candidate in candidates]
        self.assertEqual(positions, sorted(positions))

    def test_relay_runs_the_user_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            relay = self._write_relay(Path(temporary))
            home = Path(temporary) / "home"
            stub = home / ".local" / "bin" / "jolven-session"
            stub.parent.mkdir(parents=True)
            stub.write_text("#!/bin/sh\nprintf 'relay-ok\\n'\n", encoding="utf-8")
            stub.chmod(0o755)

            result = subprocess.run(
                [relay],
                capture_output=True,
                encoding="utf-8",
                env={"HOME": str(home), "PATH": ""},
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "relay-ok")

    def test_relay_reports_a_missing_launcher(self):
        if Path("/usr/bin/jolven-session").exists() or Path(
            "/usr/local/bin/jolven-session"
        ).exists():
            self.skipTest("host provides a system-wide Jolven launcher")

        with tempfile.TemporaryDirectory() as temporary:
            relay = self._write_relay(Path(temporary))
            home = Path(temporary) / "home"
            home.mkdir()

            result = subprocess.run(
                [relay],
                capture_output=True,
                encoding="utf-8",
                env={"HOME": str(home), "PATH": ""},
            )

        self.assertEqual(result.returncode, 127)
        self.assertEqual(result.stdout, "")

    def _write_relay(self, directory):
        result = run_helper("relay")
        self.assertEqual(result.returncode, 0, result.stderr)
        relay = directory / "jolven-session"
        relay.write_text(result.stdout, encoding="utf-8")
        relay.chmod(0o755)
        return relay


if __name__ == "__main__":
    unittest.main()
