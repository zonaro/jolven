import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HELPER = Path(__file__).parents[1] / "session" / "jolven-game-mode-setup.in"
RELAY_PATH = "@game_session_libexecdir@/jolven-session"
INVOKING_UID = "4242"


def run_helper(*args, env=None, cwd=None):
    return subprocess.run(
        [HELPER, *args],
        capture_output=True,
        encoding="utf-8",
        env=env,
        cwd=cwd,
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

    def test_the_app_installs_the_session_without_manual_scripts(self):
        # A Jolven nao distribui mais script de instalacao da Jolven Session:
        # a sessao e instalada pela tela de Preferencias (ou pelo menu do
        # app) pelo helper privilegiado, autorizado pela action polkit.
        root = Path(__file__).parents[1]
        self.assertFalse((root / "scripts" / "install-game-session.sh").exists())
        self.assertFalse((root / "scripts" / "uninstall-game-session.sh").exists())

        helper = root / "session" / "jolven-game-mode-setup.in"
        self.assertTrue(helper.is_file())

        policy = (
            root / "data" / "io.github.zonaro.Jolven.GameMode.policy.in"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'action id="io.github.zonaro.Jolven.configure-game-mode"', policy
        )
        self.assertIn(
            '<annotate key="org.freedesktop.policykit.exec.path">'
            "@system_libexecdir@/jolven-game-mode-setup</annotate>",
            policy,
        )

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

    def test_relay_finds_the_launcher_in_the_user_bin_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            relay = self._write_relay(Path(temporary))
            home = Path(temporary) / "home"
            stub = home / "bin" / "jolven-session"
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


class SessionLauncherResolutionTests(unittest.TestCase):
    """Resolucao do launcher a partir da home do usuario invocante.

    O helper pergunta a base do sistema (`getent passwd <uid>`) e nao o
    `$HOME` do processo root. Os testes usam um `getent` falso no `PATH` e
    directorios temporarios: nada depende da maquina nem de `/etc/passwd`.
    """

    def test_launcher_is_resolved_from_the_invoking_user_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._traversable_root(Path(temporary))
            home = root / "home"
            launcher = home / ".local" / "bin" / "jolven-session"
            self._write_launcher(launcher)
            home.chmod(0o755)

            result = run_helper(
                "session-file",
                env=self._environment(root, home),
                cwd=str(root),
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertIn(f"Exec={launcher.resolve()}", lines)
        self.assertIn(f"TryExec={launcher.resolve()}", lines)

    def test_user_bin_launcher_is_resolved_from_the_invoking_user_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._traversable_root(Path(temporary))
            home = root / "home"
            launcher = home / "bin" / "jolven-session"
            self._write_launcher(launcher)
            home.chmod(0o755)

            result = run_helper(
                "session-file",
                env=self._environment(root, home),
                cwd=str(root),
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertIn(f"Exec={launcher.resolve()}", lines)

    def test_legacy_cartridges_launcher_is_resolved_from_the_user_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._traversable_root(Path(temporary))
            home = root / "home"
            launcher = home / ".local" / "bin" / "cartridges-session"
            self._write_launcher(launcher)
            home.chmod(0o755)

            result = run_helper(
                "session-file",
                env=self._environment(root, home),
                cwd=str(root),
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertIn(f"Exec={launcher.resolve()}", lines)

    def test_private_user_home_falls_back_to_the_relay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._traversable_root(Path(temporary))
            helper = self._install_helper(root)
            # Um launcher visivel no prefixo do helper seria usado direto se a
            # home do usuario nao tivesse precedence.
            system_launcher = root / "bin" / "jolven-session"
            self._write_launcher(system_launcher)

            home = root / "home"
            self._write_launcher(home / ".local" / "bin" / "jolven-session")
            home.chmod(0o700)

            result = self._run_installed_helper(
                helper, root, home, uid=INVOKING_UID
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertIn(f"Exec={RELAY_PATH}", lines)
        self.assertIn(f"TryExec={RELAY_PATH}", lines)
        self.assertNotIn(f"Exec={system_launcher.resolve()}", lines)

    def test_session_file_uses_the_relay_for_a_launcher_others_cannot_execute(self):
        # Home atravessavel (0755) e launcher 0700: o greeter (gdm) e outro
        # usuario e nao consegue executar o arquivo. O `-x` do root nao serve
        # (vale com QUALQUER bit de execucao), entao o helper usa o relay —
        # que roda como o usuario da sessao, dono do launcher.
        with tempfile.TemporaryDirectory() as temporary:
            root = self._traversable_root(Path(temporary))
            home = root / "home"
            launcher = home / ".local" / "bin" / "jolven-session"
            self._write_launcher(launcher)
            launcher.chmod(0o700)
            home.chmod(0o755)

            result = run_helper(
                "session-file",
                env=self._environment(root, home),
                cwd=str(root),
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(result.returncode, 70)
        lines = result.stdout.splitlines()
        self.assertIn(f"Exec={RELAY_PATH}", lines)
        self.assertIn(f"TryExec={RELAY_PATH}", lines)
        self.assertNotIn(f"Exec={launcher.resolve()}", lines)

    def test_install_uses_the_relay_for_a_launcher_others_cannot_execute(self):
        """O `install` grava o relay e nao aborta com exit 70.

        Roda o helper num namespace de usuario (root local) com os comandos
        de sistema substituidos por stubs: o alvo do arquivo de sessao e a
        unica coisa em teste.
        """
        unshare = shutil.which("unshare")
        if unshare is None:
            self.skipTest("unshare is not available")
        probe = subprocess.run(
            [unshare, "-r", "true"], capture_output=True, encoding="utf-8"
        )
        if probe.returncode != 0:
            self.skipTest("user namespaces are not available")

        with tempfile.TemporaryDirectory() as temporary:
            root = self._traversable_root(Path(temporary))
            helper = self._install_helper(root)
            home = root / "home"
            launcher = home / ".local" / "bin" / "jolven-session"
            self._write_launcher(launcher)
            launcher.chmod(0o700)
            home.chmod(0o755)

            stubs = self._install_stubs(root)
            environment = self._environment(root, home)
            path = os.pathsep.join([str(stubs), environment["PATH"]])
            command = (
                f"cd {shlex.quote(str(root))} && "
                f"{shlex.quote(str(helper))} install"
            )
            result = subprocess.run(
                [
                    unshare,
                    "-r",
                    "env",
                    f"PKEXEC_UID={INVOKING_UID}",
                    f"HOME={environment['HOME']}",
                    f"PATH={path}",
                    "bash",
                    "-c",
                    command,
                ],
                capture_output=True,
                encoding="utf-8",
                env=clean_environment(),
                cwd=str(root),
            )
            session_file = (
                root
                / "@game_session_datadir@"
                / "wayland-sessions"
                / "io.github.zonaro.Jolven.GameMode.desktop"
            )
            content = (
                session_file.read_text(encoding="utf-8")
                if session_file.is_file()
                else ""
            )

        self.assertNotEqual(result.returncode, 70, result.stderr)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"Exec={RELAY_PATH}", content.splitlines())
        self.assertNotIn(f"Exec={launcher.resolve()}", content.splitlines())

    def test_user_home_wins_over_the_helper_and_the_baked_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._traversable_root(Path(temporary))
            helper = self._install_helper(root)
            system_launcher = root / "bin" / "jolven-session"
            self._write_launcher(system_launcher)
            # O caminho assado (`@bindir@`) e relativo no template: o helper
            # roda com o CWD no prefixo temporario.
            baked_launcher = root / "@bindir@" / "jolven-session"
            self._write_launcher(baked_launcher)

            home = root / "home"
            user_launcher = home / ".local" / "bin" / "jolven-session"
            self._write_launcher(user_launcher)
            home.chmod(0o755)

            result = self._run_installed_helper(
                helper, root, home, uid=INVOKING_UID
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertIn(f"Exec={user_launcher.resolve()}", lines)
        self.assertNotIn(f"Exec={system_launcher.resolve()}", lines)
        self.assertNotIn(f"Exec={baked_launcher.resolve()}", lines)

    def test_user_home_without_launcher_falls_back_to_the_helper_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._traversable_root(Path(temporary))
            helper = self._install_helper(root)
            system_launcher = root / "bin" / "jolven-session"
            self._write_launcher(system_launcher)

            home = root / "home"
            home.mkdir()
            home.chmod(0o755)

            result = self._run_installed_helper(
                helper, root, home, uid=INVOKING_UID
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertIn(f"Exec={system_launcher.resolve()}", lines)

    def test_without_pkexec_uid_the_helper_relative_launcher_is_used(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._traversable_root(Path(temporary))
            helper = self._install_helper(root)
            system_launcher = root / "bin" / "jolven-session"
            self._write_launcher(system_launcher)

            # Sem `PKEXEC_UID` a home do usuario nao participa da resolucao.
            home = root / "home"
            user_launcher = home / ".local" / "bin" / "jolven-session"
            self._write_launcher(user_launcher)
            home.chmod(0o755)

            result = self._run_installed_helper(helper, root, home, uid=None)

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertIn(f"Exec={system_launcher.resolve()}", lines)
        self.assertNotIn(f"Exec={user_launcher.resolve()}", lines)

    def _traversable_root(self, root):
        # O greeter percorre os directorios ancestrais: eles precisam de o+x.
        root.chmod(0o755)
        return root

    def _write_launcher(self, launcher):
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.write_text("#!/bin/sh\n", encoding="utf-8")
        launcher.chmod(0o755)
        return launcher

    def _install_helper(self, root):
        """Copia o helper para um prefixo proprio (`libexec` + `bin`)."""
        libexec = root / "libexec"
        libexec.mkdir(parents=True, exist_ok=True)
        helper = libexec / "jolven-game-mode-setup"
        helper.write_text(HELPER.read_text(encoding="utf-8"), encoding="utf-8")
        helper.chmod(0o755)
        return helper

    def _install_stubs(self, root):
        """Comandos de sistema substituidos por stubs deterministicos.

        O `install` do helper checa dependencias (`rpm`/`gamescope`), executa
        o launcher como `nobody` (`runuser`), recarrega o polkit
        (`systemctl`) e valida o arquivo de sessao
        (`desktop-file-validate`): nada disso pertence ao teste.
        """
        directory = root / "stub-bin"
        directory.mkdir(parents=True, exist_ok=True)
        for name in ("rpm", "gamescope", "runuser", "desktop-file-validate"):
            stub = directory / name
            stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            stub.chmod(0o755)
        # `systemctl is-active polkit.service` falso: o helper nao recarrega o
        # polkit da maquina do teste.
        systemctl = directory / "systemctl"
        systemctl.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        systemctl.chmod(0o755)
        return directory

    def _fake_getent(self, root, home):
        """`getent` falso que responde `getent passwd <uid>` com `home`."""
        directory = root / "fake-bin"
        directory.mkdir(parents=True, exist_ok=True)
        getent = directory / "getent"
        getent.write_text(
            "#!/bin/sh\n"
            "# Fake getent for the Jolven session helper tests.\n"
            f'if [ "$1" = "passwd" ] && [ "$2" = "{INVOKING_UID}" ]; then\n'
            f'    printf "%s\\n" "jolven-test:x:{INVOKING_UID}:1000:Jolven Test:'
            f'{home}:/bin/sh"\n'
            "    exit 0\n"
            "fi\n"
            "exit 2\n",
            encoding="utf-8",
        )
        getent.chmod(0o755)
        return directory

    def _environment(self, root, home, uid=INVOKING_UID):
        environment = clean_environment()
        # A home do processo root nao pode influenciar a resolucao.
        environment["HOME"] = str(root / "root-home")
        environment["PATH"] = os.pathsep.join(
            [str(self._fake_getent(root, home)), environment.get("PATH", "")]
        )
        if uid is not None:
            environment["PKEXEC_UID"] = uid
        return environment

    def _run_installed_helper(self, helper, root, home, uid):
        environment = self._environment(root, home, uid=uid)
        return subprocess.run(
            [str(helper), "session-file"],
            capture_output=True,
            encoding="utf-8",
            env=environment,
            cwd=str(root),
        )


if __name__ == "__main__":
    unittest.main()
