# test_sunshine_servico.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for the Sunshine autostart module (no real systemd)."""

import builtins
import subprocess
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

import cartridges.utils.sunshine_servico as servico

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

SYSTEMCTL = "/usr/bin/systemctl"
BINARIO = "/usr/bin/sunshine"

EXEC_VALIDO = (
    "ExecStart={ path=/usr/bin/sunshine ; argv[]=/usr/bin/sunshine ; "
    "ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; "
    "code=(null) ; status=0/0 }"
)
EXEC_ESTRANHO = "ExecStart={ path=/opt/outra/coisa ; argv[]=/opt/outra/coisa }"

DISTRO = "app-dev.lizardbyte.app.Sunshine.service"


def _resultado(argv, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=argv, returncode=returncode, stdout=stdout, stderr=stderr
    )


def make_runner(
    *,
    list_stdout="",
    list_falha=False,
    execstarts=None,
    enabled=("enabled\n", 0),
    enable=(0, ""),
    disable=(0, ""),
    record=None,
):
    """Fake de _executar: despacha pela subacao do systemctl."""
    execstarts = execstarts or {}

    def run(argv, timeout=15):
        if record is not None:
            record.append(list(argv))
        acao = argv[2]
        if acao == "list-unit-files":
            if list_falha:
                return None
            return _resultado(argv, stdout=list_stdout)
        if acao == "show":
            return _resultado(argv, stdout=execstarts.get(argv[-1], ""))
        if acao == "is-enabled":
            texto, codigo = enabled
            return _resultado(argv, returncode=codigo, stdout=texto)
        if acao == "enable":
            codigo, erro = enable
            return _resultado(argv, returncode=codigo, stderr=erro)
        if acao == "disable":
            codigo, erro = disable
            return _resultado(argv, returncode=codigo, stderr=erro)
        if acao == "daemon-reload":
            return _resultado(argv)
        raise AssertionError(f"argv inesperado: {argv}")

    return run


def _lista(*linhas):
    return "".join(f"{linha}\n" for linha in linhas)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        casa = patch.object(servico.Path, "home", return_value=self.home)
        casa.start()
        self.addCleanup(casa.stop)
        self.record = []

    def contexto(self, runner, *, binario=BINARIO):
        bin_path = Path(binario) if binario else None
        return (
            patch.object(servico, "_executar", side_effect=runner),
            patch.object(servico, "_systemctl", return_value=SYSTEMCTL),
            patch.object(servico, "binario_sunshine", return_value=bin_path),
        )

    def patches(self, runner, **kwargs):
        for p in self.contexto(runner, **kwargs):
            p.start()
            self.addCleanup(p.stop)


class DeteccaoTests(Base):
    def test_escolhe_unidade_com_execstart_do_sunshine(self):
        self.patches(
            make_runner(
                list_stdout=_lista(
                    "foo-sunshine-helper.service  disabled",
                    f"{DISTRO}  disabled",
                ),
                execstarts={
                    "foo-sunshine-helper.service": EXEC_ESTRANHO,
                    DISTRO: EXEC_VALIDO,
                },
                record=self.record,
            )
        )
        self.assertEqual(servico.unidade_sunshine(), DISTRO)

    def test_descarta_candidata_sem_execstart_do_sunshine(self):
        self.patches(
            make_runner(
                list_stdout=_lista("foo-sunshine-helper.service  disabled"),
                execstarts={"foo-sunshine-helper.service": EXEC_ESTRANHO},
                record=self.record,
            )
        )
        self.assertIsNone(servico.unidade_sunshine())
        # Ha binario, entao o autostart continua disponivel via fallback.
        self.assertTrue(servico.autostart_disponivel())

    def test_filtro_case_insensitive(self):
        nome = "My-SunShine-Thing.service"
        self.patches(
            make_runner(
                list_stdout=_lista(f"{nome}  disabled"),
                execstarts={nome: EXEC_VALIDO},
                record=self.record,
            )
        )
        self.assertEqual(servico.unidade_sunshine(), nome)

    def _com_unidade_jolven_no_disco(self):
        (self.home / ".config/systemd/user").mkdir(parents=True, exist_ok=True)
        (self.home / ".config/systemd/user/sunshine.service").write_text(
            "# X-Jolven-Managed=true\n[Unit]\n", encoding="utf-8"
        )

    def test_prefere_distro_a_unidade_do_jolven(self):
        self._com_unidade_jolven_no_disco()
        self.patches(
            make_runner(
                list_stdout=_lista(
                    "sunshine.service  enabled", f"{DISTRO}  disabled"
                ),
                execstarts={
                    "sunshine.service": EXEC_VALIDO,
                    DISTRO: EXEC_VALIDO,
                },
                record=self.record,
            )
        )
        self.assertEqual(servico.unidade_sunshine(), DISTRO)

    def test_prefere_distro_a_unidade_do_jolven_ordem_inversa(self):
        self._com_unidade_jolven_no_disco()
        self.patches(
            make_runner(
                list_stdout=_lista(
                    f"{DISTRO}  disabled", "sunshine.service  enabled"
                ),
                execstarts={
                    "sunshine.service": EXEC_VALIDO,
                    DISTRO: EXEC_VALIDO,
                },
                record=self.record,
            )
        )
        self.assertEqual(servico.unidade_sunshine(), DISTRO)

    def test_alias_quando_listagem_falha(self):
        self.patches(
            make_runner(
                list_falha=True,
                execstarts={servico.UNIDADE_ALIAS: EXEC_VALIDO},
                record=self.record,
            )
        )
        self.assertEqual(servico.unidade_sunshine(), servico.UNIDADE_ALIAS)

    def test_alias_invalido_quando_listagem_falha(self):
        self.patches(
            make_runner(
                list_falha=True,
                execstarts={servico.UNIDADE_ALIAS: EXEC_ESTRANHO},
                record=self.record,
            )
        )
        self.assertIsNone(servico.unidade_sunshine())


class DisponibilidadeTests(Base):
    def test_sem_unidade_e_sem_binario(self):
        self.patches(make_runner(list_stdout="", record=self.record), binario=None)
        self.assertFalse(servico.autostart_disponivel())
        self.assertFalse(servico.autostart_habilitado())
        ok, mensagem = servico.definir_autostart(True)
        self.assertFalse(ok)
        self.assertTrue(mensagem)
        self.assertNotIn("script", mensagem.lower())
        ok, mensagem = servico.definir_autostart(False)
        self.assertFalse(ok)
        self.assertTrue(mensagem)
        self.assertNotIn("script", mensagem.lower())

    def test_systemctl_ausente_sem_excecao(self):
        with patch.object(servico.shutil, "which", return_value=None):
            self.assertIsNone(servico.binario_sunshine())
            self.assertIsNone(servico.unidade_sunshine())
            self.assertFalse(servico.autostart_disponivel())
            self.assertFalse(servico.autostart_habilitado())
            ok, mensagem = servico.definir_autostart(True)
            self.assertFalse(ok)
            self.assertTrue(mensagem)
            self.assertNotIn("script", mensagem.lower())
            ok, mensagem = servico.definir_autostart(False)
            self.assertFalse(ok)
            self.assertTrue(mensagem)


class HabilitadoTests(Base):
    def test_enabled(self):
        self.patches(
            make_runner(
                list_stdout=_lista(f"{DISTRO}  disabled"),
                execstarts={DISTRO: EXEC_VALIDO},
                enabled=("enabled\n", 0),
                record=self.record,
            )
        )
        self.assertTrue(servico.autostart_habilitado())

    def test_disabled(self):
        self.patches(
            make_runner(
                list_stdout=_lista(f"{DISTRO}  disabled"),
                execstarts={DISTRO: EXEC_VALIDO},
                enabled=("disabled\n", 1),
                record=self.record,
            )
        )
        self.assertFalse(servico.autostart_habilitado())

    def test_erro_de_comando_e_false(self):
        def falha(argv, timeout=15):
            self.record.append(list(argv))
            if argv[2] == "list-unit-files":
                return _resultado(argv, stdout=_lista(f"{DISTRO}  disabled"))
            if argv[2] == "show":
                return _resultado(argv, stdout=EXEC_VALIDO)
            return None

        self.patches(falha)
        self.assertFalse(servico.autostart_habilitado())

    def test_sem_unidade_e_false(self):
        self.patches(make_runner(list_stdout="", record=self.record))
        self.assertFalse(servico.autostart_habilitado())


class DefinirTests(Base):
    def test_enable_usa_unidade_detectada(self):
        self.patches(
            make_runner(
                list_stdout=_lista(f"{DISTRO}  disabled"),
                execstarts={DISTRO: EXEC_VALIDO},
                record=self.record,
            )
        )
        ok, mensagem = servico.definir_autostart(True)
        self.assertTrue(ok)
        self.assertEqual(mensagem, "Autostart do Sunshine ativado.")
        enables = [a for a in self.record if a[2] == "enable"]
        self.assertEqual(len(enables), 1)
        self.assertEqual(enables[0][-1], DISTRO)
        self.assertNotIn("--now", enables[0])

    def test_disable_usa_unidade_detectada(self):
        self.patches(
            make_runner(
                list_stdout=_lista(f"{DISTRO}  enabled"),
                execstarts={DISTRO: EXEC_VALIDO},
                record=self.record,
            )
        )
        ok, mensagem = servico.definir_autostart(False)
        self.assertTrue(ok)
        self.assertEqual(mensagem, "Autostart do Sunshine desativado.")
        disables = [a for a in self.record if a[2] == "disable"]
        self.assertEqual(len(disables), 1)
        self.assertEqual(disables[0][-1], DISTRO)

    def test_enable_falha_com_mensagem(self):
        self.patches(
            make_runner(
                list_stdout=_lista(f"{DISTRO}  disabled"),
                execstarts={DISTRO: EXEC_VALIDO},
                enable=(1, "Failed to enable unit: something broke"),
                record=self.record,
            )
        )
        ok, mensagem = servico.definir_autostart(True)
        self.assertFalse(ok)
        self.assertIn("Não foi possível ativar", mensagem)
        self.assertIn("something broke", mensagem)
        self.assertNotIn("script", mensagem.lower())

    def test_disable_falha_com_mensagem(self):
        self.patches(
            make_runner(
                list_stdout=_lista(f"{DISTRO}  enabled"),
                execstarts={DISTRO: EXEC_VALIDO},
                disable=(1, "Failed to disable unit"),
                record=self.record,
            )
        )
        ok, mensagem = servico.definir_autostart(False)
        self.assertFalse(ok)
        self.assertIn("Não foi possível desativar", mensagem)
        self.assertNotIn("script", mensagem.lower())


class FallbackTests(Base):
    def destino(self):
        return self.home / ".config/systemd/user/sunshine.service"

    def test_cria_unidade_com_marcador(self):
        self.patches(make_runner(list_stdout="", record=self.record))
        ok, mensagem = servico.definir_autostart(True)
        self.assertTrue(ok)
        texto = self.destino().read_text(encoding="utf-8")
        self.assertIn("X-Jolven-Managed=true", texto)
        self.assertIn(f"ExecStart={BINARIO}", texto)
        self.assertIn("WantedBy=default.target", texto)
        acoes = [a[2] for a in self.record]
        self.assertIn("daemon-reload", acoes)
        self.assertIn("enable", acoes)
        # reload antes do enable.
        self.assertLess(acoes.index("daemon-reload"), acoes.index("enable"))
        enables = [a for a in self.record if a[2] == "enable"]
        self.assertEqual(enables[0][-1], "sunshine.service")

    def test_nao_sobrescreve_arquivo_sem_marcador(self):
        self.destino().parent.mkdir(parents=True, exist_ok=True)
        original = "[Unit]\nDescription=Minha unidade\n"
        self.destino().write_text(original, encoding="utf-8")
        self.patches(make_runner(list_stdout="", record=self.record))
        ok, mensagem = servico.definir_autostart(True)
        self.assertFalse(ok)
        self.assertTrue(mensagem)
        self.assertEqual(self.destino().read_text(encoding="utf-8"), original)
        self.assertFalse(any(a[2] == "enable" for a in self.record))

    def test_reutiliza_unidade_do_jolven(self):
        self.destino().parent.mkdir(parents=True, exist_ok=True)
        original = (
            "# X-Jolven-Managed=true\n"
            "[Unit]\nDescription=Sunshine (autostart gerenciado pelo Jolven)\n"
        )
        self.destino().write_text(original, encoding="utf-8")
        self.patches(make_runner(list_stdout="", record=self.record))
        ok, _mensagem = servico.definir_autostart(True)
        self.assertTrue(ok)
        self.assertEqual(self.destino().read_text(encoding="utf-8"), original)
        self.assertTrue(any(a[2] == "enable" for a in self.record))


class ContratoTests(Base):
    def test_sem_import_gi(self):
        fonte = Path(servico.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import gi", fonte)
        self.assertNotIn("from gi", fonte)

    def test_alias_publico(self):
        self.assertEqual(servico.UNIDADE_ALIAS, "sunshine.service")


if __name__ == "__main__":
    unittest.main()
