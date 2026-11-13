"""Montagem do comando de lançamento dos jogos do Minigalaxy (issues #161/#163).

Sem GTK, sem GSettings e sem subprocesso: ``minigalaxy_launch`` é um módulo
puro que recebe um ``MinigalaxyGame`` (dataclass, sem ``gi``) e devolve argv.
Os jogos são construídos direto do dataclass e as fixtures em
``tests/fixtures/minigalaxy/launch`` reproduzem as rotas de ``goggame`` do
upstream (``sharkwouter/minigalaxy``, commit ``f23e237``).

Contrato de disponibilidade do binário (comportamento real dos módulos):
``cartridges.importer.minigalaxy.detect_launcher`` só escolhe ``dosbox``,
``scummvm`` ou ``wine`` quando o programa existe no host (``shutil.which``,
checado uma única vez na varredura, em ``minigalaxy_source``). A montagem do
comando é pura: ``launch_argv``/``make_executable`` nunca reconsultam o host
e um jogo gravado com um launcher disponível recebe o argv completo mesmo
com o binário ausente; o launcher ``unavailable`` não tem comando.
"""

import builtins
import json
import os
import shlex
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]  # noqa: E731

from cartridges.importer import minigalaxy  # noqa: E402
from cartridges.importer.minigalaxy import (  # noqa: E402
    MinigalaxyGame,
    MinigalaxyPreferences,
)
from cartridges.importer.minigalaxy_launch import (  # noqa: E402
    dosbox_command,
    final_resort_command,
    fps_environment,
    launch_argv,
    launch_working_directory,
    make_executable,
    scummvm_command,
    select_dosbox_configs,
    select_scummvm_config,
    windows_command,
    wine_path,
)

try:
    # Importar cedo também devolve o ``cartridges.shared`` real antes de
    # test_minigalaxy_source stubá-lo no mesmo processo (issue #164).
    from cartridges.utils import launcher as _launcher  # noqa: E402
except Exception:  # noqa: BLE001  # árvore sem o app construído
    _launcher = None

FIXTURES = Path(__file__).parent / "fixtures" / "minigalaxy"
NATIVE = FIXTURES / "native" / "install"
WINE = FIXTURES / "wine" / "install"
LAUNCH = FIXTURES / "launch" / "install"

BOM = b"\xef\xbb\xbf"


def _game(
    directory: Path,
    launcher: str,
    preferences: MinigalaxyPreferences | None = None,
) -> MinigalaxyGame:
    """Um ``MinigalaxyGame`` direto do dataclass, sem passar pela varredura."""
    return MinigalaxyGame(
        gog_id=None,
        name=directory.name,
        platform="windows" if launcher == "wine" else "linux",
        directory=directory,
        launcher=launcher,
        preferences=preferences or MinigalaxyPreferences(),
    )


class _DiretorioTemporario(unittest.TestCase):
    """Base com uma pasta temporária por teste."""

    def _temporario(self) -> Path:
        caminho = Path(tempfile.mkdtemp(prefix="jolven-minigalaxy-"))
        self.addCleanup(shutil.rmtree, caminho, ignore_errors=True)
        return caminho


class StartScriptTests(_DiretorioTemporario):
    """``start.sh``: o caminho do script é um único elemento do argv."""

    def setUp(self) -> None:
        self.directory = NATIVE / "Assassin's Creed Ünïcode"
        self.game = _game(self.directory, "start_script")

    def test_argv_e_diretorio_de_trabalho(self) -> None:
        self.assertEqual(launch_argv(self.game), [str(self.directory / "start.sh")])
        self.assertEqual(launch_working_directory(self.game), str(self.directory))

    def test_make_executable_preserva_espacos_apostrofo_e_unicode(self) -> None:
        """O caminho com espaço, apóstrofo e acentos sai quotado por shlex."""
        argv = launch_argv(self.game)
        executavel = make_executable(self.game)
        self.assertEqual(executavel, shlex.join(argv))
        self.assertEqual(shlex.split(executavel), argv)
        # Sem a proteção do shlex, o apóstrofo e o espaço quebrariam o comando.
        self.assertIn("'", executavel)
        self.assertIn(" ", executavel)
        self.assertIn("Ünïcode", executavel)


class DosboxTests(_DiretorioTemporario):
    """DOSBox: ``-conf`` regular antes do ``_single``, depois encerramento."""

    def setUp(self) -> None:
        self.directory = NATIVE / "Duke Nukem 3D"
        self.game = _game(self.directory, "dosbox")

    def test_conf_regular_e_single(self) -> None:
        self.assertEqual(
            launch_argv(self.game),
            [
                "dosbox",
                "-conf",
                str(self.directory / "dosbox_duke3d.conf"),
                "-conf",
                str(self.directory / "dosbox_duke3d_single.conf"),
                "-no-console",
                "-c",
                "exit",
            ],
        )
        self.assertEqual(launch_working_directory(self.game), str(self.directory))

    def test_so_regular(self) -> None:
        directory = self._temporario()
        (directory / "dosbox_jogo.conf").write_text("# conf", encoding="utf-8")
        self.assertEqual(
            dosbox_command(directory, os.listdir(directory)),
            ["dosbox", "-conf", str(directory / "dosbox_jogo.conf"), "-no-console", "-c", "exit"],
        )

    def test_so_single(self) -> None:
        directory = self._temporario()
        (directory / "dosbox_jogo_single.conf").write_text("# conf", encoding="utf-8")
        self.assertEqual(
            dosbox_command(directory, os.listdir(directory)),
            [
                "dosbox",
                "-conf",
                str(directory / "dosbox_jogo_single.conf"),
                "-no-console",
                "-c",
                "exit",
            ],
        )

    def test_sem_conf(self) -> None:
        directory = self._temporario()
        self.assertEqual(dosbox_command(directory, os.listdir(directory)), [])

    def test_selecao_por_nome(self) -> None:
        self.assertEqual(
            select_dosbox_configs(["dosbox_b.conf", "dosbox_b_single.conf", "gameinfo"]),
            ("dosbox_b.conf", "dosbox_b_single.conf"),
        )


class ScummvmTests(_DiretorioTemporario):
    """ScummVM: ``scummvm -c <primeiro .ini>``."""

    def setUp(self) -> None:
        self.directory = NATIVE / "Broken Sword"
        self.game = _game(self.directory, "scummvm")

    def test_primeiro_ini(self) -> None:
        self.assertEqual(
            launch_argv(self.game),
            ["scummvm", "-c", str(self.directory / "scummvm.ini")],
        )
        self.assertEqual(launch_working_directory(self.game), str(self.directory))

    def test_sem_ini(self) -> None:
        directory = self._temporario()
        self.assertEqual(scummvm_command(directory, os.listdir(directory)), [])

    def test_selecao_por_nome(self) -> None:
        self.assertEqual(select_scummvm_config(["scummvm.ini", "outro.ini"]), "scummvm.ini")
        self.assertIsNone(select_scummvm_config(["leiame.txt"]))


class WinePrimarioTests(_DiretorioTemporario):
    """Wine com ``playTask`` primário: ``start /b /wait /d`` sob prefixo."""

    def setUp(self) -> None:
        self.directory = WINE / "Disco Elysium"
        self.prefix = f"WINEPREFIX={self.directory / 'prefix'}"
        self.game = _game(self.directory, "wine")

    def test_tarefa_primaria_com_argumentos(self) -> None:
        # O goggame da fixture começa com BOM: o parsing precisa tolerá-lo.
        self.assertTrue(
            (self.directory / "goggame-1423049311.info").read_bytes().startswith(BOM)
        )
        self.assertEqual(
            launch_argv(self.game),
            [
                "env",
                self.prefix,
                "wine",
                "start",
                "/b",
                "/wait",
                "/d",
                r"c:\game\game/bin",
                r"c:\game\game/bin/Disco Elysium.exe",
                "-force-d3d11",
            ],
        )
        # Duas playTasks: a primária é a segunda, não a primeira da lista.
        self.assertNotIn("launcher.exe", launch_argv(self.game)[-2])
        # Cada argumento é um elemento: a string não entra inteira no argv.
        self.assertEqual(launch_argv(self.game)[-1], "-force-d3d11")
        self.assertEqual(launch_working_directory(self.game), str(self.directory))

    def test_custom_wine(self) -> None:
        game = _game(
            self.directory,
            "wine",
            MinigalaxyPreferences(custom_wine="  /opt/custom/wine64  "),
        )
        argv = launch_argv(game)
        self.assertEqual(argv[2], "/opt/custom/wine64")
        self.assertEqual(argv[1], self.prefix)
        self.assertEqual(wine_path(game.preferences), "/opt/custom/wine64")

    def test_wine_path_sem_customizacao(self) -> None:
        self.assertEqual(wine_path(MinigalaxyPreferences(custom_wine=None)), "wine")
        # Espaços em branco não viram um binário inexistente.
        self.assertEqual(wine_path(MinigalaxyPreferences(custom_wine="   ")), "wine")
        self.assertEqual(wine_path(MinigalaxyPreferences(custom_wine="w")), "w")

    def test_make_executable_round_trip(self) -> None:
        executavel = make_executable(self.game)
        self.assertEqual(executavel, shlex.join(launch_argv(self.game)))
        self.assertEqual(shlex.split(executavel), launch_argv(self.game))


class WineFallbackTests(_DiretorioTemporario):
    """Sem tarefa primária: ``Launch *.lnk``, depois o primeiro executável."""

    def test_launch_lnk_tem_prioridade(self) -> None:
        directory = LAUNCH / "Fallback Lnk"
        game = _game(directory, "wine")
        self.assertEqual(
            launch_argv(game),
            ["env", f"WINEPREFIX={directory / 'prefix'}", "wine", str(directory / "Launch Jogo.lnk")],
        )

    def test_primeiro_executavel_util(self) -> None:
        directory = LAUNCH / "Fallback Exe"
        # Guarda contra drift da fixture: os ignorados continuam presentes.
        for ignorado in ("unins000.exe", "UnityCrashHandler64.exe"):
            self.assertTrue((directory / ignorado).is_file(), ignorado)
        game = _game(directory, "wine")
        self.assertEqual(
            launch_argv(game),
            ["env", f"WINEPREFIX={directory / 'prefix'}", "wine", str(directory / "Assistente.exe")],
        )

    def test_sem_executavel(self) -> None:
        directory = LAUNCH / "Sem Comando"
        game = _game(directory, "wine")
        self.assertEqual(launch_argv(game), [])
        self.assertEqual(make_executable(game), "")


class FinalResortTests(_DiretorioTemporario):
    """Fallback "FTL": ``./<path>`` da primeira playTask, dentro de ``game``."""

    def test_primeira_playtask(self) -> None:
        directory = LAUNCH / "Resort Final"
        game = _game(directory, "final_resort")
        self.assertEqual(launch_argv(game), ["./launcher/comecar.sh"])
        self.assertEqual(launch_working_directory(game), str(directory / "game"))

    def test_sem_pasta_game(self) -> None:
        directory = LAUNCH / "Sem Comando"
        game = _game(directory, "final_resort")
        self.assertEqual(final_resort_command(game), [])


class FpsEnvironmentTests(unittest.TestCase):
    """``show_fps`` liga as três variáveis documentadas; sem ele, ambiente limpo."""

    def test_sem_show_fps(self) -> None:
        self.assertEqual(fps_environment(MinigalaxyPreferences()), {})

    def test_com_show_fps(self) -> None:
        ambiente = fps_environment(MinigalaxyPreferences(show_fps=True))
        self.assertEqual(
            ambiente,
            {
                "__GL_SHOW_GRAPHICS_OSD": "1",
                "GALLIUM_HUD": "simple,fps",
                "VK_INSTANCE_LAYERS": "VK_LAYER_MESA_overlay",
            },
        )


class MakeExecutableTests(_DiretorioTemporario):
    """``make_executable``: ``shlex.join`` do argv; vazio sem comando."""

    def test_join_e_round_trip(self) -> None:
        for directory, launcher in (
            (NATIVE / "Duke Nukem 3D", "dosbox"),
            (NATIVE / "Broken Sword", "scummvm"),
            (WINE / "Disco Elysium", "wine"),
            (LAUNCH / "Resort Final", "final_resort"),
        ):
            with self.subTest(launcher=launcher):
                game = _game(directory, launcher)
                argv = launch_argv(game)
                self.assertTrue(argv)
                executavel = make_executable(game)
                self.assertEqual(executavel, shlex.join(argv))
                self.assertEqual(shlex.split(executavel), argv)

    def test_vazio_sem_comando(self) -> None:
        directory = self._temporario()
        for launcher in ("dosbox", "scummvm", "unavailable"):
            with self.subTest(launcher=launcher):
                game = _game(directory, launcher)
                self.assertEqual(launch_argv(game), [])
                self.assertEqual(make_executable(game), "")


class ContratoLauncherAusenteTests(_DiretorioTemporario):
    """Comportamento real com o binário ausente: a montagem não consulta o host.

    ``detect_launcher`` (varredura) é quem checa ``shutil.which``; um jogo já
    gravado como ``dosbox`` recebe o argv completo mesmo sem o binário, e o
    launcher ``unavailable`` (nada detectado) não produz comando.
    """

    def test_comando_nao_consulta_o_host(self) -> None:
        directory = NATIVE / "Duke Nukem 3D"
        game = _game(directory, "dosbox")
        esperado = launch_argv(game)
        with mock.patch("shutil.which", return_value=None), mock.patch.dict(
            os.environ, {"PATH": ""}
        ):
            self.assertEqual(launch_argv(game), esperado)
            self.assertEqual(make_executable(game), shlex.join(esperado))

    def test_unavailable_nao_tem_comando(self) -> None:
        game = _game(self._temporario(), "unavailable")
        self.assertEqual(launch_argv(game), [])
        self.assertEqual(make_executable(game), "")


class SegurancaTests(unittest.TestCase):
    """Metacaracteres de shell no ``goggame`` nunca separam ou executam nada.

    O caminho vem de um arquivo do Minigalaxy, não do usuário do Jolven:
    ele tem de continuar UM elemento do argv, quotado pelo ``shlex.join``,
    e sobreviver ao ``shlex.split`` do ``run_executable`` sem mudar de
    sentido.
    """

    def setUp(self) -> None:
        self.directory = LAUNCH / "Injecao Shell"
        self.game = _game(self.directory, "wine")

    def test_metacaracteres_ficam_em_um_elemento(self) -> None:
        argv = launch_argv(self.game)
        # env, WINEPREFIX, wine, start, /b, /wait, /d, workingDir, path
        self.assertEqual(len(argv), 9)
        caminho = argv[-1]
        self.assertTrue(caminho.startswith("c:\\game\\"))
        for metacaractere in ("`", "$(", ";", "|", "'", '"', "\n"):
            with self.subTest(metacaractere=metacaractere):
                self.assertIn(metacaractere, caminho)
        # Unicode e o workingDir hostil também sobrevivem, cada um no seu elemento.
        self.assertIn("çãó", caminho)
        self.assertEqual(argv[-2], r"c:\game\w;`$(x)`|a'b")

    def test_round_trip_preserva_o_metacaractere(self) -> None:
        argv = launch_argv(self.game)
        executavel = make_executable(self.game)
        self.assertEqual(executavel, shlex.join(argv))
        self.assertEqual(shlex.split(executavel), argv)
        # A aspa do shlex protege o caminho: a string pronta para o
        # /bin/sh -c nunca deixa o `rm` ou o $(id) fora de um argumento.
        self.assertIn("`rm`", argv[-1])
        self.assertIn("$(id)", argv[-1])

    def test_goggame_hostil_continua_legivel(self) -> None:
        nome, game_id, task = minigalaxy.parse_goggame_info(
            self.directory / "goggame-4001.info"
        )
        self.assertEqual(nome, "Injecao Shell")
        self.assertEqual(game_id, "4001")
        self.assertTrue(task["path"].startswith("game/`rm`"))


class LigacaoLauncherTests(unittest.TestCase):
    """Fiação do cliente Minigalaxy em ``cartridges.utils.launcher`` (#164).

    Importada via Flatpak ou .desktop, a própria interface do Minigalaxy é
    um launcher (badge/ícone no topo), nunca um jogo. Pode pular em árvores
    onde ``cartridges.shared`` não importa sem o app construído.
    """

    @classmethod
    def setUpClass(cls) -> None:
        if _launcher is None:
            raise unittest.SkipTest("cartridges.utils.launcher não importável aqui")
        cls.launcher = _launcher

    def test_minigalaxy_esta_registrado_como_launcher(self) -> None:
        self.assertEqual(
            self.launcher._APLICATIVOS["minigalaxy"],
            (
                "io.github.sharkwouter.Minigalaxy",
                "minigalaxy",
                "minigalaxy-source-symbolic",
            ),
        )

    def test_flatpak_e_desktop_do_minigalaxy_sao_launchers(self) -> None:
        for base_source, identificador in (
            ("flatpak", "io.github.sharkwouter.Minigalaxy"),
            ("desktop", "minigalaxy"),
        ):
            with self.subTest(base_source=base_source):
                jogo = SimpleNamespace(
                    base_source=base_source,
                    game_id=f"{base_source}_{identificador}",
                    name="Minigalaxy",
                )
                self.assertTrue(self.launcher.detectar(jogo))

    def test_icone_da_fonte_minigalaxy(self) -> None:
        """A fonte resolve para o símbolo enviado, como steam e heroic."""
        self.assertEqual(
            self.launcher.nomes_de_icone_da_fonte("minigalaxy"),
            (
                "minigalaxy-source-symbolic",
                "io.github.sharkwouter.Minigalaxy",
                "minigalaxy",
            ),
        )


if __name__ == "__main__":
    unittest.main()
