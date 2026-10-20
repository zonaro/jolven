# test_integrations.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for the integrations registry (no GTK, no real flatpak).

Everything that touches the machine is mocked: ``shutil.which`` and
``subprocess.run`` — both patched through the integrations module, which
also drives ``launchers.flatpak_installed`` because it resolves
``subprocess`` from the same stdlib module object.
"""

import builtins
import subprocess
import unittest

from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

from cartridges.utils.integrations import (
    CATEGORIAS,
    FLATHUB_URL,
    STATUS_AUSENTE,
    STATUS_FLATPAK,
    STATUS_NATIVO,
    Integracao,
    instalar_flatpak,
    listar_integracoes,
    obter_status,
)


#: Minimum set the Integrações page depends on (issue #46).
_CHAVES_OBRIGATORIAS = frozenset(
    {
        "sunshine",
        "moonlight",
        "steam",
        "lutris",
        "heroic",
        "bottles",
        "itch",
        "flatpak",
        "retroarch",
        "dolphin",
        "gpu-screen-recorder",
    }
)


def _por_chave(chave: str) -> Integracao:
    for integracao in listar_integracoes():
        if integracao.chave == chave:
            return integracao
    raise AssertionError(f"integração ausente: {chave}")


def _fake_run(
    returncode: int = 0, stderr: str = "", calls: list | None = None
) -> Any:
    def run(command: Any, **kwargs: Any) -> SimpleNamespace:
        if calls is not None:
            calls.append((list(command), kwargs))
        return SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)

    return run


class RegistroTests(unittest.TestCase):
    def test_lista_nao_vazia(self) -> None:
        self.assertTrue(listar_integracoes())

    def test_chaves_unicas(self) -> None:
        chaves = [item.chave for item in listar_integracoes()]
        self.assertEqual(len(chaves), len(set(chaves)))

    def test_categorias_validas(self) -> None:
        for item in listar_integracoes():
            with self.subTest(chave=item.chave):
                self.assertIn(item.categoria, CATEGORIAS)

    def test_toda_integracao_tem_flatpak_ou_binario(self) -> None:
        for item in listar_integracoes():
            with self.subTest(chave=item.chave):
                self.assertTrue(item.app_id_flatpak or item.binario)

    def test_strings_de_exibicao_nao_vazias(self) -> None:
        for item in listar_integracoes():
            with self.subTest(chave=item.chave):
                self.assertTrue(item.chave.strip())
                self.assertTrue(item.titulo.strip())
                self.assertTrue(item.descricao.strip())

    def test_chaves_obrigatorias_presentes(self) -> None:
        chaves = {item.chave for item in listar_integracoes()}
        self.assertEqual(_CHAVES_OBRIGATORIAS - chaves, frozenset())

    def test_flatpak_nao_e_instalavel(self) -> None:
        self.assertIsNone(_por_chave("flatpak").app_id_flatpak)
        self.assertEqual(_por_chave("flatpak").binario, "flatpak")

    def test_sunshine_reusa_constantes(self) -> None:
        sunshine = _por_chave("sunshine")
        self.assertEqual(sunshine.app_id_flatpak, "dev.lizardbyte.app.Sunshine")
        self.assertEqual(sunshine.binario, "sunshine")

    def test_dataclass_congelada(self) -> None:
        item = _por_chave("steam")
        with self.assertRaises(FrozenInstanceError):
            item.chave = "outra"  # type: ignore[misc]

    def test_categoria_desconhecida_levanta_value_error(self) -> None:
        with self.assertRaises(ValueError):
            Integracao(
                "x", "X", "invalida", "descricao", "app.id.X", "x"
            )

    def test_sem_flatpak_e_sem_binario_levanta_value_error(self) -> None:
        with self.assertRaises(ValueError):
            Integracao("x", "X", "ferramentas", "descricao", None, None)


class StatusTests(unittest.TestCase):
    def test_nativo_quando_binario_no_path(self) -> None:
        with (
            patch(
                "cartridges.utils.integrations.shutil.which",
                side_effect=lambda nome: (
                    f"/usr/bin/{nome}" if nome == "lutris" else None
                ),
            ),
            patch("cartridges.utils.integrations.subprocess.run") as run,
        ):
            self.assertEqual(
                obter_status(_por_chave("lutris")), STATUS_NATIVO
            )
        run.assert_not_called()

    def test_nativo_vence_flatpak(self) -> None:
        with (
            patch(
                "cartridges.utils.integrations.shutil.which",
                side_effect=lambda nome: f"/usr/bin/{nome}",
            ),
            patch("cartridges.utils.integrations.subprocess.run") as run,
        ):
            self.assertEqual(
                obter_status(_por_chave("steam")), STATUS_NATIVO
            )
        run.assert_not_called()

    def test_flatpak_quando_app_instalado(self) -> None:
        def run(command: Any, **kwargs: Any) -> SimpleNamespace:
            self.assertEqual(command[:2], ("flatpak", "info"))
            self.assertIn("net.lutris.Lutris", command)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with (
            patch("cartridges.utils.integrations.shutil.which", return_value=None),
            patch("cartridges.utils.integrations.subprocess.run", side_effect=run),
        ):
            self.assertEqual(
                obter_status(_por_chave("lutris")), STATUS_FLATPAK
            )

    def test_ausente_quando_nada_instalado(self) -> None:
        with (
            patch("cartridges.utils.integrations.shutil.which", return_value=None),
            patch(
                "cartridges.utils.integrations.subprocess.run",
                side_effect=_fake_run(returncode=1),
            ),
        ):
            self.assertEqual(
                obter_status(_por_chave("heroic")), STATUS_AUSENTE
            )

    def test_sem_app_id_flatpak_nao_consulta_flatpak(self) -> None:
        with (
            patch("cartridges.utils.integrations.shutil.which", return_value=None),
            patch("cartridges.utils.integrations.subprocess.run") as run,
        ):
            self.assertEqual(
                obter_status(_por_chave("legendary")), STATUS_AUSENTE
            )
        run.assert_not_called()

    def test_flatpak_ausente_sem_cli(self) -> None:
        # `flatpak info` cannot run when the CLI is gone: OSError inside
        # launchers.flatpak_installed degrades to "não instalado".
        with (
            patch("cartridges.utils.integrations.shutil.which", return_value=None),
            patch(
                "cartridges.utils.integrations.subprocess.run",
                side_effect=OSError("no such file"),
            ),
        ):
            self.assertEqual(
                obter_status(_por_chave("steam")), STATUS_AUSENTE
            )


class InstalarTests(unittest.TestCase):
    def test_argv_esperado_remote_add_depois_install(self) -> None:
        calls: list = []
        with (
            patch(
                "cartridges.utils.integrations.shutil.which",
                return_value="/usr/bin/flatpak",
            ),
            patch(
                "cartridges.utils.integrations.subprocess.run",
                side_effect=_fake_run(calls=calls),
            ),
        ):
            instalar_flatpak("net.lutris.Lutris")
        self.assertEqual(len(calls), 2)
        (add_argv, add_kwargs), (install_argv, install_kwargs) = calls
        self.assertEqual(
            add_argv,
            [
                "/usr/bin/flatpak",
                "remote-add",
                "--user",
                "--if-not-exists",
                "flathub",
                FLATHUB_URL,
            ],
        )
        self.assertEqual(
            install_argv,
            [
                "/usr/bin/flatpak",
                "install",
                "--user",
                "-y",
                "flathub",
                "net.lutris.Lutris",
            ],
        )
        self.assertEqual(add_kwargs.get("timeout"), 600)
        self.assertEqual(install_kwargs.get("timeout"), 600)

    def test_saida_nao_zero_levanta_com_stderr(self) -> None:
        with (
            patch(
                "cartridges.utils.integrations.shutil.which",
                return_value="/usr/bin/flatpak",
            ),
            patch(
                "cartridges.utils.integrations.subprocess.run",
                side_effect=_fake_run(
                    returncode=1, stderr="error: no such ref net.lutris.Lutris"
                ),
            ),
        ):
            with self.assertRaises(RuntimeError) as contexto:
                instalar_flatpak("net.lutris.Lutris")
        self.assertIn("no such ref", str(contexto.exception))

    def test_falha_de_processo_levanta_runtime_error(self) -> None:
        with (
            patch(
                "cartridges.utils.integrations.shutil.which",
                return_value="/usr/bin/flatpak",
            ),
            patch(
                "cartridges.utils.integrations.subprocess.run",
                side_effect=subprocess.TimeoutExpired("flatpak", 600),
            ),
        ):
            with self.assertRaises(RuntimeError):
                instalar_flatpak("net.lutris.Lutris")

    def test_sem_flatpak_levanta_runtime_error(self) -> None:
        with patch(
            "cartridges.utils.integrations.shutil.which", return_value=None
        ):
            with self.assertRaises(RuntimeError):
                instalar_flatpak("net.lutris.Lutris")

    def test_app_id_vazio_levanta_runtime_error(self) -> None:
        with self.assertRaises(RuntimeError):
            instalar_flatpak("   ")


if __name__ == "__main__":
    unittest.main()
