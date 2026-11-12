# hashing.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hashes e leituras parciais de arquivos de jogo (issue #110).

Toda leitura aqui é limitada e falha em silêncio para o chamador: um arquivo
gigante, um disco removido no meio da leitura ou uma permissão negada viram
"sem hash", nunca um erro que interrompa a importação.

Os hashes são calculados fora da thread GTK (quem chama é um ``Manager``
assíncrono). O teto de leitura completa existe para não varrer ISOs de 40 GB
ao abrir a biblioteca; acima dele o arquivo recebe uma impressão digital
parcial, útil para detectar arquivo movido e explicitamente insuficiente para
afirmar qual dump é.
"""

from __future__ import annotations

import logging
import os
import zlib
from hashlib import md5, sha1
from pathlib import Path
from typing import Any, Optional

_CHUNK = 1024 * 1024

#: Acima disto o arquivo não é lido por inteiro. 512 MiB cobre cartuchos e
#: discos pequenos e deixa ISOs grandes para a impressão digital parcial.
DEFAULT_FULL_HASH_LIMIT = 512 * 1024 * 1024

#: Quanto da cabeça e da cauda entram na impressão digital de arquivos grandes.
DEFAULT_PARTIAL_BYTES = 2 * 1024 * 1024

#: Quanto do começo do arquivo é lido para reconhecer cabeçalho/plataforma.
HEADER_BYTES = 0x8000 + 0x200


def _hash_stream(handle, hasher, skip: int = 0, limit: Optional[int] = None):
    if skip:
        handle.seek(skip)
    remaining = limit
    while True:
        size = _CHUNK if remaining is None else min(_CHUNK, remaining)
        if size <= 0:
            break
        chunk = handle.read(size)
        if not chunk:
            break
        hasher.update(chunk)
        if remaining is not None:
            remaining -= len(chunk)
    return hasher


def _digest(
    path: Path, hasher, *, skip: int = 0, limit: Optional[int] = None
) -> Optional[str]:
    try:
        with path.open("rb") as handle:
            _hash_stream(handle, hasher, skip=skip, limit=limit)
    except (OSError, ValueError):
        logging.debug("Não foi possível calcular hash de %s", path, exc_info=True)
        return None
    return hasher.hexdigest()


def md5_of_file(
    path: Path, *, skip: int = 0, limit: Optional[int] = None
) -> Optional[str]:
    """MD5 do arquivo (ou de uma janela dele, com ``skip``/``limit``)."""
    return _digest(path, md5(), skip=skip, limit=limit)


def sha1_of_file(path: Path, *, limit: Optional[int] = None) -> Optional[str]:
    return _digest(path, sha1(), limit=limit)


def crc32_of_file(path: Path, *, limit: Optional[int] = None) -> Optional[str]:
    """CRC32 em hexadecimal, formato usado por catálogos de ROM antigos."""
    checksum = 0
    try:
        with path.open("rb") as handle:
            remaining = limit
            while True:
                size = _CHUNK if remaining is None else min(_CHUNK, remaining)
                if size <= 0:
                    break
                chunk = handle.read(size)
                if not chunk:
                    break
                checksum = zlib.crc32(chunk, checksum)
                if remaining is not None:
                    remaining -= len(chunk)
    except (OSError, ValueError):
        logging.debug("Não foi possível calcular CRC32 de %s", path, exc_info=True)
        return None
    return f"{checksum & 0xFFFFFFFF:08x}"


def partial_digest(
    path: Path, head_bytes: int = DEFAULT_PARTIAL_BYTES, tail_bytes: int | None = None
) -> Optional[str]:
    """MD5 da cabeça e da cauda de um arquivo, com o tamanho no meio.

    Dois arquivos grandes só recebem a mesma impressão digital se tiverem o
    mesmo tamanho, o mesmo começo e o mesmo fim. É o suficiente para seguir um
    arquivo movido; não é um hash do dump.
    """
    tail_bytes = head_bytes if tail_bytes is None else tail_bytes
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size <= head_bytes + tail_bytes:
        return md5_of_file(path)
    hasher = md5()
    try:
        with path.open("rb") as handle:
            hasher.update(handle.read(head_bytes))
            hasher.update(str(size).encode("ascii"))
            handle.seek(max(0, size - tail_bytes))
            hasher.update(handle.read(tail_bytes))
    except (OSError, ValueError):
        return None
    return hasher.hexdigest()


def file_signature(path: Path) -> dict[str, Any]:
    """Tamanho e mtime do arquivo, usados como chave de cache."""
    try:
        stat = path.stat()
    except OSError:
        return {}
    return {"size": stat.st_size, "mtime": int(stat.st_mtime)}


def read_header(path: Path, size: int = HEADER_BYTES) -> bytes:
    """Primeiros bytes do arquivo, ou ``b""`` quando não dá para ler."""
    try:
        with path.open("rb") as handle:
            return handle.read(size)
    except (OSError, ValueError):
        return b""


def _skip_copier_header(path: Path) -> int:
    """512 bytes de cabeçalho de copiadora, quando o tamanho denuncia.

    Cartuchos de SNES/Mega Drive copiados por copiadora de disquete ganham um
    cabeçalho de 512 bytes: o arquivo tem 512 bytes a mais que um múltiplo de
    1024. É a mesma regra que o RetroAchievements usa para ignorá-lo.
    """
    try:
        return 512 if path.stat().st_size % 1024 == 512 else 0
    except OSError:
        return 0


#: Plataformas em que o hash do RetroAchievements é o MD5 do arquivo inteiro.
_RA_FULL_FILE_PLATFORMS = frozenset(
    {"gb", "gbc", "gba", "nds", "n64", "saturn", "dreamcast", "psp"}
)

#: Plataformas que podem ter cabeçalho de copiadora antes do dump.
_RA_COPIER_HEADER_PLATFORMS = frozenset({"snes", "genesis", "megadrive"})


def retroachievements_hash(path: Path, platform: str) -> Optional[str]:
    """Hash no formato do RetroAchievements, só quando a regra é conhecida.

    Regras aplicadas (documentadas em
    https://docs.retroachievements.org/developer-docs/game-identification.html):

    * NES/Famicom Disk System: MD5 sem o cabeçalho iNES de 16 bytes;
    * SNES e Mega Drive/Genesis: MD5 sem o cabeçalho de copiadora de 512 bytes;
    * Game Boy, GBC, GBA, NDS, N64, Saturn, Dreamcast e PSP: MD5 do arquivo;
    * PlayStation: MD5 do executável quando o arquivo é um ``PS-X EXE``.

    Qualquer outra plataforma devolve ``None``: melhor não ter hash do que
    gravar um hash que o serviço não reconhece.
    """
    platform = (platform or "").lower()
    if platform in ("nes", "fds"):
        header = read_header(path, 4)
        skip = 16 if header[:4] == b"NES\x1a" else 0
        return md5_of_file(path, skip=skip)
    if platform in _RA_COPIER_HEADER_PLATFORMS:
        return md5_of_file(path, skip=_skip_copier_header(path))
    if platform == "psx":
        header = read_header(path, 8)
        if header[:8] == b"PS-X EXE":
            return md5_of_file(path)
        return None
    if platform in _RA_FULL_FILE_PLATFORMS:
        return md5_of_file(path)
    return None


def best_effort_hashes(
    path: Path,
    platform: str,
    *,
    full_limit: int = DEFAULT_FULL_HASH_LIMIT,
    partial_bytes: int = DEFAULT_PARTIAL_BYTES,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Hashes possíveis para o arquivo, dentro do limite de leitura.

    Devolve ``(hashes, assinatura)``. A assinatura diz qual caminho foi usado
    (``full`` ou ``partial``) e o tamanho lido, para a evidência registrar o
    que realmente foi feito.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return {}, {}
    if size <= 0:
        return {}, {"mode": "empty", "size": 0}

    hashes: dict[str, str] = {}
    if size <= full_limit:
        if digest := md5_of_file(path):
            hashes["md5"] = digest
            if digest_ra := retroachievements_hash(path, platform):
                hashes["ra"] = digest_ra
        return hashes, {"mode": "full", "size": size}

    if digest := partial_digest(path, partial_bytes):
        hashes["partial-md5"] = digest
    return hashes, {"mode": "partial", "size": size}


def file_size(path: Path) -> int:
    try:
        return os.stat(path).st_size
    except OSError:
        return 0
