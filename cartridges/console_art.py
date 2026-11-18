"""Adaptador de arte Jolven para a WebView do Console (#184).

Serve as artes que o Jolven já guarda em cache (capas, fundos, logos) para a
SPA do Console por um esquema interno seguro, ``jolven-art://``.

Política de seleção para o hero (sem rede, sempre cache local):
    1. fundo manual do jogo (``wallpapers/<game_id>-fundo.<ext>``);
    2. melhor imagem já cacheada em ``cache/jolven/library-bg/<game_id>/``
       (paisagem vence; entre elas, a de maior área);
    3. capa do jogo (paisagem não existe no Jolven hoje);
    4. placeholder em gradiente (SVG gerado em memória).

Restrições do esquema:
    - URLs carregam apenas ``game_id`` e uma tag de conteúdo opaca;
    - nenhum caminho absoluto chega ao WebView ou ao JS;
    - ``game_id`` é validado antes de qualquer I/O e o caminho resolvido é
      confinado ao diretório esperado (realpath);
    - tamanho, dimensões, formato e tipo de conteúdo são verificados (header
      parse puro, sem decodificar pixels — prevenção de decompression bomb);
    - arquivos ausentes/corrompidos caem no placeholder.

Este módulo não importa GTK e é seguro para uso headless nos testes. A
conversão de TIFF/GIF-estático para PNG é delegada ao chamador (a SPA roda em
uma WebView que não tem decodificador TIFF); em ambientes sem esse conversor,
TIFF responde com o placeholder.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlsplit

logger = logging.getLogger(__name__)

ART_SCHEME = "jolven-art"

MAX_IMAGE_BYTES = 24 * 1024 * 1024
MAX_SVG_BYTES = 2 * 1024 * 1024
MAX_DIMENSION = 8192
MIN_DIMENSION = 8
MAX_GAME_ID = 200

_SNIFF_BYTES = 1024 * 1024  # janelas de leitura para o header
_COVER_EXTS = (".gif", ".tiff")
_HERO_MANUAL_EXTS = (".jpg", ".jpeg", ".png", ".webp")
_HERO_CACHE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

_MIME = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "tiff": "image/tiff",
    "svg": "image/svg+xml",
}

_JPEG_SOF = {
    0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
}
_JPEG_STANDALONE = {0x01, 0xD8, 0xD9} | set(range(0xD0, 0xD8))

__all__ = [
    "ART_SCHEME",
    "MAX_IMAGE_BYTES",
    "MAX_DIMENSION",
    "MIN_DIMENSION",
    "art_tag",
    "parse_art_uri",
    "serve_art",
    "sniff_image_bytes",
    "validate_image",
    "placeholder_bytes",
]


# ---------------------------------------------------------------- shared ---


def _shared() -> Optional[Any]:
    try:
        from cartridges import shared

        return shared
    except Exception:
        return None


def _sgdb_animated(sh: Any) -> bool:
    try:
        schema = getattr(sh, "schema", None)
        if schema is None:
            return False
        return bool(schema.get_boolean("sgdb-animated"))
    except Exception:
        return False


def _stat_sig(path: Path) -> Optional[tuple[int, int]]:
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


# ------------------------------------------------------------- sniffing ---


def sniff_image_bytes(head: bytes) -> Optional[tuple[str, int, int]]:
    """Detecta formato e dimensões a partir do header, sem decodificar.

    Devolve ``(formato, largura, altura)``; para SVG, ``(0, 0)`` porque não
    há grade fixa. Devolve ``None`` quando não reconhece o arquivo.
    """

    if len(head) >= 24 and head[:8] == b"\x89PNG\r\n\x1a\n":
        w = int.from_bytes(head[16:20], "big")
        h = int.from_bytes(head[20:24], "big")
        return ("png", w, h)

    if len(head) >= 10 and head[:6] in (b"GIF87a", b"GIF89a"):
        w = int.from_bytes(head[6:8], "little")
        h = int.from_bytes(head[8:10], "little")
        return ("gif", w, h)

    if len(head) >= 4 and head[0] == 0xFF and head[1] == 0xD8:
        dim = _jpeg_dimensions(head)
        return ("jpeg", dim[0], dim[1]) if dim else None

    if len(head) >= 30 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        dim = _webp_dimensions(head)
        return ("webp", dim[0], dim[1]) if dim else None

    if len(head) >= 8 and head[:4] in (b"II*\x00", b"MM\x00*"):
        dim = _tiff_dimensions(head)
        return ("tiff", dim[0], dim[1]) if dim else None

    if _looks_like_svg(head):
        return ("svg", 0, 0)

    return None


def _jpeg_dimensions(head: bytes) -> Optional[tuple[int, int]]:
    pos = 2
    limit = len(head)
    while pos + 4 <= limit:
        if head[pos] != 0xFF:
            return None
        while pos < limit and head[pos] == 0xFF:
            pos += 1
        if pos >= limit:
            return None
        marker = head[pos]
        if marker in _JPEG_STANDALONE:
            pos += 1
            continue
        if pos + 2 > limit:
            return None
        seg_len = int.from_bytes(head[pos + 1 : pos + 3], "big")
        if seg_len < 2:
            return None
        if marker in _JPEG_SOF:
            if pos + 7 > limit:
                return None
            h = int.from_bytes(head[pos + 4 : pos + 6], "big")
            w = int.from_bytes(head[pos + 6 : pos + 8], "big")
            return (w, h)
        pos += 1 + seg_len
    return None


def _webp_dimensions(head: bytes) -> Optional[tuple[int, int]]:
    fourcc = head[12:16]
    data = 20
    if fourcc == b"VP8X" and len(head) >= data + 10:
        w = 1 + int.from_bytes(head[data + 4 : data + 7], "little")
        h = 1 + int.from_bytes(head[data + 7 : data + 10], "little")
        return (w, h)
    if fourcc == b"VP8 " and len(head) >= data + 10:
        if head[data + 3 : data + 6] != b"\x9d\x01\x2a":
            return None
        w = int.from_bytes(head[data + 6 : data + 8], "little") & 0x3FFF
        h = int.from_bytes(head[data + 8 : data + 10], "little") & 0x3FFF
        return (w, h)
    if fourcc == b"VP8L" and len(head) >= data + 6:
        if head[data] != 0x2F:
            return None
        b = head[data + 1 : data + 6]
        w1 = (b[0] | (b[1] << 8) | ((b[2] & 0x3F) << 16)) & 0x3FFF
        h1 = ((b[2] >> 6) | (b[3] << 2) | (b[4] << 10)) & 0x3FFF
        return (w1 + 1, h1 + 1)
    return None


def _tiff_dimensions(head: bytes) -> Optional[tuple[int, int]]:
    little = head[:4] == b"II*\x00"
    byte_order = "little" if little else "big"
    ifd_off = int.from_bytes(head[4:8], byte_order)
    if ifd_off < 8 or ifd_off + 2 > len(head):
        return None
    count = int.from_bytes(head[ifd_off : ifd_off + 2], byte_order)
    if count > 512:
        return None
    base = ifd_off + 2
    tags: dict[int, tuple[int, int]] = {}
    for i in range(count):
        entry = base + i * 12
        if entry + 12 > len(head):
            return None
        tag = int.from_bytes(head[entry : entry + 2], byte_order)
        type_ = int.from_bytes(head[entry + 2 : entry + 4], byte_order)
        n = int.from_bytes(head[entry + 4 : entry + 8], byte_order)
        value = head[entry + 8 : entry + 12]
        if tag in (256, 257) and n >= 1:
            if type_ == 3:  # SHORT
                tags[tag] = (int.from_bytes(value[:2], byte_order), 0)
            elif type_ == 4:  # LONG
                tags[tag] = (int.from_bytes(value, byte_order), 0)
    if 256 in tags and 257 in tags:
        w, h = tags[256][0], tags[257][0]
        return (w, h)
    return None


def _looks_like_svg(head: bytes) -> bool:
    sample = head[:4096].lower()
    return b"<svg" in sample and (b"<?xml" in sample or b"<!doctype" in sample or sample.lstrip().startswith(b"<svg"))


# ----------------------------------------------------------- validation ---


def _real(path: Path) -> str:
    return os.path.realpath(str(path))


def _contained(real: str, roots: tuple[Path, ...]) -> bool:
    for root in roots:
        root_real = _real(root)
        if real == root_real or real.startswith(root_real + os.sep):
            return True
    return False


def validate_image(
    path: Path, roots: tuple[Path, ...]
) -> Optional[tuple[str, int, int]]:
    """Valida tamanho, formato e dimensões de ``path``.

    Não decodifica pixels: a proteção contra decompression bomb é o limite
    de dimensões no header. Segue symlinks, mas exige que o caminho real
    esteja confinado a uma das ``roots``.
    """

    try:
        real = _real(path)
        st = os.stat(real)
    except OSError:
        return None
    if not os.path.isfile(real):
        return None
    if not _contained(real, tuple(Path(r) for r in roots)):
        return None
    size = st.st_size
    suffix = Path(real).suffix.lower()
    if suffix == ".svg":
        cap = MAX_SVG_BYTES
    else:
        cap = MAX_IMAGE_BYTES
    if size <= 0 or size > cap:
        return None
    try:
        with open(real, "rb") as handle:
            head = handle.read(_SNIFF_BYTES)
    except OSError:
        return None
    info = sniff_image_bytes(head)
    if info is None:
        return None
    fmt, w, h = info
    if fmt == "svg":
        return info
    if not (MIN_DIMENSION <= w <= MAX_DIMENSION and MIN_DIMENSION <= h <= MAX_DIMENSION):
        return None
    return info


# ------------------------------------------------------------ candidates ---


def _cover_candidate(sh: Any, game_id: str) -> tuple[Optional[Path], tuple[Path, ...], Optional[str]]:
    covers = Path(getattr(sh, "covers_dir", ""))
    if _sgdb_animated(sh):
        ordered = (".gif", ".tiff")
    else:
        ordered = (".tiff", ".gif")
    for ext in ordered:
        candidate = covers / f"{game_id}{ext}"
        if candidate.is_file():
            return candidate, (covers,), ext.lstrip(".")
    return None, (), None


def _manual_fundo(sh: Any, game_id: str) -> Optional[Path]:
    wallpapers = Path(getattr(sh, "wallpapers_dir", ""))
    for ext in _HERO_MANUAL_EXTS:
        candidate = wallpapers / f"{game_id}-fundo{ext}"
        if candidate.is_file():
            return candidate
    return None


def _cache_fundo(sh: Any, game_id: str) -> Optional[Path]:
    cache_root = Path(getattr(sh, "cache_dir", "")) / "jolven" / "library-bg"
    cdir = cache_root / game_id
    best: Optional[tuple[tuple[int, int], Path]] = None
    try:
        entries = list(os.scandir(cdir))
    except OSError:
        return None
    for entry in entries:
        suffix = Path(entry.name).suffix.lower()
        if suffix not in _HERO_CACHE_EXTS:
            continue
        try:
            if not entry.is_file(follow_symlinks=True):
                continue
        except OSError:
            continue
        candidate = Path(entry.path)
        info = validate_image(candidate, (cache_root,))
        if info is None:
            continue
        _, w, h = info
        score = (1 if w >= h else 0, w * h)
        if best is None or score > best[0]:
            best = (score, candidate)
    return best[1] if best else None


def _hero_candidate(sh: Any, game_id: str) -> tuple[Optional[Path], tuple[Path, ...]]:
    manual = _manual_fundo(sh, game_id)
    if manual is not None:
        return manual, (Path(getattr(sh, "wallpapers_dir", "")),)
    cached = _cache_fundo(sh, game_id)
    if cached is not None:
        return cached, (Path(getattr(sh, "cache_dir", "")) / "jolven" / "library-bg",)
    cover, roots, _ = _cover_candidate(sh, game_id)
    if cover is not None:
        return cover, roots
    return None, ()


_logo_sidecar_cache: dict[str, tuple[int, Any]] = {}


def _read_logo_sidecar(logos: Path, game_id: str) -> Optional[dict]:
    path = logos / f"{game_id}.json"
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return None
    key = str(path)
    hit = _logo_sidecar_cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = None
    except Exception:
        data = None
    _logo_sidecar_cache[key] = (mtime, data)
    return data


def _cached_logo_file(logos: Path, sidecar: dict) -> Optional[Path]:
    filename = sidecar.get("file")
    if not filename or not isinstance(filename, str):
        return None
    if "/" in filename or "\\" in filename or filename in (".", ".."):
        return None
    candidate = logos / filename
    return candidate if candidate.is_file() else None


def _logo_candidate(sh: Any, game: Any) -> tuple[Optional[Path], tuple[Path, ...]]:
    logos = Path(getattr(sh, "logos_dir", ""))
    game_id = str(getattr(game, "game_id", "") or "")
    sidecar = _read_logo_sidecar(logos, game_id)
    if not sidecar:
        return None, ()
    removed = bool(getattr(game, "removed", False))
    locked = bool(sidecar.get("locked", False))
    if not (locked or removed):
        if sidecar.get("name") != str(getattr(game, "name", "")):
            return None, ()
    cached = _cached_logo_file(logos, sidecar)
    if cached is None:
        return None, ()
    return cached, (logos,)


# ------------------------------------------------------------------ tag ---


def art_tag(game: Any) -> str:
    """Tag opaca de conteúdo para invalidar o cache da WebView.

    Mistura mtime/tamanho da capa, do fundo manual, de um fingerprint do
    cache de fundos e do logo. Qualquer mudança nesses arquivos muda a tag,
    então a SPA pode embutir ``?v=<tag>`` na URL sem vazar caminhos.
    """

    sh = _shared()
    if sh is None:
        return "0"
    game_id = str(getattr(game, "game_id", "") or "")
    if not game_id:
        return "0"

    parts: list[Any] = []
    covers = Path(getattr(sh, "covers_dir", ""))
    for ext in _COVER_EXTS:
        parts.append(_stat_sig(covers / f"{game_id}{ext}"))

    wallpapers = Path(getattr(sh, "wallpapers_dir", ""))
    for ext in _HERO_MANUAL_EXTS:
        parts.append(_stat_sig(wallpapers / f"{game_id}-fundo{ext}"))

    cdir = Path(getattr(sh, "cache_dir", "")) / "jolven" / "library-bg" / game_id
    fingerprint: list[tuple[str, int, int]] = []
    try:
        for entry in os.scandir(cdir):
            try:
                st = entry.stat()
            except OSError:
                continue
            fingerprint.append((entry.name, st.st_size, st.st_mtime_ns))
    except OSError:
        fingerprint = []
    parts.append(tuple(sorted(fingerprint)) if fingerprint else None)

    logos = Path(getattr(sh, "logos_dir", ""))
    parts.append(_stat_sig(logos / f"{game_id}.json"))
    sidecar = _read_logo_sidecar(logos, game_id) if (logos / f"{game_id}.json").is_file() else None
    filename = sidecar.get("file") if isinstance(sidecar, dict) else None
    if isinstance(filename, str) and filename and "/" not in filename and "\\" not in filename:
        parts.append(_stat_sig(logos / filename))
    else:
        parts.append(None)

    blob = repr(tuple(parts)).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:12]


# ------------------------------------------------------------ placeholder ---

_PLACEHOLDER_COVER = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 600">'
    '<rect width="400" height="600" rx="18" fill="#1a1a22"/>'
    '<rect x="1.5" y="1.5" width="397" height="597" rx="17" fill="none" stroke="#2a2a38" stroke-width="3"/>'
    '<g fill="#3a3a4e">'
    '<path d="M200 236c-42 0-74 34-74 78 0 34 22 54 40 54 14 0 18-8 34-8s20 8 34 8c18 0 40-20 40-54 0-44-32-78-74-78z"/>'
    '<circle cx="162" cy="300" r="9" fill="#1a1a22"/><circle cx="238" cy="300" r="9" fill="#1a1a22"/>'
    '<path d="M150 292h24M158 284v16" stroke="#1a1a22" stroke-width="5" stroke-linecap="round"/>'
    '</g></svg>'
)

_PLACEHOLDER_HERO = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080">'
    '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0" stop-color="#1b1b28"/><stop offset="1" stop-color="#101018"/>'
    '</linearGradient></defs>'
    '<rect width="1920" height="1080" fill="url(#g)"/>'
    '<circle cx="1450" cy="300" r="420" fill="#23233a" fill-opacity="0.55"/>'
    '<circle cx="380" cy="880" r="360" fill="#1f1f30" fill-opacity="0.6"/>'
    '</svg>'
)

_PLACEHOLDER_LOGO = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect width="1" height="1" fill="none"/></svg>'
)


def placeholder_bytes(variant: str) -> bytes:
    if variant == "hero":
        return _PLACEHOLDER_HERO.encode("utf-8")
    if variant == "logo":
        return _PLACEHOLDER_LOGO.encode("utf-8")
    return _PLACEHOLDER_COVER.encode("utf-8")


_PLACEHOLDER_KIND = {"cover": "cover", "hero": "hero", "logo": "logo"}


def parse_art_uri(uri: str) -> Optional[tuple[str, str]]:
    """Extrai ``(kind, ident)`` de ``jolven-art://<kind>/<ident>?v=...``.

    Valida o esquema, o tipo, o ``game_id`` e remove a query (tag opaca,
    ignorada pelo backend).
    """

    if not uri or len(uri) > 1024:
        return None
    try:
        parts = urlsplit(uri)
    except ValueError:
        return None
    if parts.scheme.lower() != ART_SCHEME:
        return None
    kind = parts.netloc.lower()
    if kind not in ("cover", "hero", "logo", "placeholder"):
        return None
    try:
        ident = unquote(parts.path.lstrip("/"), errors="strict")
    except Exception:
        return None
    if not ident or len(ident) > MAX_GAME_ID:
        return None
    if "/" in ident or "\\" in ident or ident in (".", ".."):
        return None
    if any(ord(ch) < 32 for ch in ident):
        return None
    return kind, ident


# ----------------------------------------------------------------- serve ---


def _find_game(sh: Any, game_id: str) -> Optional[Any]:
    store = getattr(sh, "store", None)
    if store is None:
        return None
    try:
        from cartridges import console_adapter

        return console_adapter.find_by_id(store, game_id)
    except Exception:
        return None


def _read_limited(path: Path, cap: int) -> Optional[bytes]:
    try:
        with open(path, "rb") as handle:
            data = handle.read(cap + 1)
    except OSError:
        return None
    if len(data) > cap:
        return None
    return data


def serve_art(uri: str, *, to_png: Any = None) -> tuple[bytes, str]:
    """Resolve ``uri`` para ``(bytes, content_type)``.

    Nunca levanta exceção: qualquer falha resulta no placeholder do tipo
    pedido. ``to_png`` (chamador com GTK/GdkPixbuf) converte TIFF — formato
    que a WebView não decodifica — e o primeiro frame de GIFs quando a
    animação está desabilitada. Sem ele, TIFF responde com placeholder.
    """

    parsed = parse_art_uri(uri)
    if parsed is None:
        return placeholder_bytes("cover"), "image/svg+xml"
    kind, ident = parsed
    if kind == "placeholder":
        variant = ident if ident in _PLACEHOLDER_KIND else "cover"
        return placeholder_bytes(variant), "image/svg+xml"

    try:
        sh = _shared()
        if sh is None:
            return placeholder_bytes(kind), "image/svg+xml"

        game = _find_game(sh, ident)
        if game is None:
            return placeholder_bytes(kind), "image/svg+xml"

        animated = _sgdb_animated(sh)
        roots: tuple[Path, ...] = ()
        candidate: Optional[Path] = None
        needs_png = False

        if kind == "cover":
            candidate, roots, ext = _cover_candidate(sh, ident)
            needs_png = bool(
                candidate
                and ((ext == "tiff") or (ext == "gif" and not animated))
            )
        elif kind == "hero":
            candidate, roots = _hero_candidate(sh, ident)
            if candidate is not None and candidate.suffix.lower() in (".tiff",):
                needs_png = True
        elif kind == "logo":
            candidate, roots = _logo_candidate(sh, game)
            if candidate is not None and candidate.suffix.lower() in (".tiff",):
                needs_png = True

        if candidate is None:
            return placeholder_bytes(kind), "image/svg+xml"

        info = validate_image(candidate, tuple(Path(r) for r in roots))
        if info is None:
            return placeholder_bytes(kind), "image/svg+xml"
        fmt, _, _ = info
        suffix = candidate.suffix.lower()
        if suffix == ".tiff" or (suffix == ".gif" and needs_png):
            if to_png is None:
                return placeholder_bytes(kind), "image/svg+xml"
            png = to_png(candidate)
            if not png:
                return placeholder_bytes(kind), "image/svg+xml"
            return png, "image/png"

        data = _read_limited(candidate, MAX_SVG_BYTES if fmt == "svg" else MAX_IMAGE_BYTES)
        if data is None:
            return placeholder_bytes(kind), "image/svg+xml"
        return data, _MIME.get(fmt, "application/octet-stream")
    except Exception:
        logger.exception("Falha ao resolver a arte %s", uri[:120])
        return placeholder_bytes(kind), "image/svg+xml"
