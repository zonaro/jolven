# test_minigalaxy_desktop.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Detecção de atalhos ``.desktop`` criados pelo cliente Minigalaxy (issue #165)."""

import unittest
from pathlib import Path

from cartridges.importer.minigalaxy import detect_minigalaxy_desktop


def _desktop(tmp: Path, name: str, content: str) -> Path:
    path = tmp / name
    path.write_text(content, encoding="utf-8")
    return path


class DetectMinigalaxyDesktopTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self.tmp = Path(tempfile.mkdtemp(prefix="minigalaxy-desktop-"))

    def test_desktop_com_goggame_exec_reconhecido(self):
        alvo = self.tmp / "Meu Jogo"
        alvo.mkdir()
        desktop = _desktop(
            self.tmp,
            "jogo.desktop",
            "[Desktop Entry]\n"
            "Name=Meu Jogo GOG\n"
            "Exec=minigalaxy --launch goggame-12345\n"
            "Icon=minigalaxy-jogo\n"
            f"Path={alvo}\n"
            "Type=Application\n",
        )
        resultado = detect_minigalaxy_desktop(desktop)
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["gog_id"], "12345")
        self.assertEqual(resultado["name"], "Meu Jogo GOG")
        self.assertEqual(resultado["icon"], "minigalaxy-jogo")
        self.assertEqual(resultado["directory"], alvo)

    def test_desktop_sem_goggame_mas_com_minigalaxy_no_exec(self):
        desktop = _desktop(
            self.tmp,
            "jogo.desktop",
            "[Desktop Entry]\n"
            "Name=Outro Jogo\n"
            "Exec=minigalaxy start /home/usuario/GOG Games/Outro Jogo\n"
            "Type=Application\n",
        )
        resultado = detect_minigalaxy_desktop(desktop)
        self.assertIsNotNone(resultado)
        self.assertIsNone(resultado["gog_id"])
        self.assertEqual(resultado["name"], "Outro Jogo")

    def test_atalho_pessoal_sem_assinatura_nao_e_reconhecido(self):
        desktop = _desktop(
            self.tmp,
            "pessoal.desktop",
            "[Desktop Entry]\n"
            "Name=Meu Atalho Pessoal\n"
            "Exec=/usr/bin/firefox https://example.com\n"
            "Type=Application\n",
        )
        self.assertIsNone(detect_minigalaxy_desktop(desktop))

    def test_arquivo_sem_grupo_desktop_entry_nao_e_reconhecido(self):
        desktop = _desktop(
            self.tmp,
            "nao-desktop.desktop",
            "[Geral]\n"
            "Nome=Qualquer coisa\n"
            "Exec=algo\n",
        )
        self.assertIsNone(detect_minigalaxy_desktop(desktop))

    def test_caminho_inexistente_nao_vira_diretorio(self):
        desktop = _desktop(
            self.tmp,
            "jogo.desktop",
            "[Desktop Entry]\n"
            "Name=Jogo\n"
            "Exec=minigalaxy --launch goggame-99\n"
            "Path=/tmp/nao-existe-xyz\n"
            "Type=Application\n",
        )
        resultado = detect_minigalaxy_desktop(desktop)
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["gog_id"], "99")
        self.assertIsNone(resultado["directory"])

    def test_id_zero_vai_para_none(self):
        desktop = _desktop(
            self.tmp,
            "jogo.desktop",
            "[Desktop Entry]\n"
            "Name=Jogo\n"
            "Exec=minigalaxy --launch goggame-0\n"
            "Type=Application\n",
        )
        resultado = detect_minigalaxy_desktop(desktop)
        self.assertIsNotNone(resultado)
        self.assertIsNone(resultado["gog_id"])


if __name__ == "__main__":
    unittest.main()
