"""Testes do adaptador de arte do Console (#184).

Cobrem a detecção de formato/dimensões sem decodificar pixels, a política
de seleção (capa/hero/logo), o confinamento de caminhos, o placeholder e a
tag de conteúdo, injetando um módulo ``shared`` falso com diretórios
temporários.
"""

import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

import builtins

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

import cartridges.console_art as art  # noqa: E402


def _png_bytes(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


def _gif_bytes(width: int, height: int) -> bytes:
    return (
        b"GIF89a"
        + width.to_bytes(2, "little")
        + height.to_bytes(2, "little")
        + b"\xf0\x00\x00\x00\x00\x00"
    )


def _jpeg_bytes(width: int, height: int) -> bytes:
    app0 = b"\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = (
        b"\xff\xc0"
        + (17).to_bytes(2, "big")
        + b"\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    )
    return b"\xff\xd8" + app0 + sof


def _webp_vp8x_bytes(width: int, height: int) -> bytes:
    chunk = b"\x00" + b"\x00\x00\x00" + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    body = b"WEBP" + b"VP8X" + len(chunk).to_bytes(4, "little") + chunk
    return b"RIFF" + (4 + len(body)).to_bytes(4, "little") + body


def _tiff_le_bytes(width: int, height: int) -> bytes:
    out = bytearray(b"II*\x00")
    out += (8).to_bytes(4, "little")
    out += (2).to_bytes(2, "little")
    for tag, value in ((256, width), (257, height)):
        out += tag.to_bytes(2, "little")
        out += (3).to_bytes(2, "little")  # SHORT
        out += (1).to_bytes(4, "little")
        out += value.to_bytes(2, "little") + b"\x00\x00"
    return bytes(out)


def _tiff_be_bytes(width: int, height: int) -> bytes:
    out = bytearray(b"MM\x00*")
    out += (8).to_bytes(4, "big")
    out += (2).to_bytes(2, "big")
    for tag, value in ((256, width), (257, height)):
        out += tag.to_bytes(2, "big")
        out += (3).to_bytes(2, "big")
        out += (1).to_bytes(4, "big")
        out += value.to_bytes(2, "big") + b"\x00\x00"
    return bytes(out)


def _svg_bytes() -> bytes:
    return b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'


class _FakeShared(SimpleNamespace):
    pass


def _install_fake_shared(testcase, tmp: Path, games=(), animated: bool = False) -> None:
    covers = tmp / "covers"
    logos = tmp / "logos"
    wallpapers = tmp / "wallpapers"
    cache = tmp / "cache"
    for d in (covers, logos, wallpapers, cache / "jolven" / "library-bg"):
        d.mkdir(parents=True, exist_ok=True)
    fake = _FakeShared(
        covers_dir=covers,
        logos_dir=logos,
        wallpapers_dir=wallpapers,
        cache_dir=cache,
        store=list(games),
        schema=SimpleNamespace(get_boolean=lambda key: animated and key == "sgdb-animated"),
    )
    import cartridges

    if getattr(testcase, "_fake_depth", 0) == 0:
        testcase._old_shared = getattr(cartridges, "shared", None)
    testcase._fake_depth = getattr(testcase, "_fake_depth", 0) + 1
    cartridges.shared = fake
    art._logo_sidecar_cache.clear()


def _uninstall_fake_shared(testcase) -> None:
    import cartridges

    testcase._fake_depth = getattr(testcase, "_fake_depth", 1) - 1
    if testcase._fake_depth > 0:
        art._logo_sidecar_cache.clear()
        return
    if getattr(testcase, "_old_shared", None) is None:
        try:
            del cartridges.shared
        except AttributeError:
            pass
    else:
        cartridges.shared = testcase._old_shared
    testcase._fake_depth = 0
    art._logo_sidecar_cache.clear()


class SniffTests(unittest.TestCase):
    def test_png(self):
        self.assertEqual(art.sniff_image_bytes(_png_bytes(640, 480)), ("png", 640, 480))

    def test_gif(self):
        self.assertEqual(art.sniff_image_bytes(_gif_bytes(320, 200)), ("gif", 320, 200))

    def test_jpeg(self):
        self.assertEqual(art.sniff_image_bytes(_jpeg_bytes(200, 256)), ("jpeg", 200, 256))

    def test_webp_vp8x(self):
        self.assertEqual(art.sniff_image_bytes(_webp_vp8x_bytes(1024, 768)), ("webp", 1024, 768))

    def test_tiff_le(self):
        self.assertEqual(art.sniff_image_bytes(_tiff_le_bytes(400, 600)), ("tiff", 400, 600))

    def test_tiff_be(self):
        self.assertEqual(art.sniff_image_bytes(_tiff_be_bytes(400, 600)), ("tiff", 400, 600))

    def test_svg(self):
        self.assertEqual(art.sniff_image_bytes(_svg_bytes()), ("svg", 0, 0))

    def test_garbage(self):
        self.assertIsNone(art.sniff_image_bytes(b"\x00" * 64))

    def test_truncated_png(self):
        self.assertIsNone(art.sniff_image_bytes(_png_bytes(10, 10)[:12]))


class ValidateImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jolven-art-test-"))

    def _write(self, name: str, data: bytes, root: str = "covers") -> Path:
        d = self.tmp / root
        d.mkdir(parents=True, exist_ok=True)
        p = d / name
        p.write_bytes(data)
        return p

    def test_valid_png(self):
        p = self._write("a.png", _png_bytes(100, 200))
        info = art.validate_image(p, (self.tmp / "covers",))
        self.assertEqual(info, ("png", 100, 200))

    def test_too_small_dimensions_rejected(self):
        p = self._write("small.png", _png_bytes(4, 4))
        self.assertIsNone(art.validate_image(p, (self.tmp / "covers",)))

    def test_huge_dimensions_rejected(self):
        p = self._write("big.png", _png_bytes(10000, 10000))
        self.assertIsNone(art.validate_image(p, (self.tmp / "covers",)))

    def test_oversized_file_rejected(self):
        d = self.tmp / "covers"
        d.mkdir(exist_ok=True)
        p = d / "huge.png"
        p.write_bytes(_png_bytes(50, 50))
        with open(p, "ab") as handle:
            handle.truncate(art.MAX_IMAGE_BYTES + 1)
        self.assertIsNone(art.validate_image(p, (self.tmp / "covers",)))

    def test_corrupted_rejected(self):
        p = self._write("corrupt.png", os.urandom(512))
        self.assertIsNone(art.validate_image(p, (self.tmp / "covers",)))

    def test_symlink_escape_rejected(self):
        outside = self.tmp / "outside" / "segredo.png"
        (self.tmp / "outside").mkdir()
        outside.write_bytes(_png_bytes(100, 100))
        link = self._write("link.png", b"")  # placeholder para o link
        link.unlink()
        os.symlink(outside, link)
        self.assertIsNone(art.validate_image(link, (self.tmp / "covers",)))

    def test_outside_root_rejected_even_if_valid(self):
        p = self.tmp / "fora.png"
        p.write_bytes(_png_bytes(100, 100))
        self.assertIsNone(art.validate_image(p, (self.tmp / "covers",)))


class ParseUriTests(unittest.TestCase):
    def test_cover(self):
        self.assertEqual(art.parse_art_uri("jolven-art://cover/uzdoom_1?v=abc123"), ("cover", "uzdoom_1"))

    def test_percent_decoded_id(self):
        self.assertEqual(
            art.parse_art_uri("jolven-art://hero/meu%20jogo?v=1"),
            ("hero", "meu jogo"),
        )

    def test_scheme_required(self):
        self.assertIsNone(art.parse_art_uri("file:///etc/passwd"))

    def test_unknown_kind(self):
        self.assertIsNone(art.parse_art_uri("jolven-art://secret/1"))

    def test_dotdot_rejected(self):
        self.assertIsNone(art.parse_art_uri("jolven-art://cover/.."))

    def test_slash_rejected(self):
        self.assertIsNone(art.parse_art_uri("jolven-art://cover/a/b"))

    def test_empty_id_rejected(self):
        self.assertIsNone(art.parse_art_uri("jolven-art://cover/"))

    def test_huge_id_rejected(self):
        self.assertIsNone(art.parse_art_uri(f"jolven-art://cover/{'x' * 300}"))

    def test_control_chars_rejected(self):
        self.assertIsNone(art.parse_art_uri("jolven-art://cover/a%09b"))


def _game(game_id="uzdoom_1", name="DOOM", removed=False):
    return SimpleNamespace(game_id=game_id, name=name, removed=removed)


class ServeArtTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jolven-art-test-"))
        self.game = _game()
        _install_fake_shared(self, self.tmp, games=[self.game])

    def tearDown(self):
        _uninstall_fake_shared(self)

    def _write(self, root: str, name: str, data: bytes) -> Path:
        d = self.tmp / root
        d.mkdir(parents=True, exist_ok=True)
        p = d / name
        p.write_bytes(data)
        return p

    def test_cover_tiff_uses_to_png_when_provided(self):
        self._write("covers", "uzdoom_1.tiff", _tiff_le_bytes(400, 600))
        seen = []

        def fake_to_png(path):
            seen.append(path.name)
            return b"PNGDATA"

        data, mime = art.serve_art("jolven-art://cover/uzdoom_1?v=1", to_png=fake_to_png)
        self.assertEqual((data, mime), (b"PNGDATA", "image/png"))
        self.assertEqual(seen, ["uzdoom_1.tiff"])

    def test_cover_tiff_without_converter_falls_back_to_placeholder(self):
        self._write("covers", "uzdoom_1.tiff", _tiff_le_bytes(400, 600))
        data, mime = art.serve_art("jolven-art://cover/uzdoom_1")
        self.assertEqual(mime, "image/svg+xml")
        self.assertIn(b"<svg", data)

    def test_cover_gif_animated_served_raw_when_enabled(self):
        import cartridges

        cartridges.shared.schema = SimpleNamespace(
            get_boolean=lambda key: key == "sgdb-animated"
        )
        self._write("covers", "uzdoom_1.gif", _gif_bytes(320, 200))
        self._write("covers", "uzdoom_1.tiff", _tiff_le_bytes(10, 10))
        data, mime = art.serve_art("jolven-art://cover/uzdoom_1")
        self.assertEqual(mime, "image/gif")
        self.assertTrue(data.startswith(b"GIF89a"))

    def test_cover_gif_static_frame_when_disabled(self):
        self._write("covers", "uzdoom_1.gif", _gif_bytes(320, 200))
        data, mime = art.serve_art(
            "jolven-art://cover/uzdoom_1", to_png=lambda path: b"STATIC"
        )
        self.assertEqual((data, mime), (b"STATIC", "image/png"))

    def test_cover_missing_returns_placeholder(self):
        data, mime = art.serve_art("jolven-art://cover/desconhecido")
        self.assertEqual(mime, "image/svg+xml")

    def test_hero_prefers_manual_fundo(self):
        self._write("wallpapers", "uzdoom_1-fundo.jpg", _jpeg_bytes(1920, 1080))
        cache = self.tmp / "cache" / "jolven" / "library-bg" / "uzdoom_1"
        cache.mkdir(parents=True)
        (cache / "maior.png").write_bytes(_png_bytes(4000, 4000))
        data, mime = art.serve_art("jolven-art://hero/uzdoom_1")
        self.assertEqual(mime, "image/jpeg")

    def test_hero_cache_prefers_landscape(self):
        cache = self.tmp / "cache" / "jolven" / "library-bg" / "uzdoom_1"
        cache.mkdir(parents=True)
        (cache / "portrait.png").write_bytes(_png_bytes(800, 3000))
        (cache / "landscape.png").write_bytes(_png_bytes(1920, 1080))
        data, mime = art.serve_art("jolven-art://hero/uzdoom_1")
        self.assertEqual(mime, "image/png")
        self.assertEqual(art.sniff_image_bytes(data), ("png", 1920, 1080))

    def test_hero_cache_skips_symlink_escape(self):
        outside = self._write("outside", "x.png", _png_bytes(9999, 9999))
        cache = self.tmp / "cache" / "jolven" / "library-bg" / "uzdoom_1"
        cache.mkdir(parents=True)
        os.symlink(outside, cache / "escape.png")
        data, mime = art.serve_art("jolven-art://hero/uzdoom_1")
        self.assertEqual(mime, "image/svg+xml")  # sem candidato válido: capa inexistente

    def test_hero_falls_back_to_cover(self):
        self._write("covers", "uzdoom_1.tiff", _tiff_le_bytes(400, 600))
        data, mime = art.serve_art(
            "jolven-art://hero/uzdoom_1", to_png=lambda path: b"HEROPNG"
        )
        self.assertEqual((data, mime), (b"HEROPNG", "image/png"))

    def test_logo_locked_sidecar_served(self):
        self._write("logos", "uzdoom_1-logo.png", _png_bytes(300, 80))
        (self.tmp / "logos" / "uzdoom_1.json").write_text(
            json.dumps({"name": "Outro Nome", "file": "uzdoom_1-logo.png", "locked": True}),
            encoding="utf-8",
        )
        data, mime = art.serve_art("jolven-art://logo/uzdoom_1")
        self.assertEqual(mime, "image/png")

    def test_logo_name_mismatch_falls_back(self):
        self._write("logos", "uzdoom_1-logo.png", _png_bytes(300, 80))
        (self.tmp / "logos" / "uzdoom_1.json").write_text(
            json.dumps({"name": "Outro Nome", "file": "uzdoom_1-logo.png"}),
            encoding="utf-8",
        )
        data, mime = art.serve_art("jolven-art://logo/uzdoom_1")
        self.assertEqual(mime, "image/svg+xml")

    def test_logo_removed_game_bypasses_name_check(self):
        self.game.removed = True
        self._write("logos", "uzdoom_1-logo.png", _png_bytes(300, 80))
        (self.tmp / "logos" / "uzdoom_1.json").write_text(
            json.dumps({"name": "Outro Nome", "file": "uzdoom_1-logo.png"}),
            encoding="utf-8",
        )
        data, mime = art.serve_art("jolven-art://logo/uzdoom_1")
        self.assertEqual(mime, "image/png")

    def test_logo_sidecar_with_path_traversal_rejected(self):
        (self.tmp / "logos" / "uzdoom_1.json").write_text(
            json.dumps({"name": "DOOM", "file": "../covers/uzdoom_1.tiff", "locked": True}),
            encoding="utf-8",
        )
        data, mime = art.serve_art("jolven-art://logo/uzdoom_1")
        self.assertEqual(mime, "image/svg+xml")

    def test_logo_tombstone_returns_placeholder(self):
        (self.tmp / "logos" / "uzdoom_1.json").write_text(
            json.dumps({"name": "DOOM", "file": None, "locked": True}),
            encoding="utf-8",
        )
        data, mime = art.serve_art("jolven-art://logo/uzdoom_1")
        self.assertEqual(mime, "image/svg+xml")

    def test_placeholder_kind(self):
        data, mime = art.serve_art("jolven-art://placeholder/hero")
        self.assertEqual(mime, "image/svg+xml")
        self.assertIn(b"1920", data)


class ArtTagTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jolven-art-test-"))
        self.game = _game()
        _install_fake_shared(self, self.tmp, games=[self.game])

    def tearDown(self):
        _uninstall_fake_shared(self)

    def test_tag_stable_and_changes_with_cover(self):
        covers = self.tmp / "covers"
        p = covers / "uzdoom_1.tiff"
        p.write_bytes(_tiff_le_bytes(400, 600))
        tag1 = art.art_tag(self.game)
        self.assertEqual(tag1, art.art_tag(self.game))
        p.write_bytes(_tiff_le_bytes(800, 1200))
        os.utime(p, (os.stat(p).st_atime + 5, os.stat(p).st_mtime + 5))
        self.assertNotEqual(tag1, art.art_tag(self.game))
