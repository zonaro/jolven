"""Testes de instalação/restauração/recuperação da skin do Steam.

Todos os testes usam diretórios temporários que imitam ``<steam>/steamui``.
A Steam real do usuário (``~/.steam``, ``~/.var/app``) nunca é tocada.
"""

import os
import tempfile
import unittest
from pathlib import Path

from cartridges.integrations.steam_skin import installer, vendor
from cartridges.integrations.steam_skin.constants import PATCH_HEADER
from cartridges.integrations.steam_skin.recovery import (
    Estado,
    precisa_reparo,
    reparar_se_seguro,
    verificar_estado,
)

CSS_NAMES = ("library.css", "gamerecording.css", "gamenotes.css")


def _patch_bytes(raiz: Path, nome: str) -> bytes:
    return (raiz / "steamui" / "css" / nome).read_bytes()


class _SteamFixture(unittest.TestCase):
    #: Tamanho das CSS originais, grande o bastante para caber o patch.
    TAMANHO = 4096

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "steam"
        self.originals = self._criar_arvore(self.root)

    def tearDown(self):
        # Restaura permissões (alguns testes deixam diretórios read-only).
        for caminho in sorted(self.root.rglob("*"), reverse=True):
            try:
                os.chmod(caminho, 0o755 if caminho.is_dir() else 0o644)
            except OSError:
                pass
        self._tmp.cleanup()

    def _criar_arvore(self, raiz: Path, tamanho: int | None = None) -> dict[str, bytes]:
        css = raiz / "steamui" / "css"
        css.mkdir(parents=True, exist_ok=True)
        (raiz / "steamui" / "adwaita").mkdir(parents=True, exist_ok=True)
        tamanho = self.TAMANHO if tamanho is None else tamanho
        originais: dict[str, bytes] = {}
        for nome in CSS_NAMES:
            dado = (f"/* {nome} Steam original */\n" + "x" * tamanho + "\n").encode("utf-8")
            (css / nome).write_bytes(dado)
            originais[nome] = dado
        return originais


class InstalarTests(_SteamFixture):
    def test_instalar_marca_as_css(self):
        self.assertTrue(installer.instalar(self.root, "dracula", "#ff0000", "dark"))
        self.assertTrue(installer.esta_instalada(self.root))
        self.assertTrue(installer.totalmente_instalada(self.root))
        for nome in CSS_NAMES:
            with self.subTest(css=nome):
                caminho = self.root / "steamui" / "css" / nome
                self.assertEqual(installer.primeira_linha(caminho), PATCH_HEADER)

    def test_backup_guarda_conteudo_original(self):
        installer.instalar(self.root, "dracula", "#ff0000", "dark")
        for nome, original in self.originals.items():
            with self.subTest(css=nome):
                backup = installer.caminho_backup(self.root, nome)
                self.assertTrue(backup.is_file())
                self.assertEqual(backup.name, Path(nome).with_suffix(".original.css").name)
                self.assertEqual(backup.read_bytes(), original)

    def test_instalacao_e_idempotente(self):
        self.assertTrue(installer.instalar(self.root, "dracula", "#ff0000", "dark"))
        antes = {nome: _patch_bytes(self.root, nome) for nome in CSS_NAMES}

        self.assertFalse(installer.instalar(self.root, "dracula", "#ff0000", "dark"))

        depois = {nome: _patch_bytes(self.root, nome) for nome in CSS_NAMES}
        self.assertEqual(antes, depois)

    def test_restaurar_volta_conteudo_original(self):
        installer.instalar(self.root, "dracula", "#ff0000", "dark")
        self.assertTrue(installer.restaurar(self.root))
        for nome, original in self.originals.items():
            with self.subTest(css=nome):
                self.assertEqual(_patch_bytes(self.root, nome), original)
                self.assertFalse(installer.caminho_backup(self.root, nome).exists())
        self.assertFalse((self.root / "steamui" / "adwaita").exists())
        self.assertFalse(installer.esta_instalada(self.root))

    def test_restaurar_sem_skin_e_noop(self):
        # Sem skin instalada e sem diretório de skin: nada a restaurar.
        (self.root / "steamui" / "adwaita").rmdir()
        self.assertFalse(installer.restaurar(self.root))

    def test_instalar_caminho_invalido_levanta_skin_error(self):
        invalido = Path(self._tmp.name) / "vazio"
        invalido.mkdir()
        with self.assertRaises(installer.SkinError):
            installer.instalar(invalido, "dracula", "#ff0000", "dark")


class AtualizacaoTests(_SteamFixture):
    def test_update_da_steam_exige_reparo(self):
        installer.instalar(self.root, "dracula", "#ff0000", "dark")
        self.assertEqual(verificar_estado(self.root), Estado.SINCRONIZADA)

        # Steam reescreveu o CSS sem o nosso header.
        (self.root / "steamui" / "css" / "library.css").write_text(
            "/* Steam atualizado */\n" + "y" * self.TAMANHO, encoding="utf-8"
        )

        self.assertEqual(verificar_estado(self.root), Estado.ATUALIZACAO_NECESSARIA)
        self.assertTrue(precisa_reparo(self.root))

    def test_reparo_seguro_reinstala(self):
        installer.instalar(self.root, "dracula", "#ff0000", "dark")
        (self.root / "steamui" / "css" / "library.css").write_text(
            "/* Steam atualizado */\n" + "y" * self.TAMANHO, encoding="utf-8"
        )
        self.assertTrue(reparar_se_seguro(self.root, {"theme_slug": "dracula"}))
        self.assertTrue(installer.totalmente_instalada(self.root))


class ConflitoTests(_SteamFixture):
    def test_conflito_de_terceiros(self):
        caminho = self.root / "steamui" / "css" / "library.css"
        caminho.write_text("/* Millennium patched */\n.x{}\n", encoding="utf-8")

        self.assertEqual(verificar_estado(self.root), Estado.CONFLITO_TERCEIROS)

        antes = caminho.read_bytes()
        self.assertFalse(reparar_se_seguro(self.root, {"theme_slug": "dracula"}))
        self.assertEqual(caminho.read_bytes(), antes)

    def test_reparo_nao_sobrescreve_conflito(self):
        caminho = self.root / "steamui" / "css" / "gamerecording.css"
        conteudo = "/* CSS Loader userstyle */\nbody{}\n"
        caminho.write_text(conteudo, encoding="utf-8")
        self.assertEqual(verificar_estado(self.root), Estado.CONFLITO_TERCEIROS)
        reparar_se_seguro(self.root)
        self.assertEqual(caminho.read_text(encoding="utf-8"), conteudo)


@unittest.skipIf(os.geteuid() == 0, "permissões não se aplicam ao root")
class PermissaoTests(_SteamFixture):
    def test_dir_read_only_reporta_permissao(self):
        installer.instalar(self.root, "dracula", "#ff0000", "dark")
        css = self.root / "steamui" / "css"
        os.chmod(css, 0o500)
        try:
            self.assertEqual(verificar_estado(self.root), Estado.PERMISSAO)
        finally:
            os.chmod(css, 0o755)

    def test_falha_de_escrita_vira_skin_error_contido(self):
        css = self.root / "steamui" / "css"
        os.chmod(css, 0o500)
        try:
            with self.assertRaises(installer.SkinError):
                installer.instalar(self.root, "dracula", "#ff0000", "dark")
        finally:
            os.chmod(css, 0o755)
        # Nada ficou pela metade: a árvore da skin foi revertida.
        self.assertFalse(installer.esta_instalada(self.root))


class PatchGrandeTests(_SteamFixture):
    def test_patch_maior_que_original_levanta_erro(self):
        # Recria a árvore com CSS minúsculas: o patch não cabe.
        self.originals = self._criar_arvore(self.root, tamanho=8)
        with self.assertRaises(installer.PatchTooLargeError):
            installer.instalar(self.root, "dracula", "#ff0000", "dark")


class VendorTests(unittest.TestCase):
    def test_vendor_disponivel(self):
        self.assertTrue(vendor.vendor_available())
        self.assertEqual(vendor.vendor_version(), "4.4")
        self.assertEqual(len(vendor.list_colorthemes()), 23)


if __name__ == "__main__":
    unittest.main()
