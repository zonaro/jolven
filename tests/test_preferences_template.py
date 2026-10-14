# test_preferences_template.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression test: every Template.Child used by the preferences dialog
must exist in the Blueprint source.

A missing id breaks dialog construction, which silently disables every
menu entry that opens Preferences (including Sunshine settings).
Pure file parsing: no GTK, no build directory needed.
"""

import re
import unittest

from pathlib import Path


ROOT = Path(__file__).parents[1]


def template_childs(source: Path) -> set[str]:
    text = source.read_text(encoding="utf-8")
    return set(
        re.findall(r"(\w+)\s*:\s*[\w.]+\s*=\s*Gtk\.Template\.Child\(\)", text)
    )


def blueprint_ids(source: Path) -> set[str]:
    ids: set[str] = set()
    pattern = re.compile(r"^\s*(?:\[suffix\]|Adw\.|Gtk\.)?.*?(\w+)\s*\{")
    for line in source.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "using", "menu ", "item ")):
            continue
        stripped = re.sub(r"^\w+:\s*", "", stripped)
        match = re.match(r"(?:\w[\w.]*\s+)?([A-Za-z_][\w]*)\s*\{", stripped)
        if match:
            ids.add(match.group(1))
    return ids


class PreferencesAtributosTests(unittest.TestCase):
    """Consistência dos nomes internos usados dentro da classe."""

    def test_todo_metodo_interno_chamado_existe(self) -> None:
        """Regressão (#38): ``self._x(...)`` sempre tem ``_x`` definido.

        Um nome interno errado levanta ``AttributeError`` **dentro** de um
        handler de sinal do GTK, que engole a exceção: o handler morre em
        silêncio e a ação deixa de acontecer. Foi exatamente o que aconteceu
        com a escolha de tema na galeria (``_bloqueio_no_modo`` inexistente),
        sem nenhum sintoma além de "não aplica".
        """
        texto = (ROOT / "cartridges" / "preferences.py").read_text(encoding="utf-8")
        chamadas = set(re.findall(r"self\.(_[A-Za-z]\w*)\s*\(", texto))
        definidos = set(re.findall(r"^\s*def\s+(_[A-Za-z]\w*)\s*\(", texto, re.M))
        atribuidos = set(re.findall(r"self\.(_[A-Za-z]\w*)\s*(?::[^=\n]*)?=", texto))
        faltando = sorted(chamadas - definidos - atribuidos)
        self.assertEqual(
            faltando,
            [],
            f"chamadas a atributos internos inexistentes: {faltando}",
        )


class PreferencesTemplateTests(unittest.TestCase):
    def test_all_childs_exist_in_blueprint(self) -> None:
        childs = template_childs(ROOT / "cartridges" / "preferences.py")
        self.assertGreater(len(childs), 100)
        ids = blueprint_ids(ROOT / "data" / "gtk" / "preferences.blp")
        missing = sorted(childs - ids)
        self.assertEqual(missing, [])

    def test_sunshine_page_exists(self) -> None:
        blp = (ROOT / "data" / "gtk" / "preferences.blp").read_text(
            encoding="utf-8"
        )
        self.assertIn('name: "sunshine";', blp)


if __name__ == "__main__":
    unittest.main()
