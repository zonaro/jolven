"""Testes do detector de instalações Steam (sem tocar na Steam real)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cartridges.integrations.steam_skin.detector import (
    Installation,
    detect_all,
    detect_custom,
    expand_steam_path,
    find_installation,
    is_steam_path_valid,
    _probe,
)

CSS_NAMES = ("library.css", "gamerecording.css", "gamenotes.css")


def _make_valid_tree(raiz: Path) -> Path:
    """Cria um ``<steam>`` mínimo com ``steamui/css`` e os CSS requeridos."""
    css = raiz / "steamui" / "css"
    css.mkdir(parents=True, exist_ok=True)
    (raiz / "steamui" / "adwaita").mkdir(parents=True, exist_ok=True)
    for nome in CSS_NAMES:
        (css / nome).write_text(f"/* {nome} */\n:root {{}}\n", encoding="utf-8")
    return raiz


class DetectorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_detect_custom_valido(self):
        alvo = _make_valid_tree(self.base / "steam")
        instalacoes = detect_custom(alvo)
        self.assertEqual(len(instalacoes), 1)
        inst = instalacoes[0]
        self.assertIsInstance(inst, Installation)
        self.assertTrue(inst.accessible)
        self.assertEqual(inst.kind, "custom")
        self.assertIsNone(inst.reason)
        self.assertEqual(inst.path, alvo)

    def test_detect_custom_invalido_diretorio_existente(self):
        alvo = self.base / "vazio"
        alvo.mkdir()
        inst = detect_custom(alvo)[0]
        self.assertFalse(inst.accessible)
        self.assertEqual(inst.reason, "not a valid Steam interface directory")

    def test_detect_custom_inexistente(self):
        inst = detect_custom(self.base / "nao-existe")[0]
        self.assertFalse(inst.accessible)
        self.assertEqual(inst.reason, "directory not found")

    def test_detect_custom_sem_css_obrigatorio(self):
        alvo = self.base / "incompleto"
        css = alvo / "steamui" / "css"
        css.mkdir(parents=True)
        (css / "library.css").write_text("/* só um */\n", encoding="utf-8")
        inst = detect_custom(alvo)[0]
        self.assertFalse(inst.accessible)
        self.assertEqual(inst.reason, "not a valid Steam interface directory")

    def test_is_steam_path_valid(self):
        alvo = _make_valid_tree(self.base / "steam")
        self.assertTrue(is_steam_path_valid(alvo))
        self.assertFalse(is_steam_path_valid(self.base / "nenhum"))
        self.assertFalse(is_steam_path_valid(self.base))

    def test_find_installation(self):
        alvo = _make_valid_tree(self.base / "steam")
        self.assertTrue(find_installation(alvo).accessible)
        self.assertFalse(find_installation(self.base / "x").accessible)

    def test_expand_steam_path(self):
        self.assertEqual(expand_steam_path("~"), Path.home())
        self.assertEqual(expand_steam_path("~/steam"), Path.home() / "steam")
        absoluto = self.base / "algo"
        self.assertEqual(expand_steam_path(str(absoluto)), absoluto)

    def test_multiplas_instalacoes_sem_duplicar(self):
        a = _make_valid_tree(self.base / "a")
        b = _make_valid_tree(self.base / "b")
        # ``a`` aparece em native e flatpak: deve ser deduplicado.
        with (
            mock.patch(
                "cartridges.integrations.steam_skin.detector.detect_native",
                return_value=[Installation(a, "native", True, None)],
            ),
            mock.patch(
                "cartridges.integrations.steam_skin.detector.detect_flatpak",
                return_value=[Installation(a, "flatpak", True, None)],
            ),
            mock.patch(
                "cartridges.integrations.steam_skin.detector.detect_snap",
                return_value=[Installation(b, "snap", True, None)],
            ),
        ):
            encontradas = detect_all(include_custom=False)

        self.assertEqual([inst.path for inst in encontradas], [a, b])
        self.assertEqual([inst.kind for inst in encontradas], ["native", "snap"])

    def test_probe_reporta_diretorio_inexistente(self):
        inst = _probe(self.base / "nao-existe", "custom")
        self.assertFalse(inst.accessible)
        self.assertEqual(inst.reason, "directory not found")


if __name__ == "__main__":
    unittest.main()
