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


def declared_ids(source: Path) -> list[str]:
    """Ids declarados no Blueprint, na ordem e com repetição.

    Um id declarado duas vezes (dois widgets com o mesmo nome) quebra o
    template em runtime: o GTK reclama do id duplicado ao construir o
    diálogo. A lista mantém as repetições justamente para permitir
    detectar isso.
    """
    ids: list[str] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "using", "menu ", "item ")):
            continue
        stripped = re.sub(r"^\w+:\s*", "", stripped)
        match = re.match(r"(?:\w[\w.]*\s+)?([A-Za-z_][\w]*)\s*\{", stripped)
        if match:
            ids.append(match.group(1))
    return ids


def blueprint_block(source: Path, opening: str) -> str:
    """Recorta o bloco Blueprint que começa na linha com ``opening``.

    Conta as chaves para achar o fechamento correto (o bloco pode conter
    sub-blocos). Devolve string vazio quando a abertura não existe.
    """
    lines = source.read_text(encoding="utf-8").splitlines()
    start = None
    for index, line in enumerate(lines):
        if opening in line:
            start = index
            break
    if start is None:
        return ""
    depth = 0
    for index in range(start, len(lines)):
        depth += lines[index].count("{") - lines[index].count("}")
        if depth <= 0 and index > start:
            return "\n".join(lines[start : index + 1])
    return "\n".join(lines[start:])


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


class GameSessionPreferencesTests(unittest.TestCase):
    """Instalação/remoção da Jolven Session pela tela de Preferências.

    A ação da sessão do display manager é privilégio do helper autorizado:
    o widget precisa existir no Blueprint, o Python precisa do
    ``Gtk.Template.Child`` correspondente e a operação não pode rodar na
    thread GTK.
    """

    IDS = ("game_session_install_group", "game_session_row", "game_session_button")

    @property
    def blp_path(self) -> Path:
        return ROOT / "data" / "gtk" / "preferences.blp"

    def test_grupo_e_rola_existem_na_pagina_de_sessao(self) -> None:
        pagina = blueprint_block(self.blp_path, "Adw.PreferencesPage session_page")
        self.assertIn("Adw.PreferencesGroup game_session_install_group", pagina)

        grupo = blueprint_block(
            self.blp_path, "Adw.PreferencesGroup game_session_install_group"
        )
        self.assertIn("Adw.ActionRow game_session_row", grupo)
        self.assertIn("activatable-widget: game_session_button;", grupo)
        self.assertIn("[suffix]", grupo)
        self.assertIn("Button game_session_button", grupo)

    def test_grupo_vem_depois_do_grupo_de_game_mode(self) -> None:
        blp = self.blp_path.read_text(encoding="utf-8")
        self.assertLess(
            blp.index("game_mode_group {"),
            blp.index("game_session_install_group {"),
        )

    def test_ids_novos_declarados_uma_vez(self) -> None:
        declarados = declared_ids(self.blp_path)
        for nome in self.IDS:
            with self.subTest(id=nome):
                self.assertEqual(
                    declarados.count(nome),
                    1,
                    f"id {nome} declarado mais de uma vez no Blueprint",
                )

    def test_childs_novos_declarados_no_python(self) -> None:
        childs = template_childs(ROOT / "cartridges" / "preferences.py")
        for nome in self.IDS:
            with self.subTest(id=nome):
                self.assertIn(nome, childs)

    def test_grupo_novo_tem_tipo_de_preferences_group(self) -> None:
        texto = (ROOT / "cartridges" / "preferences.py").read_text(encoding="utf-8")
        self.assertIn(
            "game_session_install_group: Adw.PreferencesGroup = Gtk.Template.Child()",
            texto,
        )

    def test_acao_nao_roda_na_thread_gtk(self) -> None:
        texto = (ROOT / "cartridges" / "preferences.py").read_text(encoding="utf-8")
        self.assertIn(
            'self.game_session_button.connect("clicked", self.alternar_game_session)',
            texto,
        )
        # O helper roda em thread própria e o resultado volta para a tela.
        self.assertIn("setup_async(", texto)
        self.assertIn("entregar_na_tela(self._concluir_game_session", texto)
        self.assertIn(
            "threading.Thread(\n            target=self._carregar_estado_game_session",
            texto,
        )


if __name__ == "__main__":
    unittest.main()
