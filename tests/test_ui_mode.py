# test_ui_mode.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Resolvedor de interface da sessão: Jolven Flat ou Jolven Console (issue #179)."""

import unittest
from unittest import mock

from cartridges import ui_mode


class _SchemaFake:
    """Schema falso que expõe apenas o que selected() consulta."""

    def __init__(self, keys: list[str]) -> None:
        self._keys = set(keys)

    def list_keys(self) -> list[str]:
        return list(self._keys)


class UiModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._patches = []

    def tearDown(self) -> None:
        for patcher in self._patches:
            patcher.stop()

    def _definir_schema(self, valor: str) -> None:
        """Finge que o schema esta instalado, tem a chave ui-mode e devolve valor."""

        p_lookup = mock.patch.object(
            ui_mode, "schema_lookup", return_value=_SchemaFake(["ui-mode"])
        )
        p_get = mock.patch.object(
            ui_mode.shared.state_schema,
            "get_string",
            side_effect=lambda k, **kw: valor,
        )
        p_lookup.start()
        p_get.start()
        self._patches.extend([p_lookup, p_get])

    def _schema_indisponível(self) -> None:
        p = mock.patch.object(ui_mode, "schema_lookup", return_value=None)
        p.start()
        self._patches.append(p)

    def test_padrao_eh_flat(self):
        # Sem mock: schema nao tem a chave no ambiente de teste (versao antiga),
        # entao selected() nao chega a ler e devolve o padrao Flat.
        self.assertEqual(ui_mode.selected(), ui_mode.FLAT)
        self.assertFalse(ui_mode.is_console())

    def test_console_persistido(self):
        self._definir_schema("console")
        self.assertEqual(ui_mode.selected(), ui_mode.CONSOLE)
        self.assertTrue(ui_mode.is_console())

    def test_valor_desconhecido_cai_de_volta_ao_flat(self):
        self._definir_schema("qualquer-coisa")
        self.assertEqual(ui_mode.selected(), ui_mode.FLAT)
        self.assertFalse(ui_mode.is_console())

    def test_schema_indisponivel_cai_de_volta_ao_flat(self):
        self._schema_indisponível()
        self.assertEqual(ui_mode.selected(), ui_mode.FLAT)
        self.assertFalse(ui_mode.is_console())

    def test_chave_ausente_cai_de_volta_ao_flat(self):
        # Schema instalado, mas sem a chave ui-mode (instalacao antiga): nao
        # pode chamar get_string (g_error fatal), apenas devolve Flat.
        p_lookup = mock.patch.object(
            ui_mode, "schema_lookup", return_value=_SchemaFake([])
        )
        p_lookup.start()
        self._patches.append(p_lookup)
        self.assertEqual(ui_mode.selected(), ui_mode.FLAT)
        self.assertFalse(ui_mode.is_console())


if __name__ == "__main__":
    unittest.main()
