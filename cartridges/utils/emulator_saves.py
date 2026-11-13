# SPDX-License-Identifier: GPL-3.0-or-later
"""Safe, explicit emulator save-file backups.

No external emulator directory is scanned by default. Callers must supply
specific files, and restore destinations are chosen explicitly by the user.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

FORMAT_VERSION = 1
MAX_FILES = 500
MAX_SINGLE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
BUFFER_SIZE = 64 * 1024
MANIFEST_NAME = "jolven-save-manifest.json"


def _safe_name(name: str) -> str:
    if not name or len(name) > 180:
        raise ValueError("Invalid save filename")
    if name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("Invalid save filename")
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ValueError("Control character in save filename")
    return name


def create_save_backup(
    selected_files: Iterable[Path],
    target_zip: Path,
    *,
    emulator_hint: str = "",
) -> dict:
    """Create a portable archive from explicitly selected local files."""
    selected = [Path(file) for file in selected_files]
    if not selected or len(selected) > MAX_FILES:
        raise ValueError("Select between 1 and 500 save files")
    if len(emulator_hint) > 120:
        raise ValueError("Emulator hint too long")

    output = Path(target_zip)
    output.parent.mkdir(parents=True, exist_ok=True)
    target_real = output.resolve(strict=False)
    seen: set[Path] = set()
    for file in selected:
        if file.is_symlink() or not file.is_file():
            raise ValueError("Only regular save files can be backed up")
        resolved = file.resolve(strict=True)
        if resolved in seen or resolved == target_real:
            raise ValueError("Duplicate file or output included as input")
        seen.add(resolved)

    manifest = {
        "format": "jolven-emulator-save-backup",
        "version": FORMAT_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "emulator_hint": emulator_hint,
        "files": [],
    }

    temporary = None
    total = 0
    try:
        with tempfile.NamedTemporaryFile(
            dir=output.parent, prefix=".jolven-save-", suffix=".tmp",
            delete=False
        ) as tmp:
            temporary = Path(tmp.name)

        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for index, file in enumerate(selected):
                size = file.stat().st_size
                if size > MAX_SINGLE_BYTES or total + size > MAX_TOTAL_BYTES:
                    raise ValueError("Save files exceed backup size limits")
                entry = f"files/{index:04d}.bin"
                digest = hashlib.sha256()
                written = 0
                with file.open("rb") as source, archive.open(entry, "w") as target:
                    while True:
                        chunk = source.read(BUFFER_SIZE)
                        if not chunk:
                            break
                        written += len(chunk)
                        total += len(chunk)
                        if written > MAX_SINGLE_BYTES or total > MAX_TOTAL_BYTES:
                            raise ValueError("Save data exceeds backup size limits")
                        digest.update(chunk)
                        target.write(chunk)

                manifest["files"].append({
                    "entry": entry,
                    "name": _safe_name(file.name),
                    "size": written,
                    "sha256": digest.hexdigest(),
                })
            archive.writestr(
                MANIFEST_NAME,
                json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
            )

        # Atomic replacement of a Jolven-owned archive after successful write.
        os.replace(temporary, output)
        temporary = None
        return manifest
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def restore_save_backup(backup_zip: Path, destination: Path) -> list[Path]:
    """Restore verified saves; never overwrite existing destination files."""
    archive_path = Path(backup_zip)
    target_dir = Path(destination)
    if not target_dir.is_dir() or target_dir.is_symlink():
        raise ValueError("Select an existing regular destination folder")

    with zipfile.ZipFile(archive_path) as archive:
        infos = {info.filename: info for info in archive.infolist()}
        if MANIFEST_NAME not in infos or len(infos) > MAX_FILES + 1:
            raise ValueError("Invalid Jolven save archive")
        if infos[MANIFEST_NAME].file_size > 256 * 1024:
            raise ValueError("Manifest is too large")
        try:
            manifest = json.loads(archive.read(MANIFEST_NAME))
        except (ValueError, UnicodeDecodeError, KeyError) as error:
            raise ValueError("Invalid save manifest") from error
        if (
            not isinstance(manifest, dict)
            or manifest.get("format") != "jolven-emulator-save-backup"
            or manifest.get("version") != FORMAT_VERSION
            or not isinstance(manifest.get("files"), list)
        ):
            raise ValueError("Unsupported save archive format")

        entries = manifest["files"]
        if not entries or len(entries) > MAX_FILES:
            raise ValueError("Invalid number of save files")

        total = 0
        names: set[str] = set()
        with tempfile.TemporaryDirectory(prefix=".jolven-restore-", dir=target_dir) as staging:
            staging_dir = Path(staging)
            staged: list[tuple[str, Path]] = []
            for index, record in enumerate(entries):
                if not isinstance(record, dict):
                    raise ValueError("Invalid save record")
                entry = f"files/{index:04d}.bin"
                if record.get("entry") != entry:
                    raise ValueError("Unexpected ZIP path")
                info = infos.get(entry)
                if info is None or info.flag_bits & 1:
                    raise ValueError("Missing or encrypted save entry")
                name = _safe_name(record.get("name", ""))
                if name in names:
                    raise ValueError("Conflicting save filenames in archive")
                names.add(name)
                size = record.get("size")
                checksum = record.get("sha256")
                if (
                    not isinstance(size, int) or size < 0
                    or size > MAX_SINGLE_BYTES
                    or not isinstance(checksum, str) or len(checksum) != 64
                    or info.file_size != size
                ):
                    raise ValueError("Invalid save size/checksum")
                total += size
                if total > MAX_TOTAL_BYTES or (
                    size > max(1, info.compress_size) * 200
                ):
                    raise ValueError("Archive exceeds extraction limits")

                staged_file = staging_dir / f"{index:04d}.tmp"
                digest = hashlib.sha256()
                with archive.open(info) as data, staged_file.open("xb") as target:
                    copied = 0
                    while True:
                        chunk = data.read(BUFFER_SIZE)
                        if not chunk:
                            break
                        copied += len(chunk)
                        if copied > size:
                            raise ValueError("Save size mismatch")
                        digest.update(chunk)
                        target.write(chunk)
                if copied != size or digest.hexdigest() != checksum:
                    raise ValueError("Save checksum mismatch")
                staged.append((name, staged_file))

            expected = {MANIFEST_NAME, *(f"files/{i:04d}.bin" for i in range(len(entries)))}
            if set(infos) != expected:
                raise ValueError("Unexpected ZIP entries")

            created: list[Path] = []
            try:
                for name, staged_file in staged:
                    target = target_dir / name
                    if target.exists() or target.is_symlink():
                        raise FileExistsError(f"Save already exists: {name}")
                    # Staging and destination are on the same filesystem.
                    # Hardlink is an atomic exclusive create; never replace.
                    os.link(staged_file, target, follow_symlinks=False)
                    created.append(target)
                return created
            except Exception:
                for created_file in created:
                    created_file.unlink(missing_ok=True)
                raise
