# serials.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Seriais, códigos de mídia e reconhecimento de plataforma (issue #110).

Este módulo responde a uma pergunta só: *que jogo é este arquivo?* — sem
executar nada, sem rede e sem confiar no nome do arquivo quando existe um
cabeçalho melhor. O nome entra como última evidência, com confiança baixa.

Formatos cobertos:

* ISO9660 de PlayStation (``SYSTEM.CNF`` → serial ``SLUS-00594``), PlayStation 2
  (``BOOT2``) e PSP (``PSP_GAME/PARAM.SFO`` → ``DISC_ID``);
* GameCube (magic em 0x1C) e Wii (magic em 0x18), com o código de 6 caracteres;
* NDS e GBA pelo logotipo da Nintendo no cabeçalho;
* NES/Famicom (cabeçalho iNES), Mega Drive/Genesis (``SEGA`` em 0x100) e
  ``PS-X EXE`` avulso;
* seriais reconhecíveis no próprio nome do arquivo (PS1, PS2, PSP).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from hashlib import md5
from pathlib import Path
from typing import Optional

from cartridges.identity.hashing import HEADER_BYTES, read_header
from cartridges.identity.iso9660 import IsoEntry, IsoImage, try_open

#: Extensões que identificam a plataforma sem abrir o arquivo.
EXTENSION_PLATFORMS = {
    ".nes": "nes",
    ".fds": "fds",
    ".unf": "nes",
    ".sfc": "snes",
    ".smc": "snes",
    ".swc": "snes",
    ".fig": "snes",
    ".md": "genesis",
    ".gen": "genesis",
    ".smd": "genesis",
    ".32x": "sega32x",
    ".gb": "gb",
    ".gbc": "gbc",
    ".gba": "gba",
    ".nds": "nds",
    ".3ds": "3ds",
    ".cia": "3ds",
    ".cci": "3ds",
    ".n64": "n64",
    ".z64": "n64",
    ".v64": "n64",
    ".gcm": "gamecube",
    ".rvz": "gamecube",
    ".wbfs": "wii",
    ".wad": "wii",
    ".nsp": "switch",
    ".xci": "switch",
    ".pce": "pcengine",
    ".sms": "mastersystem",
    ".gg": "gamegear",
    ".a26": "atari2600",
    ".a52": "atari5200",
    ".a78": "atari7800",
    ".lynx": "lynx",
    ".vb": "virtualboy",
    ".ws": "wonderswan",
    ".wsc": "wonderswan",
    ".ngp": "neogeopocket",
    ".ngc": "neogeopocket",
    ".col": "colecovision",
    ".int": "intellivision",
    ".cue": "psx",
    ".chd": "psx",
    ".gdi": "dreamcast",
    ".cdi": "dreamcast",
    ".pbp": "psx",
    ".cso": "psp",
    ".iso": "iso",
}

#: Extensões ambíguas por si só: o conteúdo decide se é PS1, PS2, PSP ou outra
#: plataforma que também usa ISO9660.
_ISO_LIKE = frozenset({"iso", "cso", "chd", "cue"})

_NINTENDO_LOGO = bytes(
    (
        0x24,
        0xFF,
        0xAE,
        0x51,
        0x69,
        0x9A,
        0xA2,
        0x21,
        0x3D,
        0x84,
        0x82,
        0x0A,
        0x84,
        0xE4,
        0x09,
        0xAD,
    )
)

# ``SLUS_005.94``, ``SLUS-00594``, ``SLES 01234``; e o formato PSP, com cinco
# dígitos (``ULUS-10000``).
_PS_SERIAL_RE = re.compile(
    r"\b([A-Z]{4})[-_. ]?(\d{3})[.\-]?(\d{2})\b"
)
_PSP_SERIAL_RE = re.compile(r"\b([A-Z]{4})[-_ ]?(\d{5})\b")
_SYSTEM_CNF_BOOT_RE = re.compile(
    r"BOOT2?\s*=\s*cdrom0:[\\/]+([A-Za-z0-9_\-\.]+)", re.IGNORECASE
)

#: Tamanho máximo lido de um arquivo de configuração dentro da imagem.
_ISO_CONFIG_LIMIT = 64 * 1024


@dataclass(frozen=True)
class PlatformGuess:
    """Plataforma provável e o motivo dela."""

    platform: str
    source: str
    confidence: int


@dataclass(frozen=True)
class MediaIdentity:
    """O que a mídia diz sobre si mesma."""

    platform: str = ""
    serial: str = ""
    media_id: str = ""
    hashes: dict[str, str] = None  # type: ignore[assignment]
    source: str = "file"
    confidence: int = 0


def normalize_ps_serial(value: str) -> str:
    r"""Normaliza ``SLUS_005.94``/``SLUS-00594`` para ``SLUS-00594``."""
    match = _PS_SERIAL_RE.search(value.upper())
    if not match:
        return ""
    letters, first, second = match.groups()
    return f"{letters}-{first}{second}"


def normalize_psp_serial(value: str) -> str:
    match = _PSP_SERIAL_RE.search(value.upper())
    if not match:
        return ""
    letters, digits = match.groups()
    return f"{letters}-{digits}"


def platform_from_extension(path: Path) -> str:
    return EXTENSION_PLATFORMS.get(path.suffix.lower(), "")


def sniff_platform(header: bytes, path: Optional[Path] = None) -> PlatformGuess:
    """Reconhece a plataforma pelos primeiros bytes do arquivo."""
    if len(header) >= 4 and header[:4] == b"NES\x1a":
        return PlatformGuess("nes", "header", 3)
    if len(header) >= 8 and header[:8] == b"PS-X EXE":
        return PlatformGuess("psx", "header", 3)
    if len(header) >= 0x104 and header[0x100:0x104] == b"NCSD":
        return PlatformGuess("3ds", "header", 3)
    if len(header) >= 0x104 and header[0x100:0x104] == b"HEAD":
        return PlatformGuess("switch", "header", 2)
    if len(header) >= 0x20:
        if header[0x18:0x1C] == b"\x5d\x1c\x9e\xa3":
            return PlatformGuess("wii", "header", 3)
        if header[0x1C:0x20] == b"\xc2\x33\x9f\x3d":
            return PlatformGuess("gamecube", "header", 3)
    if len(header) >= 0xB3 and header[4:20] == _NINTENDO_LOGO:
        # O logotipo é comum a GBA e NDS; o marcador 0x96 em 0xB2 é do GBA.
        if header[0xB2] == 0x96:
            return PlatformGuess("gba", "header", 3)
        return PlatformGuess("nds", "header", 2)
    if len(header) >= 0x104 and header[0x100:0x104] == b"SEGA":
        return PlatformGuess("genesis", "header", 3)
    if len(header) >= 0x8006 and header[0x8001:0x8006] == b"CD001":
        return PlatformGuess("iso", "header", 3)

    extension = platform_from_extension(path) if path else ""
    if extension and extension != "iso":
        return PlatformGuess(extension, "extension", 1)
    return PlatformGuess("", "unknown", 0)


def _read_sfo(data: bytes) -> dict[str, str]:
    """Lê um PARAM.SFO (PSP/PS3) e devolve só as chaves de texto.

    Estrutura: magic ``\\0PSF``, três offsets e a contagem de entradas; cada
    entrada tem 16 bytes e aponta para a tabela de chaves e a de dados. Qualquer
    inconsistência devolve ``{}`` — o SFO é escrito pelo próprio jogo e não é
    confiável.
    """
    if len(data) < 20 or data[:4] != b"\x00PSF":
        return {}
    key_table = int.from_bytes(data[8:12], "little")
    data_table = int.from_bytes(data[12:16], "little")
    count = int.from_bytes(data[16:20], "little")
    if count <= 0 or count > 256:
        return {}
    if not (20 <= key_table < len(data)) or not (20 <= data_table < len(data)):
        return {}

    values: dict[str, str] = {}
    for index in range(count):
        entry_offset = 20 + index * 16
        if entry_offset + 16 > len(data):
            break
        key_offset = int.from_bytes(data[entry_offset : entry_offset + 2], "little")
        fmt = int.from_bytes(
            data[entry_offset + 2 : entry_offset + 4], "little"
        )
        length = int.from_bytes(data[entry_offset + 4 : entry_offset + 8], "little")
        data_offset = int.from_bytes(
            data[entry_offset + 12 : entry_offset + 16], "little"
        )
        key_start = key_table + key_offset
        key_end = data.find(b"\x00", key_start)
        if key_end < 0:
            break
        key = data[key_start:key_end].decode("utf-8", "replace")
        value_start = data_table + data_offset
        value_end = min(len(data), value_start + max(0, length))
        if value_end <= value_start:
            continue
        raw = data[value_start:value_end]
        if fmt & 0x0400:
            values[key] = raw.split(b"\x00", 1)[0].decode("utf-8", "replace")
        elif fmt & 0x0004:
            if len(raw) >= 4:
                values[key] = str(int.from_bytes(raw[:4], "little"))
    return values


def _md5_iso_entry(image: IsoImage, entry: IsoEntry) -> Optional[str]:
    """MD5 do conteúdo de um arquivo dentro da imagem, em blocos."""
    if entry.size <= 0:
        return None
    hasher = md5()
    try:
        for chunk in image.iter_file(entry):
            hasher.update(chunk)
    except OSError:
        return None
    return hasher.hexdigest()


def _identify_iso(path: Path) -> MediaIdentity:
    """Lê SYSTEM.CNF/PARAM.SFO dentro da imagem para achar serial e plataforma."""
    with_iso = try_open(path)
    if with_iso is None:
        return MediaIdentity()
    try:
        psp_param = with_iso.resolve("PSP_GAME/PARAM.SFO")
        if psp_param is not None:
            values = _read_sfo(with_iso.read(psp_param, _ISO_CONFIG_LIMIT))
            serial = values.get("DISC_ID", "").strip().upper()
            hashes: dict[str, str] = {}
            eboot = with_iso.resolve("PSP_GAME/SYSDIR/EBOOT.BIN")
            if eboot is not None and (digest := _md5_iso_entry(with_iso, eboot)):
                # O RetroAchievements identifica ISO de PSP pelo EBOOT.BIN.
                hashes["ra"] = digest
            return MediaIdentity(
                platform="psp",
                serial=normalize_psp_serial(serial),
                media_id=serial,
                hashes=hashes,
                source="iso-param-sfo",
                confidence=3 if serial else 1,
            )

        system_cnf = with_iso.resolve("SYSTEM.CNF")
        if system_cnf is not None:
            config = with_iso.read(system_cnf, _ISO_CONFIG_LIMIT).decode(
                "latin-1", "replace"
            )
            match = _SYSTEM_CNF_BOOT_RE.search(config)
            if match:
                executable = match.group(1).upper()
                serial = normalize_ps_serial(executable)
                platform = "ps2" if "BOOT2" in config.upper() else "psx"
                hashes = {}
                entry = with_iso.resolve(executable)
                if entry is None and not executable.endswith("."):
                    entry = with_iso.resolve(executable + ".1")
                if entry is not None and (digest := _md5_iso_entry(with_iso, entry)):
                    # PlayStation é identificado pelo executável do jogo, não
                    # pelo MD5 da imagem inteira.
                    hashes["ra"] = digest
                return MediaIdentity(
                    platform=platform,
                    serial=serial,
                    media_id=executable,
                    hashes=hashes,
                    source="iso-system-cnf",
                    confidence=3 if serial else 1,
                )

        psx_exe = with_iso.resolve("PSX.EXE")
        if psx_exe is not None:
            hashes = {}
            if digest := _md5_iso_entry(with_iso, psx_exe):
                hashes["ra"] = digest
            return MediaIdentity(
                platform="psx",
                hashes=hashes,
                source="iso-psx-exe",
                confidence=2,
            )
    finally:
        with_iso.close()
    return MediaIdentity()


def _identify_avulso(path: Path, header: bytes) -> MediaIdentity:
    """Seriais e códigos que estão no cabeçalho, sem precisar de ISO."""
    guess = sniff_platform(header, path)
    platform = guess.platform
    serial = ""
    media_id = ""

    if platform in ("gamecube", "wii") and len(header) >= 6:
        code = header[0:6]
        if all(32 <= byte < 127 for byte in code):
            media_id = code.decode("ascii")
            serial = media_id
    elif platform == "gba" and len(header) >= 0xB0:
        code = header[0xAC:0xB0]
        if all(32 <= byte < 127 for byte in code):
            media_id = code.decode("ascii")
    elif platform == "nds" and len(header) >= 0x10:
        code = header[0x0C:0x10]
        if all(32 <= byte < 127 for byte in code):
            media_id = code.decode("ascii")

    return MediaIdentity(
        platform=platform,
        serial=serial,
        media_id=media_id,
        hashes={},
        source=guess.source,
        confidence=guess.confidence,
    )


def serial_from_filename(name: str) -> tuple[str, str, int]:
    """``(plataforma, serial, confiança)`` a partir do nome do arquivo.

    O nome é a evidência mais fraca da cadeia: só entra quando não há
    cabeçalho, e nunca sozinho transforma dois arquivos no mesmo jogo.
    """
    upper = (name or "").upper()
    if psp := normalize_psp_serial(upper):
        return "psp", psp, 1
    if ps := normalize_ps_serial(upper):
        return "psx", ps, 1
    return "", "", 0


def identify_media(path: Path, platform_hint: str = "") -> MediaIdentity:
    """Identifica o arquivo combinando extensão, cabeçalho, ISO9660 e nome.

    ``platform_hint`` vem do importador (o Dolphin já sabe que o jogo é de
    GameCube, por exemplo) e só é usado quando o arquivo não diz nada.
    """
    if not path.is_file():
        return MediaIdentity(platform=platform_hint)

    header = read_header(path, HEADER_BYTES)
    guess = sniff_platform(header, path)
    platform = guess.platform
    serial = ""
    media_id = ""
    hashes: dict[str, str] = {}
    source = guess.source
    confidence = guess.confidence

    if platform in _ISO_LIKE or platform in ("iso", ""):
        iso = _identify_iso(path)
        if iso.platform:
            platform = iso.platform
            serial = iso.serial
            media_id = iso.media_id
            hashes = dict(iso.hashes)
            source = iso.source
            confidence = iso.confidence

    if platform and platform not in ("iso", ""):
        avulso = _identify_avulso(path, header)
        if avulso.platform and not serial:
            serial = avulso.serial
            media_id = media_id or avulso.media_id
            if not source or source == "extension":
                source = avulso.source
            confidence = max(confidence, avulso.confidence)

    if not serial:
        name_platform, name_serial, name_confidence = serial_from_filename(
            path.name
        )
        if name_serial and (not platform or platform == name_platform):
            serial = name_serial
            platform = platform or name_platform
            source = "filename"
            confidence = name_confidence

    if not platform and platform_hint:
        platform = platform_hint

    return MediaIdentity(
        platform=platform or platform_hint,
        serial=serial,
        media_id=media_id,
        hashes=hashes,
        source=source,
        confidence=confidence,
    )
