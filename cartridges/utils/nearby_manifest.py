# SPDX-License-Identifier: GPL-3.0-or-later
"""Strict, offline manifest for planned Jolven Nearby LAN transfers.

This is the file identity/validation layer only. It deliberately does NOT
listen on sockets, perform discovery, or claim the pairing/TLS protocol
is implemented. Network transport must be audited separately.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PROTOCOL_VERSION = 1
MAX_FILES = 128
MAX_FILE_BYTES = 8 * 1024 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_NAME = 180
CHUNK_SIZE = 256 * 1024
_ALLOWED_KINDS = frozenset(("rom", "save", "cover", "label"))
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class TransferFile:
    name: str
    size: int
    sha256: str
    kind: str


def _safe_name(name: object) -> str:
    if not isinstance(name, str) or not name or len(name) > MAX_NAME:
        raise ValueError("Invalid file name")
    if name in (".", "..") or name.startswith("."):
        raise ValueError("Hidden/traversal names are not allowed")
    if any(ord(c) < 32 for c in name) or "/" in name or "\\" in name or ":" in name:
        raise ValueError("Only safe single-component names are allowed")
    if name.strip() != name or name.endswith("."):
        raise ValueError("Unsafe file name")
    return name


def _validate(files: Iterable[TransferFile]) -> tuple[TransferFile, ...]:
    entries = tuple(files)
    if not entries or len(entries) > MAX_FILES:
        raise ValueError("Invalid number of transfer files")
    total = 0
    seen: set[str] = set()
    for entry in entries:
        name = _safe_name(entry.name)
        if name.casefold() in seen:
            raise ValueError("Duplicate file name")
        seen.add(name.casefold())
        if type(entry.size) is not int or not (0 <= entry.size <= MAX_FILE_BYTES):
            raise ValueError("Invalid file size")
        total += entry.size
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Transfer exceeds size limit")
        if not isinstance(entry.sha256, str) or not _SHA256.fullmatch(entry.sha256):
            raise ValueError("Invalid SHA-256 digest")
        if entry.kind not in _ALLOWED_KINDS:
            raise ValueError("Unsupported file kind")
    return entries


def create_manifest(files: Iterable[tuple[Path, str]]) -> bytes:
    """Hash only explicitly selected local regular files; no symlinks."""
    result: list[TransferFile] = []
    for raw_path, kind in files:
        path = Path(raw_path)
        if path.is_symlink() or not path.is_file():
            raise ValueError("Source is not a regular file")
        _safe_name(path.name)
        stat = path.stat()
        if stat.st_size > MAX_FILE_BYTES:
            raise ValueError("Source exceeds maximum size")
        digest = hashlib.sha256()
        seen = 0
        with path.open("rb") as handle:
            while True:
                block = handle.read(CHUNK_SIZE)
                if not block:
                    break
                digest.update(block)
                seen += len(block)
                if seen > MAX_FILE_BYTES:
                    raise ValueError("Source changed while hashing")
        if seen != stat.st_size:
            raise ValueError("Source changed while hashing")
        result.append(TransferFile(path.name, seen, digest.hexdigest(), kind))
    checked = _validate(result)
    encoded = json.dumps(
        {"version": PROTOCOL_VERSION, "files": [
            {"name": item.name, "size": item.size, "sha256": item.sha256,
             "kind": item.kind} for item in checked
        ]}, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ValueError("Manifest exceeds size limit")
    return encoded


def decode_manifest(payload: bytes) -> tuple[TransferFile, ...]:
    """Validate untrusted manifest BEFORE accepting any transport payload."""
    if not isinstance(payload, bytes) or len(payload) > MAX_MANIFEST_BYTES:
        raise ValueError("Invalid manifest envelope")
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Invalid manifest JSON") from error
    if not isinstance(data, dict) or set(data) != {"version", "files"}:
        raise ValueError("Unknown manifest fields")
    if type(data["version"]) is not int or data["version"] != PROTOCOL_VERSION:
        raise ValueError("Unsupported manifest version")
    rows = data["files"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_FILES:
        raise ValueError("Invalid manifest length")
    result: list[TransferFile] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"name", "size", "sha256", "kind"}:
            raise ValueError("Malformed manifest entry")
        result.append(TransferFile(
            row["name"], row["size"], row["sha256"], row["kind"]
        ))
    return _validate(result)


def verify_file(path: Path, entry: TransferFile) -> bool:
    """Verify an explicitly staged file before any final rename/import."""
    _validate((entry,))
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        return False
    if path.stat().st_size != entry.size:
        return False
    digest = hashlib.sha256()
    read = 0
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
            read += len(chunk)
            if read > entry.size:
                return False
    return read == entry.size and digest.hexdigest() == entry.sha256
