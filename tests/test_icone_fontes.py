"""Testes do canal de ícones: nomes por fonte e registro dos recursos.

A interface mostra o ícone de uma fonte na barra lateral e no badge do
card. Duas peças alimentam isso: a lista de nomes candidatos
(`cartridges.utils.launcher`) e o registro dos SVGs enviados pelo app no
tema de ícones do GTK (`cartridges.main`).

Os testes que dependem do GResource compilado pulam quando o app ainda não
foi construído: sem o recurso registrado os ícones não existem e não há o
que verificar.
"""

import builtins
import inspect
import unittest
from pathlib import Path
from types import SimpleNamespace

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gio, GLib, Gtk  # noqa: E402

from cartridges import shared  # noqa: E402
from cartridges.utils import launcher  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]

# Ícones que o app envia: uma fonte (categoria) e uma ação da interface.
RECURSO_DE_ICONE = "/icons/scalable/categories/uzdoom-source-symbolic.svg"
RECURSO_DE_ACAO = "/icons/scalable/actions/trofeu-symbolic.svg"


def _recurso_registrado(prefixo: str, recurso: str) -> bool:
    """Diz se um caminho do GResource já está registrado."""
    try:
        dados = Gio.resources_lookup_data(
            prefixo + recurso, Gio.ResourceLookupFlags.NONE
        )
    except GLib.Error:
        return False
    return dados is not None


def _registrar_gresource() -> None:
    """Registra o GResource compilado do app, quando ele existe.

    :raise unittest.SkipTest: quando o app ainda não foi construído, os
        ícones enviados não existem e não há o que verificar.
    """
    if _recurso_registrado(shared.PREFIX, RECURSO_DE_ICONE):
        return
    candidatos = [
        RAIZ / "build" / "data" / "jolven.gresource",
        Path.home() / ".local" / "share" / "jolven" / "jolven.gresource",
        Path("/usr/local/share/jolven/jolven.gresource"),
        Path("/usr/share/jolven/jolven.gresource"),
    ]
    for candidato in candidatos:
        if candidato.is_file():
            Gio.Resource.load(str(candidato))._register()
            return
    raise unittest.SkipTest(
        "needs the built app: no jolven.gresource found, "
        "the sent icons cannot be verified without it"
    )


class NomesDeIconeDaFonteTests(unittest.TestCase):
    """Candidatos de ícone de cada fonte (módulo puro, sem GTK)."""

    # Fonte -> ID do aplicativo que a plataforma instala.
    FONTES_COM_ICONE_REAL = {
        "uzdoom": "org.zdoom.UZDoom",
        "eden": "dev.eden_emu.eden",
        "cemu": "info.cemu.Cemu",
        "quiver": "io.github.tgeorgiadis.QuiverLauncher",
    }

    def test_asset_enviado_vem_primeiro_nas_fontes_com_simbolo_oficial(self) -> None:
        fontes = ("steam", "heroic", "lutris", "retroarch", "bottles", "itch", "twintail")
        for fonte in fontes:
            with self.subTest(fonte=fonte):
                nomes = launcher.nomes_de_icone_da_fonte(fonte)
                self.assertEqual(nomes[0], f"{fonte}-source-symbolic")

    def test_icone_do_sistema_vem_primeiro_nas_quatro_plataformas(self) -> None:
        """Com a plataforma instalada, o logo verdadeiro é o do sistema.

        É o que o issue #63 pede: o ícone do sistema quando o aplicativo
        está instalado e o asset enviado pelo Jolven quando não está.
        """
        for fonte, icone in self.FONTES_COM_ICONE_REAL.items():
            with self.subTest(fonte=fonte):
                nomes = launcher.nomes_de_icone_da_fonte(fonte)
                self.assertEqual(nomes[0], icone)
                # O símbolo enviado continua na lista: é a reserva para
                # quando a plataforma não está instalada.
                self.assertIn(f"{fonte}-source-symbolic", nomes)
                self.assertLess(nomes.index(icone), nomes.index(f"{fonte}-source-symbolic"))

    def test_nenhum_nome_vem_duplicado(self) -> None:
        fontes = (
            "steam",
            "heroic",
            "lutris",
            "bottles",
            "itch",
            "twintail",
            "retroarch",
            "desktop",
            "xcloud",
            *self.FONTES_COM_ICONE_REAL,
        )
        for fonte in fontes:
            with self.subTest(fonte=fonte):
                nomes = launcher.nomes_de_icone_da_fonte(fonte)
                self.assertEqual(len(nomes), len(set(nomes)))

    def test_fontes_que_funcionavam_mantem_os_nomes(self) -> None:
        esperado = {
            "steam": ("steam-source-symbolic", "com.valvesoftware.Steam", "steam"),
            "heroic": (
                "heroic-source-symbolic",
                "com.heroicgameslauncher.hgl",
                "heroic",
            ),
            "lutris": ("lutris-source-symbolic", "net.lutris.Lutris", "lutris"),
            "bottles": ("bottles-source-symbolic", "com.usebottles.bottles", "bottles"),
            "itch": ("itch-source-symbolic", "io.itch.itch", "itch"),
            "twintail": (
                "twintail-source-symbolic",
                "twintaillauncher",
                "app.twintaillauncher.ttl",
            ),
            "retroarch": (
                "retroarch-source-symbolic",
                "org.libretro.RetroArch",
                "retroarch",
            ),
        }
        for fonte, nomes in esperado.items():
            with self.subTest(fonte=fonte):
                self.assertEqual(launcher.nomes_de_icone_da_fonte(fonte), nomes)

    def test_fontes_especiais_continuam_igual(self) -> None:
        self.assertEqual(
            launcher.nomes_de_icone_da_fonte("desktop"),
            ("desktop-source-symbolic", "user-desktop-symbolic"),
        )
        self.assertEqual(
            launcher.nomes_de_icone_da_fonte("xcloud"),
            ("xbox-cloud-symbolic", "xbox-symbolic", "xbox"),
        )

    def test_emulador_com_icone_proprio_nao_vira_launcher(self) -> None:
        """O ID do emulador não pode entrar na tabela de launchers.

        `_APLICATIVOS` também decide o que é um launcher: com o ID do
        Cemu, do Eden, do UZDoom ou do Quiver lá dentro, o app passaria a
        tratar o Flatpak do emulador como launcher e ele sairia da grade.
        """
        for fonte, icone in self.FONTES_COM_ICONE_REAL.items():
            with self.subTest(fonte=fonte):
                self.assertNotIn(fonte, launcher._APLICATIVOS)
                jogo = SimpleNamespace(
                    base_source="flatpak",
                    game_id=f"flatpak_{icone}",
                    name=fonte,
                )
                self.assertFalse(launcher.detectar(jogo))


class RegistroDeRecursosTests(unittest.TestCase):
    """O caminho de recursos precisa estar no tema para o GTK achar os SVGs."""

    def setUp(self) -> None:
        _registrar_gresource()

    def test_icone_enviado_so_aparece_apos_o_registro(self) -> None:
        from cartridges import main

        tema = Gtk.IconTheme.new()
        self.assertFalse(tema.has_icon("uzdoom-source-symbolic"))
        main.registrar_icones_enviados(tema)
        self.assertTrue(tema.has_icon("uzdoom-source-symbolic"))

    def test_plataformas_do_issue_63_saem_do_icone_generico(self) -> None:
        """As quatro plataformas não podem cair no ícone genérico.

        Era o sintoma relatado: a barra lateral mostrava
        `application-x-executable-symbolic` e o badge do card mostrava o
        ícone de imagem ausente. Basta um nome da lista existir no tema —
        o do sistema quando a plataforma está instalada ou o asset do
        Jolven quando não está.
        """
        from cartridges import main

        tema = Gtk.IconTheme.new()
        main.registrar_icones_enviados(tema)
        for fonte in NomesDeIconeDaFonteTests.FONTES_COM_ICONE_REAL:
            with self.subTest(fonte=fonte):
                nomes = launcher.nomes_de_icone_da_fonte(fonte)
                self.assertTrue(
                    any(tema.has_icon(nome) for nome in nomes),
                    f"{fonte}: nenhum ícone no tema, a fonte cai no genérico",
                )
                # O asset enviado é a reserva obrigatória: existe sempre,
                # mesmo sem a plataforma instalada.
                self.assertTrue(tema.has_icon(f"{fonte}-source-symbolic"))

    def test_icones_de_acao_tambem_sao_encontrados(self) -> None:
        from cartridges import main

        tema = Gtk.IconTheme.new()
        main.registrar_icones_enviados(tema)
        self.assertTrue(tema.has_icon("trofeu-symbolic"))
        self.assertTrue(tema.has_icon("novidades-symbolic"))

    def test_recurso_vive_no_prefixo_do_app(self) -> None:
        self.assertTrue(_recurso_registrado(shared.PREFIX, RECURSO_DE_ICONE))
        self.assertTrue(_recurso_registrado(shared.PREFIX, RECURSO_DE_ACAO))

    def test_ativacao_registra_o_caminho_de_recursos(self) -> None:
        from cartridges import main

        codigo = inspect.getsource(main.CartridgesApplication.do_activate)
        self.assertIn("registrar_icones_enviados", codigo)


if __name__ == "__main__":
    unittest.main()
