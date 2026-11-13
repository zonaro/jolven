import unittest
from unittest import mock

from cartridges import shared
from cartridges.utils import gschema


class SchemaAvailableTests(unittest.TestCase):
    def test_unknown_schema_is_unavailable(self):
        self.assertFalse(gschema.schema_available("org.example.does.not.exist"))

    def test_own_schema_is_available(self):
        self.assertTrue(gschema.schema_available(shared.APP_ID))

    def test_missing_gi_is_unavailable(self):
        # Sem ``gi`` a resposta e False, como em qualquer maquina sem o schema:
        # quem chama segue pelo fallback em vez de morrer no import.
        with mock.patch.dict("sys.modules", {"gi": None, "gi.repository": None}):
            self.assertFalse(
                gschema.schema_available("org.gnome.desktop.interface")
            )


class SteamAccentTests(unittest.TestCase):
    def test_accent_falls_back_without_the_gnome_schema(self):
        # Regressao do aborto no CI: sem o schema, ``Gio.Settings.new`` mata o
        # processo (g_error) e o except do chamador nunca roda.
        from cartridges.integrations.steam_skin import installer

        with mock.patch.object(installer, "schema_available", return_value=False):
            self.assertEqual(
                installer._system_accent_css(), "var(--adw-accent-blue)"
            )

    def test_accent_is_resolved_when_the_schema_exists(self):
        from cartridges.integrations.steam_skin import installer

        if not gschema.schema_available(installer._INTERFACE_SCHEMA):
            self.skipTest("org.gnome.desktop.interface is not installed")
        valor = installer._system_accent_css()
        self.assertTrue(
            valor.startswith("var(--adw-accent-") or valor.startswith("#"), valor
        )


class SessionWallpaperTests(unittest.TestCase):
    def test_wallpaper_config_degrades_without_the_gnome_schema(self):
        from cartridges.utils import session_wallpaper

        with mock.patch.object(
            session_wallpaper, "schema_available", return_value=False
        ):
            fundo = session_wallpaper._Fundo()
        self.assertIsNone(fundo._config)

    def test_wallpaper_config_opens_when_the_schema_exists(self):
        from cartridges.utils import session_wallpaper

        if not gschema.schema_available(session_wallpaper._PAREDE_SCHEMA):
            self.skipTest("org.gnome.desktop.background is not installed")
        self.assertIsNotNone(session_wallpaper._Fundo()._config)


if __name__ == "__main__":
    unittest.main()
