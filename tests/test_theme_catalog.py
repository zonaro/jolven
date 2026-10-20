"""Testes do catálogo de temas do Jolven (módulo puro, sem GTK)."""

import unittest
from pathlib import Path

from cartridges.themes.catalog import (
    CATALOGO,
    CATALOG_SLUGS,
    DEFAULT_SLUG,
    IS_DARK_ONLY_BY_SLUG,
    NAMES_BY_SLUG,
    carregar_catalogo,
    get_palette,
    modo_do_tema,
    nome_do_tema,
    obter_tema,
    palette_for_mode,
    slug_é_dark_only,
    tema_padrao,
)
from cartridges.themes.palette import Palette, load_palette_from_css, validar_hex

RAIZ = Path(__file__).resolve().parents[1]
PALETAS = RAIZ / "data" / "themes" / "palettes"


class CatalogoTests(unittest.TestCase):
    def test_catalogo_tem_24_temas(self):
        self.assertEqual(len(CATALOGO), 24)

    def test_chaves_batem_com_slug_das_paletas(self):
        for slug, paleta in CATALOGO.items():
            with self.subTest(slug=slug):
                self.assertIsInstance(paleta, Palette)
                self.assertEqual(paleta.slug, slug)

    def test_jolven_presente(self):
        self.assertIn("jolven", CATALOGO)
        self.assertEqual(DEFAULT_SLUG, "jolven")

    def test_tema_padrao_e_jolven(self):
        self.assertEqual(tema_padrao().slug, "jolven")
        self.assertEqual(tema_padrao().slug, DEFAULT_SLUG)

    def test_carregar_catalogo_e_idempotente(self):
        self.assertIs(carregar_catalogo(), CATALOGO)
        self.assertEqual(carregar_catalogo(), carregar_catalogo())

    def test_obter_tema_desconhecido_cai_no_padrao(self):
        self.assertEqual(obter_tema("nao-existe").slug, "jolven")
        self.assertEqual(obter_tema(None).slug, "jolven")
        self.assertEqual(obter_tema("").slug, "jolven")

    def test_get_palette_e_alias(self):
        self.assertIs(get_palette("dracula"), obter_tema("dracula"))

    def test_dark_only(self):
        self.assertTrue(slug_é_dark_only("oled"))
        self.assertFalse(slug_é_dark_only("catppuccin-latte"))
        self.assertFalse(slug_é_dark_only("nord"))
        self.assertTrue(IS_DARK_ONLY_BY_SLUG["oled"])

    def test_modo_do_tema_sugerido(self):
        self.assertIn(modo_do_tema("jolven"), ("dark", "light"))
        self.assertEqual(modo_do_tema("adwaita"), "light")
        self.assertEqual(modo_do_tema("adwaita-gray"), "dark")
        self.assertEqual(modo_do_tema("nord"), "dark")
        self.assertEqual(modo_do_tema("oled"), "dark")

        self.assertFalse(IS_DARK_ONLY_BY_SLUG["catppuccin-latte"])

    def test_nome_do_tema_gruvbox(self):
        # Guarda contra a grafia "gruvox" que já apareceu na base.
        self.assertEqual(nome_do_tema("gruvbox"), "Gruvbox")
        self.assertNotEqual(nome_do_tema("gruvbox"), "gruvox")
        self.assertEqual(NAMES_BY_SLUG["gruvbox"], "Gruvbox")

    def test_toda_paleta_tem_accent_bg_hex_valido(self):
        for slug, paleta in CATALOGO.items():
            with self.subTest(slug=slug):
                self.assertIsNotNone(paleta.accent_bg)
                self.assertEqual(validar_hex(paleta.accent_bg), paleta.accent_bg)
                if paleta.accent_fg is not None:
                    self.assertEqual(validar_hex(paleta.accent_fg), paleta.accent_fg)

    def test_catalog_slugs_espelha_o_catalogo(self):
        self.assertEqual(CATALOG_SLUGS, list(CATALOGO))

    def test_palette_for_mode_e_coerente(self):
        for slug in ("jolven", "dracula", "catppuccin-latte"):
            with self.subTest(slug=slug):
                self.assertIs(palette_for_mode(slug, "dark"), obter_tema(slug))
                self.assertIs(palette_for_mode(slug, "light"), obter_tema(slug))
                self.assertEqual(palette_for_mode(slug, "dark").slug, slug)

    def test_css_variables_emite_acentos(self):
        variaveis = obter_tema("dracula").css_variables()
        self.assertEqual(variaveis["--accent-bg-color"], "#bd93f9")
        self.assertEqual(variaveis["--accent-color"], "#f8f8f2")


class PaletteTests(unittest.TestCase):
    def test_validar_hex(self):
        self.assertEqual(validar_hex("#ff0000"), "#ff0000")
        self.assertEqual(validar_hex("  #abc  "), "#abc")
        self.assertEqual(validar_hex("#abcd"), "#abcd")
        self.assertEqual(validar_hex("#11223344"), "#11223344")
        self.assertIsNone(validar_hex("red"))
        self.assertIsNone(validar_hex("#gggggg"))
        self.assertIsNone(validar_hex(None))
        self.assertIsNone(validar_hex(123))

    def test_load_palette_from_css(self):
        paleta = load_palette_from_css(PALETAS / "catppuccin-mocha.css")
        self.assertIsNotNone(paleta)
        self.assertEqual(paleta.accent_bg, "#cba6f7")
        self.assertEqual(paleta.accent_fg, "#cdd6f4")
        self.assertEqual(paleta.slug, "catppuccin-mocha")

    def test_load_palette_from_css_inexistente(self):
        self.assertIsNone(load_palette_from_css(PALETAS / "nao-existe.css"))

    def test_load_palette_from_css_sem_cores(self):
        import tempfile

        with tempfile.TemporaryDirectory() as diretorio:
            caminho = Path(diretorio) / "vazio.css"
            caminho.write_text("body { color: red; }\n", encoding="utf-8")
            self.assertIsNone(load_palette_from_css(caminho))


if __name__ == "__main__":
    unittest.main()
