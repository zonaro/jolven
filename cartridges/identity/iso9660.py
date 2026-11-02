# iso9660.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Leitor ISO9660 mínimo, só para identidade de jogos (issue #110).

Não é um extrator de imagem: abre o arquivo, lê o descritor primário e resolve
um caminho até um arquivo pequeno (``SYSTEM.CNF``, ``PARAM.SFO``,
``EBOOT.BIN``). Nada é descompactado, montado ou copiado para fora do processo.

O leitor ignora Joliet/Rock Ridge de propósito — os arquivos que interessam a
PS1/PS2/PSP usam nomes 8.3 em maiúsculas, iguais nos dois diretórios.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SECTOR_SIZE = 2048
_PVD_LBA = 16
_PVD_MAGIC = b"CD001"


class IsoError(Exception):
    """A imagem não é um ISO9660 legível."""


@dataclass(frozen=True)
class IsoEntry:
    path: str
    lba: int
    size: int
    is_dir: bool


def _u32(data: bytes, offset: int) -> int:
    """Inteiro de 32 bits no layout LE do registro de diretório."""
    if len(data) < offset + 4:
        return 0
    return int.from_bytes(data[offset : offset + 4], "little")


class IsoImage:
    """Imagem ISO9660 aberta em modo somente leitura."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self._handle = path.open("rb")
        except OSError as error:
            raise IsoError(str(error)) from error
        try:
            self._root = self._read_root()
        except IsoError:
            self._handle.close()
            raise
        except OSError as error:
            self._handle.close()
            raise IsoError(str(error)) from error

    # -- ciclo de vida ---------------------------------------------------
    def __enter__(self) -> "IsoImage":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._handle.close()
        except OSError:
            pass

    # -- leitura ---------------------------------------------------------
    def _read_at(self, lba: int, size: int) -> bytes:
        self._handle.seek(lba * SECTOR_SIZE)
        return self._handle.read(size)

    def _read_root(self) -> IsoEntry:
        sector = self._read_at(_PVD_LBA, SECTOR_SIZE)
        if len(sector) < 190 or sector[1:6] != _PVD_MAGIC:
            raise IsoError("descritor primário ausente")
        if sector[0] != 1:
            raise IsoError("descritor primário inválido")
        return self._parse_record(sector[156:190], "")

    def _parse_record(self, record: bytes, parent: str) -> IsoEntry:
        if len(record) < 34:
            raise IsoError("registro de diretório truncado")
        lba = _u32(record, 2)
        size = _u32(record, 10)
        flags = record[25]
        name_len = record[32]
        raw_name = record[33 : 33 + name_len]
        if raw_name in (b"\x00", b"\x01"):
            name = ""
        else:
            name = raw_name.decode("latin-1", "replace")
            if ";" in name:
                name = name.split(";", 1)[0]
            name = name.rstrip(".") or name
        path = f"{parent}/{name}".strip("/")
        return IsoEntry(
            path=path,
            lba=lba,
            size=size,
            is_dir=bool(flags & 0x02),
        )

    def _entries(self, directory: IsoEntry) -> list[IsoEntry]:
        if directory.size <= 0:
            return []
        # Um diretório nunca é lido inteiro: o limite evita que uma imagem
        # corrompida declare um diretório de gigabytes e trave a leitura.
        limit = min(directory.size, 4 * 1024 * 1024)
        data = self._read_at(directory.lba, limit)
        entries: list[IsoEntry] = []
        offset = 0
        while offset + 34 <= len(data):
            length = data[offset]
            if length == 0:
                # Fim do setor: o próximo setor recomeça o alinhamento.
                offset = ((offset // SECTOR_SIZE) + 1) * SECTOR_SIZE
                continue
            if offset + length > len(data):
                break
            try:
                entry = self._parse_record(
                    data[offset : offset + length], directory.path
                )
            except IsoError:
                break
            if entry.path and entry.path not in (directory.path,):
                entries.append(entry)
            offset += length
        return entries

    def resolve(self, iso_path: str) -> Optional[IsoEntry]:
        """Resolve ``/A/B/C`` (case-insensitive) até um arquivo ou diretório."""
        parts = [part for part in iso_path.replace("\\", "/").split("/") if part]
        current = self._root
        for index, part in enumerate(parts):
            if not current.is_dir:
                return None
            wanted = part.upper()
            match = None
            for entry in self._entries(current):
                name = entry.path.rsplit("/", 1)[-1].upper()
                if name == wanted:
                    match = entry
                    break
            if match is None:
                return None
            current = match
            if index < len(parts) - 1 and not current.is_dir:
                return None
        return current

    def read(self, entry: IsoEntry, limit: int = 64 * 1024) -> bytes:
        """Conteúdo do arquivo, truncado em ``limit`` bytes."""
        if entry.is_dir or entry.size <= 0:
            return b""
        return self._read_at(entry.lba, min(entry.size, limit))

    def iter_file(self, entry: IsoEntry, chunk_size: int = 1024 * 1024):
        """Itera o conteúdo de um arquivo em blocos, sem carregá-lo inteiro."""
        if entry.is_dir or entry.size <= 0:
            return
        remaining = entry.size
        self._handle.seek(entry.lba * SECTOR_SIZE)
        while remaining > 0:
            chunk = self._handle.read(min(chunk_size, remaining))
            if not chunk:
                return
            remaining -= len(chunk)
            yield chunk


def try_open(path: Path) -> Optional[IsoImage]:
    """Abre a imagem devolvendo ``None`` em vez de levantar erro."""
    try:
        return IsoImage(path)
    except (IsoError, OSError):
        logging.debug("Imagem não é ISO9660: %s", path)
        return None
