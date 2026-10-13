"""Testes de persistência/comportamento do ThemeManager.

GTK/GObject pode não estar disponível no ambiente de teste: nesse caso a
classe é pulada graciosamente (``unittest.SkipTest``) sem falhar a suíte.
"""

import unittest

try:
    from cartridges.themes.manager import ThemeManager
except Exception as _erro_import:  # pragma: no cover - ambiente sem GI
    ThemeManager = None
    _ERRO_IMPORT = _erro_import
else:
    _ERRO_IMPORT = None


@unittest.skipIf(ThemeManager is None, f"GTK/GObject indisponível: {_ERRO_IMPORT}")
class ThemeManagerTests(unittest.TestCase):
    def setUp(self):
        try:
            self.manager = ThemeManager()
        except Exception as erro:  # pragma: no cover - ambiente sem display
            self.skipTest(f"não foi possível instanciar ThemeManager: {erro}")

    def test_estado_inicial(self):
        self.assertEqual(self.manager.slug, "jolven")
        self.assertEqual(self.manager.modo, "auto")
        self.assertFalse(self.manager.glows)
        self.assertFalse(self.manager.steam_skin_ativo)

    def test_set_palette_muda_slug(self):
        self.manager.set_palette("dracula")
        self.assertEqual(self.manager.slug, "dracula")
        self.assertEqual(self.manager.paleta.slug, "dracula")

    def test_set_palette_desconhecido_volta_ao_padrao(self):
        self.manager.set_palette("dracula")
        self.manager.set_palette("nao-existe")
        self.assertEqual(self.manager.slug, "jolven")

    def test_set_mode_muda_modo(self):
        self.manager.set_mode("dark")
        self.assertEqual(self.manager.modo, "dark")
        self.manager.set_mode("light")
        self.assertEqual(self.manager.modo, "light")

    def test_set_mode_invalido_volta_para_auto(self):
        self.manager.set_mode("dark")
        self.manager.set_mode("roxo")
        self.assertEqual(self.manager.modo, "auto")

    def test_set_glows(self):
        self.manager.set_glows(True)
        self.assertTrue(self.manager.glows)
        self.manager.set_glows(False)
        self.assertFalse(self.manager.glows)

    def test_set_acento_custom_nao_explode(self):
        self.manager.set_acento_custom("#ff0000")
        self.assertEqual(self.manager.perfil_compatilhado()["accent_custom"], "#ff0000")
        self.manager.set_acento_custom(None)
        self.assertEqual(self.manager.perfil_compatilhado()["accent_custom"], "")

    def test_acento_custom_invalido_e_ignorado(self):
        self.manager.set_palette("dracula")
        self.manager.set_acento_custom("vermelho")
        perfil = self.manager.perfil_compatilhado()
        self.assertEqual(perfil["accent_custom"], "")
        # Sem custom válido, o accent efetivo é o destaque da paleta.
        self.assertEqual(perfil["accent"], "#bd93f9")

    def test_perfil_compatilhado_tem_as_chaves(self):
        self.manager.set_palette("dracula")
        self.manager.set_mode("dark")
        self.manager.set_glows(True)
        perfil = self.manager.perfil_compatilhado()
        self.assertEqual(
            set(perfil),
            {"theme_slug", "accent", "accent_custom", "mode", "glows"},
        )
        self.assertEqual(perfil["theme_slug"], "dracula")
        self.assertEqual(perfil["mode"], "dark")
        self.assertTrue(perfil["glows"])

    def test_perfil_compartilhado_e_alias(self):
        self.manager.set_palette("nord")
        self.assertEqual(
            self.manager.perfil_compartilhado(),
            self.manager.perfil_compatilhado(),
        )

    def test_listar_catalogo(self):
        slugs = ThemeManager.listar_catalogo()
        self.assertEqual(len(slugs), 24)
        self.assertIn("jolven", slugs)

    def test_info_do_tema(self):
        info = ThemeManager.info_do_tema("oled")
        self.assertEqual(info["name"], "OLED")
        self.assertTrue(info["is_dark_only"])
        self.assertEqual(info["accent_bg"], "#ff6e4a")


if __name__ == "__main__":
    unittest.main()
