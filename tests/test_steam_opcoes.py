"""Reparo de instalação quebrada e opções avançadas da skin da Steam.

Todos os testes usam diretórios temporários que imitam ``<steam>/steamui``.
A Steam real do usuário (``~/.steam``, ``~/.var/app``) nunca é tocada.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from cartridges.integrations.steam_skin import installer, vendor
from cartridges.integrations.steam_skin.constants import PATCH_HEADER
from cartridges.integrations.steam_skin.manager import SteamSkinManager
from cartridges.integrations.steam_skin.recovery import (
    Estado,
    precisa_reparo,
    reparar_se_seguro,
    verificar_estado,
)

CSS_NAMES = ("library.css", "gamerecording.css", "gamenotes.css")

OPCOES_CHEIAS = {
    "font": "cantarell",
    "windowcontrols_theme": "theme",
    "windowcontrols_layout": "left",
    "rounded_corners": False,
    "cursor_pointer": True,
    "hide_whats_new": True,
    "sidebar_hover": True,
    "uncrop_covers": True,
    "hide_qr": True,
}


class _SteamFixture(unittest.TestCase):
    TAMANHO = 4096

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "steam"
        css = self.root / "steamui" / "css"
        css.mkdir(parents=True, exist_ok=True)
        for nome in CSS_NAMES:
            (css / nome).write_bytes(
                (f"/* {nome} Steam original */\n" + "x" * self.TAMANHO + "\n").encode()
            )

    def tearDown(self):
        self._tmp.cleanup()

    def _config(self) -> str:
        return (self.root / "steamui" / "adwaita" / "config.css").read_text(
            encoding="utf-8"
        )


class _FakeSettings:
    """GSettings mínimo para o manager (caminho fixo, toggle desligado)."""

    def __init__(self, caminho: Path, habilitado: bool = False) -> None:
        self._caminho = caminho
        self._habilitado = habilitado

    def list_keys(self):
        return ["steam-skin-enabled", "steam-install-path"]

    def get_string(self, chave: str) -> str:
        return str(self._caminho) if chave == "steam-install-path" else ""

    def get_boolean(self, chave: str) -> bool:
        return self._habilitado if chave == "steam-skin-enabled" else False


class ReparoIncompativelTests(_SteamFixture):
    def test_skin_sem_diretorio_volta_a_sincronizar(self):
        installer.instalar(self.root, "dracula", "#ff0000", "dark")
        shutil.rmtree(self.root / "steamui" / "adwaita")

        self.assertEqual(verificar_estado(self.root), Estado.INCOMPATIVEL)
        self.assertTrue(precisa_reparo(self.root))

        self.assertTrue(reparar_se_seguro(self.root, {"theme_slug": "dracula"}))
        self.assertEqual(verificar_estado(self.root), Estado.SINCRONIZADA)
        self.assertTrue(installer.totalmente_instalada(self.root))

    def test_backup_ausente_nao_quebra_nem_perde_patch(self):
        installer.instalar(self.root, "dracula", "#ff0000", "dark")
        backups = list((self.root / "steamui" / "css").glob("*.original.css"))
        self.assertTrue(backups)
        backups[0].unlink()

        self.assertEqual(verificar_estado(self.root), Estado.INCOMPATIVEL)
        # Sem exceção e sem tocar no cabeçalho: o reparo é seguro mesmo sem
        # o backup (o original já estava perdido; nada novo é destruído).
        self.assertTrue(reparar_se_seguro(self.root, {"theme_slug": "dracula"}))
        for nome in CSS_NAMES:
            with self.subTest(css=nome):
                caminho = self.root / "steamui" / "css" / nome
                self.assertEqual(installer.primeira_linha(caminho), PATCH_HEADER)
        # Sem backup o estado segue INCOMPATIVEL (documentado: não há como
        # recriar o original perdido).
        self.assertEqual(verificar_estado(self.root), Estado.INCOMPATIVEL)

    def test_conflito_de_terceiros_continua_recusado(self):
        caminho = self.root / "steamui" / "css" / "library.css"
        caminho.write_text("/* Millennium patched */\n.x{}\n", encoding="utf-8")
        self.assertEqual(verificar_estado(self.root), Estado.CONFLITO_TERCEIROS)

        antes = caminho.read_bytes()
        self.assertFalse(reparar_se_seguro(self.root, {"theme_slug": "dracula"}))
        self.assertEqual(caminho.read_bytes(), antes)
        self.assertFalse(precisa_reparo(self.root))


class RepararManagerTests(_SteamFixture):
    def _perfil(self) -> dict:
        return {
            "theme_slug": "dracula",
            "accent": "#ff0000",
            "mode": "dark",
            "opcoes_avancadas": dict(OPCOES_CHEIAS),
        }

    def test_reparar_funciona_com_toggle_desligado(self):
        installer.instalar(self.root, "dracula", "#ff0000", "dark")
        shutil.rmtree(self.root / "steamui" / "adwaita")
        self.assertEqual(verificar_estado(self.root), Estado.INCOMPATIVEL)

        manager = SteamSkinManager(schema=_FakeSettings(self.root, habilitado=False))
        self.assertFalse(manager.habilitado())
        self.assertTrue(manager.reparar(self._perfil()))
        self.assertEqual(verificar_estado(self.root), Estado.SINCRONIZADA)

    def test_reparar_recusa_conflito(self):
        caminho = self.root / "steamui" / "css" / "library.css"
        caminho.write_text("/* Millennium patched */\n.x{}\n", encoding="utf-8")
        manager = SteamSkinManager(schema=_FakeSettings(self.root, habilitado=True))
        self.assertFalse(manager.reparar(self._perfil()))
        self.assertEqual(caminho.read_text(encoding="utf-8"), "/* Millennium patched */\n.x{}\n")

    def test_reparar_sem_steam_retorna_falso(self):
        manager = SteamSkinManager(
            schema=_FakeSettings(Path(self._tmp.name) / "inexistente")
        )
        self.assertFalse(manager.reparar(self._perfil()))


class OpcoesSuportadasTests(unittest.TestCase):
    ESPERADAS = {
        "font",
        "windowcontrols_theme",
        "windowcontrols_layout",
        "rounded_corners",
        "cursor_pointer",
        "hide_whats_new",
        "sidebar_hover",
        "uncrop_covers",
        "hide_qr",
    }

    def test_vendor_real_anuncia_as_nove_opcoes(self):
        self.assertEqual(SteamSkinManager.opcoes_suportadas(), self.ESPERADAS)

    def _vendor_minimo(self, base: Path) -> Path:
        raiz = base / "vendor-minimo"
        (raiz / "colorthemes" / "x").mkdir(parents=True)
        (raiz / "palette.css").write_text(":root{}\n", encoding="utf-8")
        (raiz / "colorthemes" / "x" / "x.css").write_text(":root{}\n", encoding="utf-8")
        return raiz

    def test_vendor_minimo_anuncia_conjunto_vazio(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = self._vendor_minimo(Path(tmp))
            anterior = os.environ.get(vendor.VENDOR_ENV)
            os.environ[vendor.VENDOR_ENV] = str(raiz)
            try:
                self.assertEqual(SteamSkinManager.opcoes_suportadas(), set())
            finally:
                if anterior is None:
                    del os.environ[vendor.VENDOR_ENV]
                else:
                    os.environ[vendor.VENDOR_ENV] = anterior

    def test_vendor_so_fontes_anuncia_so_font(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = self._vendor_minimo(Path(tmp))
            fontes = raiz / "fonts" / "adwaita"
            fontes.mkdir(parents=True)
            (fontes / "adwaita.css").write_text(":root{}\n", encoding="utf-8")
            anterior = os.environ.get(vendor.VENDOR_ENV)
            os.environ[vendor.VENDOR_ENV] = str(raiz)
            try:
                self.assertEqual(SteamSkinManager.opcoes_suportadas(), {"font"})
            finally:
                if anterior is None:
                    del os.environ[vendor.VENDOR_ENV]
                else:
                    os.environ[vendor.VENDOR_ENV] = anterior


class ConfigCssTests(_SteamFixture):
    def test_opcoes_cheias_viram_config_e_arvore(self):
        self.assertTrue(
            installer.instalar(self.root, "dracula", "#ff0000", "dark", dict(OPCOES_CHEIAS))
        )
        config = self._config()
        for esperado in (
            'extras/general/no-rounded-corners.css',
            'extras/general/cursor-pointer.css',
            'extras/library/hide-whats-new.css',
            'extras/library/sidebar-hover.css',
            'extras/library/uncrop-covers-in-details.css',
            'extras/login/hide-qr.css',
            'fonts/cantarell/cantarell.css',
            'windowcontrols/adwaita.css',
            '--adw-windowcontrols-left-buttons: 3;',
            '.title-bar-actions.window-controls .title-area-icon',
        ):
            with self.subTest(esperado=esperado):
                self.assertIn(esperado, config)

        arvore = self.root / "steamui" / "adwaita"
        for relativo in (
            "extras/general/cursor-pointer.css",
            "extras/library/hide-whats-new.css",
            "windowcontrols/adwaita.css",
            "fonts/cantarell/cantarell.css",
            "fonts/cantarell/cantarell-vf.otf",
            "fonts/adwaita/adwaita.css",
            "config.css",
        ):
            with self.subTest(arquivo=relativo):
                self.assertTrue((arvore / relativo).is_file())

    def test_layout_padrao_nao_emite_bloco(self):
        installer.instalar(self.root, "dracula", "#ff0000", "dark", {"windowcontrols_layout": "default"})
        self.assertNotIn("windowcontrols-left-buttons", self._config())

    def test_baseline_sem_opcoes_nao_muda(self):
        self.assertTrue(installer.instalar(self.root, "dracula", "#ff0000", "dark"))
        config = self._config()
        self.assertNotIn("extras/", config)
        self.assertNotIn("fonts/", config)
        self.assertNotIn("windowcontrols", config)
        # Segunda execução idêntica continua sendo no-op.
        self.assertFalse(installer.instalar(self.root, "dracula", "#ff0000", "dark"))

    def test_cantos_arredondados_padrao_nao_desliga(self):
        installer.instalar(self.root, "dracula", "#ff0000", "dark", {})
        self.assertNotIn("no-rounded-corners", self._config())


if __name__ == "__main__":
    unittest.main()
