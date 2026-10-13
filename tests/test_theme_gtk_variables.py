"""Testes da paleta completa do libadwaita (módulo puro, sem GTK).

Cobre ``Palette.gtk_variables()`` e o CSS ``:root`` gerado pelo
``gtk_engine``: presença das variáveis-chave, textos legíveis por luminância,
ausência de cores semânticas e idempotência/estabilidade.
"""

import re
import unittest

from cartridges.themes.catalog import CATALOGO, obter_tema
from cartridges.themes.palette import Palette, cor_contraste

try:
    from cartridges.themes import gtk_engine
except Exception as _erro_import:  # pragma: no cover - ambiente sem GI
    gtk_engine = None
    _ERRO_IMPORT = _erro_import
else:
    _ERRO_IMPORT = None

#: Nomes verificados no gtk.css do libadwaita 1.9.4 (ordem de emissão).
VARIAVEIS_ESPERADAS = (
    "--window-bg-color",
    "--window-fg-color",
    "--view-bg-color",
    "--view-fg-color",
    "--headerbar-bg-color",
    "--headerbar-fg-color",
    "--headerbar-backdrop-color",
    "--headerbar-border-color",
    "--headerbar-shade-color",
    "--headerbar-darker-shade-color",
    "--sidebar-bg-color",
    "--sidebar-fg-color",
    "--sidebar-backdrop-color",
    "--sidebar-border-color",
    "--sidebar-shade-color",
    "--secondary-sidebar-bg-color",
    "--secondary-sidebar-fg-color",
    "--secondary-sidebar-backdrop-color",
    "--secondary-sidebar-border-color",
    "--secondary-sidebar-shade-color",
    "--card-bg-color",
    "--card-fg-color",
    "--card-shade-color",
    "--dialog-bg-color",
    "--dialog-fg-color",
    "--popover-bg-color",
    "--popover-fg-color",
    "--popover-shade-color",
    "--thumbnail-bg-color",
    "--thumbnail-fg-color",
    "--accent-bg-color",
    "--accent-fg-color",
    "--border-color",
    "--shade-color",
)

#: Pares (fundo, texto) cuja legibilidade é verificada por luminância.
PARES_FG = (
    ("--window-bg-color", "--window-fg-color"),
    ("--view-bg-color", "--view-fg-color"),
    ("--headerbar-bg-color", "--headerbar-fg-color"),
    ("--sidebar-bg-color", "--sidebar-fg-color"),
    ("--secondary-sidebar-bg-color", "--secondary-sidebar-fg-color"),
    ("--card-bg-color", "--card-fg-color"),
    ("--dialog-bg-color", "--dialog-fg-color"),
    ("--popover-bg-color", "--popover-fg-color"),
    ("--thumbnail-bg-color", "--thumbnail-fg-color"),
    ("--accent-bg-color", "--accent-fg-color"),
)

_HEX = re.compile(r"^#(?:[0-9A-Fa-f]{3,4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")
_RGBA = re.compile(r"^rgba\(\d{1,3},\s*\d{1,3},\s*\d{1,3},\s*[\d.]+\)$")
_NOMEADOS = {"white": (255, 255, 255), "black": (0, 0, 0)}


def _luminancia_independente(cor: str) -> float:
    """Luminância calculada aqui no teste, sem reutilizar a produção."""
    nome = cor.strip().lower()
    if nome in _NOMEADOS:
        vermelho, verde, azul = _NOMEADOS[nome]
    else:
        texto = nome.lstrip("#")
        if len(texto) in (3, 4):
            texto = "".join(c * 2 for c in texto[:3])
        vermelho, verde, azul = (
            int(texto[0:2], 16),
            int(texto[2:4], 16),
            int(texto[4:6], 16),
        )
    return (0.2126 * vermelho + 0.7152 * verde + 0.0722 * azul) / 255


class GtkVariablesTests(unittest.TestCase):
    def test_todas_as_variaveis_em_todo_o_catalogo(self):
        for slug, paleta in CATALOGO.items():
            for modo in ("light", "dark"):
                with self.subTest(slug=slug, modo=modo):
                    variaveis = paleta.gtk_variables(modo)
                    self.assertEqual(list(variaveis), list(VARIAVEIS_ESPERADAS))
                    for valor in variaveis.values():
                        self.assertIsInstance(valor, str)
                        self.assertTrue(valor)
                        self.assertTrue(
                            _HEX.match(valor)
                            or _RGBA.match(valor)
                            or valor in _NOMEADOS,
                            f"valor inválido para CSS: {valor!r}",
                        )

    def test_sem_cores_semanticas(self):
        for slug, paleta in CATALOGO.items():
            with self.subTest(slug=slug):
                for chave in paleta.gtk_variables("dark"):
                    self.assertFalse(
                        chave.startswith(
                            (
                                "--destructive-",
                                "--success-",
                                "--warning-",
                                "--error-",
                            )
                        ),
                        f"{chave} sobrescreve cor semântica do libadwaita",
                    )

    def test_fg_legivel_por_luminancia(self):
        for slug, paleta in CATALOGO.items():
            for modo in ("light", "dark"):
                with self.subTest(slug=slug, modo=modo):
                    variaveis = paleta.gtk_variables(modo)
                    for fundo_var, texto_var in PARES_FG:
                        fundo = _luminancia_independente(variaveis[fundo_var])
                        texto = variaveis[texto_var]
                        if fundo < 0.5:
                            self.assertEqual(texto, "white", fundo_var)
                        else:
                            self.assertEqual(texto, "black", fundo_var)

    def test_fg_spot_check(self):
        # Dracula tem fundo escuro -> texto claro; Kate tem fundo claro.
        dracula = obter_tema("dracula").gtk_variables("dark")
        self.assertEqual(dracula["--window-fg-color"], "white")
        self.assertEqual(dracula["--headerbar-fg-color"], "white")
        kate = obter_tema("kate").gtk_variables("light")
        self.assertEqual(kate["--window-fg-color"], "black")
        self.assertEqual(kate["--card-fg-color"], "black")

    def test_derivacao_dos_fundos(self):
        dracula = obter_tema("dracula")
        variaveis = dracula.gtk_variables("dark")
        self.assertEqual(variaveis["--window-bg-color"], "#282a36")
        self.assertEqual(variaveis["--view-bg-color"], "#282a36")
        self.assertEqual(variaveis["--dialog-bg-color"], "#282a36")
        self.assertEqual(variaveis["--headerbar-bg-color"], "#21222c")
        self.assertEqual(variaveis["--sidebar-bg-color"], "#21222c")
        self.assertEqual(variaveis["--card-bg-color"], "#44475a")
        self.assertEqual(variaveis["--popover-bg-color"], "#44475a")
        self.assertEqual(variaveis["--secondary-sidebar-bg-color"], "#44475a")
        self.assertEqual(variaveis["--thumbnail-bg-color"], "#44475a")
        self.assertEqual(variaveis["--border-color"], "#6272a4")

    def test_accent_vars(self):
        variaveis = obter_tema("dracula").gtk_variables("dark")
        self.assertEqual(variaveis["--accent-bg-color"], "#bd93f9")
        # --accent-fg-color é o contraste sobre o accent (legível).
        self.assertEqual(
            variaveis["--accent-fg-color"],
            cor_contraste(variaveis["--accent-bg-color"]),
        )
        # --accent-color NÃO é emitido: o libadwaita deriva o acento
        # "standalone" do nosso --accent-bg-color.
        self.assertNotIn("--accent-color", variaveis)

    def test_accent_acompanha_o_tema(self):
        """Trocar de tema troca o destaque (issue #38), também na Steam."""
        vistos = {}
        for slug in ("jolven", "dracula", "oled", "nord", "catppuccin-mocha"):
            vistos[slug] = obter_tema(slug).gtk_variables("dark")["--accent-bg-color"]
        # Cada tema tem um destaque próprio — nada de um azul fixo compartilhado.
        self.assertEqual(len(vistos), len(set(vistos.values())))
        self.assertEqual(vistos["jolven"], "#c9a7f5")
        self.assertEqual(vistos["dracula"], "#bd93f9")
        self.assertEqual(vistos["oled"], "#ff6e4a")

    def test_shade_por_modo(self):
        escuro = obter_tema("jolven").gtk_variables("dark")["--shade-color"]
        claro = obter_tema("jolven").gtk_variables("light")["--shade-color"]
        self.assertEqual(escuro, "rgba(0, 0, 0, 0.36)")
        self.assertEqual(claro, "rgba(0, 0, 0, 0.12)")

    def test_backdrop_shade_derivam_do_fundo(self):
        variaveis = obter_tema("dracula").gtk_variables("dark")
        headerbar = variaveis["--headerbar-bg-color"]
        self.assertNotEqual(variaveis["--headerbar-backdrop-color"], headerbar)
        self.assertNotEqual(variaveis["--headerbar-shade-color"], headerbar)
        self.assertNotEqual(
            variaveis["--headerbar-darker-shade-color"], headerbar
        )
        self.assertLess(
            _luminancia_independente(variaveis["--headerbar-darker-shade-color"]),
            _luminancia_independente(headerbar),
        )

    def test_recuso_com_paleta_minima(self):
        paleta = Palette(slug="minima", name="Mínima")
        for modo in ("light", "dark"):
            with self.subTest(modo=modo):
                variaveis = paleta.gtk_variables(modo)
                self.assertEqual(list(variaveis), list(VARIAVEIS_ESPERADAS))
                for valor in variaveis.values():
                    self.assertTrue(valor)
                    self.assertTrue(
                        _HEX.match(valor)
                        or _RGBA.match(valor)
                        or valor in _NOMEADOS
                    )

    def test_suplementar_aceita_hifen_e_underscore(self):
        com_hifen = Palette(
            slug="a",
            name="A",
            bg="#282a36",
            supplementary={"card-bg": "#44475a", "border": "#6272a4"},
        )
        self.assertEqual(
            com_hifen.gtk_variables("dark")["--card-bg-color"], "#44475a"
        )
        com_underscore = Palette(
            slug="b",
            name="B",
            bg="#282a36",
            supplementary={"card_bg": "#44475a", "border": "#6272a4"},
        )
        self.assertEqual(
            com_underscore.gtk_variables("dark")["--card-bg-color"], "#44475a"
        )

    def test_idempotente_e_estavel(self):
        paleta = obter_tema("tokyo-night")
        self.assertEqual(
            paleta.gtk_variables("dark"), paleta.gtk_variables("dark")
        )
        self.assertEqual(
            paleta.gtk_variables("light"), paleta.gtk_variables("light")
        )

    def test_modo_desconhecido_cai_no_escuro(self):
        paleta = obter_tema("jolven")
        self.assertEqual(paleta.gtk_variables("auto"), paleta.gtk_variables("dark"))

    def test_cor_contraste(self):
        self.assertEqual(cor_contraste("#000000"), "white")
        self.assertEqual(cor_contraste("#ffffff"), "black")
        self.assertEqual(cor_contraste("#1e1e2e"), "white")
        self.assertEqual(cor_contraste("#fafafa"), "black")
        self.assertEqual(cor_contraste("invalida"), "white")


@unittest.skipIf(gtk_engine is None, f"GTK/GObject indisponível: {_ERRO_IMPORT}")
class CssGeradoTests(unittest.TestCase):
    def test_contem_as_variaveis_chave(self):
        css = gtk_engine._gerar_css(obter_tema("dracula"), "dark", False, None)
        for chave in (
            "--window-bg-color",
            "--headerbar-bg-color",
            "--card-bg-color",
            "--accent-bg-color",
            "--accent-fg-color",
            "--border-color",
        ):
            self.assertIn(chave, css)
        # --accent-color NÃO é emitido: o libadwaita deriva do --accent-bg-color.
        self.assertNotIn("--accent-color", css)
        self.assertIn("--window-bg-color: #282a36;", css)
        self.assertNotIn("--destructive-", css)
        self.assertNotIn("--success-", css)

    def test_acento_custom_sobrescreve_duas_vars(self):
        css = gtk_engine._gerar_css(obter_tema("dracula"), "dark", False, "#ff0000")
        self.assertIn("--accent-bg-color: #ff0000;", css)
        self.assertIn(f"--accent-fg-color: {cor_contraste('#ff0000')};", css)
        # --accent-color NÃO é emitido nem no caso custom: o libadwaita
        # deriva do --accent-bg-color.
        self.assertNotIn("--accent-color", css)
        # O resto da paleta continua valendo.
        self.assertIn("--window-bg-color: #282a36;", css)

    def test_idempotente(self):
        paleta = obter_tema("gruvbox")
        primeira = gtk_engine._gerar_css(paleta, "dark", False, None)
        segunda = gtk_engine._gerar_css(paleta, "dark", False, None)
        self.assertEqual(primeira, segunda)

    def test_glow_so_no_jolven(self):
        com_glow = gtk_engine._gerar_css(obter_tema("jolven"), "dark", True, None)
        self.assertIn("jolven-glow", com_glow)
        sem_glow = gtk_engine._gerar_css(obter_tema("dracula"), "dark", True, None)
        self.assertNotIn("jolven-glow", sem_glow)


if __name__ == "__main__":
    unittest.main()
