# installer.py
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Applies / restores the Adwaita-for-Steam skin to a Steam installation.
#
# The mechanics are adapted from upstream Adwaita-for-Steam 4.4
# (``scripts/installer``): copy the skin tree into ``<steam>/steamui/adwaita``,
# generate ``config.css``, bundle each entry stylesheet to ``*.min.css`` and
# wrap the three Steam CSS files with a marker patch that re-imports the
# original (``X.original.css``) followed by the bundled skin.
#
# Jolven-specific guarantees:
# * every write is atomic (temp file + ``os.replace``);
# * a failure rolls the installation back to its previous state;
# * the operation is idempotent — a second run with the same inputs changes
#   nothing (comparison ignores the volatile "Installed at" line);
# * a patch is never written larger than the original file: it is padded with
#   spaces to the exact original size;
# * no ``subprocess``, no network, everything with :mod:`pathlib`.

from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from cartridges.integrations.steam_skin import vendor
from cartridges.integrations.steam_skin.constants import (
    BACKUP_SUFFIX,
    CONFIG_CSS_NAME,
    CSS_DIR,
    DEFAULT_COLORTHEME,
    ENTRY_CSS_NAMES,
    NAMED_ACCENTS,
    PALETTE_RELATIVE,
    PATCH_COMMENT_SUFFIX,
    PATCH_FILES,
    PATCH_HEADER,
    PATCH_HEADER_V3,
    PATCH_INSTALLED_PREFIX,
    PATCH_VERSION_PREFIX,
    SKIN_DIR_NAME,
    STEAMUI_DIR,
)
from cartridges.integrations.steam_skin.detector import (
    expand_steam_path,
    is_steam_path_valid,
)

# ── Errors ───────────────────────────────────────────────────────────────


class SkinError(RuntimeError):
    """Raised when the skin cannot be installed or restored."""


class PatchTooLargeError(SkinError):
    """Raised when a generated patch would exceed the original file size."""


# ── Paths ────────────────────────────────────────────────────────────────


def diretorio_css(steam_path: "str | Path") -> Path:
    """``<steam>/steamui/css`` for *steam_path*."""
    return expand_steam_path(steam_path) / STEAMUI_DIR / CSS_DIR


def diretorio_skin(steam_path: "str | Path") -> Path:
    """``<steam>/steamui/adwaita`` for *steam_path*."""
    return expand_steam_path(steam_path) / STEAMUI_DIR / SKIN_DIR_NAME


def caminho_backup(steam_path: "str | Path", css_name: str) -> Path:
    """``<steam>/steamui/css/<name>.original.css`` for *css_name*."""
    return diretorio_css(steam_path) / Path(css_name).with_suffix(BACKUP_SUFFIX)


def _patch_path(steam: Path, css_name: str) -> Path:
    return diretorio_css(steam) / css_name


# ── Low-level helpers ────────────────────────────────────────────────────

_RE_IMPORT = re.compile(
    r"^\s*@import\s+url\((?P<quote>[\"'])(?P<path>.+?)(?P=quote)\)\s*;\s*(?:/\*.*\*/\s*)?$"
)
_RE_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_RE_BLOCK = re.compile(r"\s*([{};,])\s*")
_RE_MULTISPACE = re.compile(r"\s+")
_RE_HEX = re.compile(r"^#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?$")
_RE_RGB = re.compile(r"^rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)$")


def _first_line(path: Path) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.readline().strip()
    except OSError:
        return ""


def primeira_linha(path: "str | Path") -> str:
    """Public wrapper returning the stripped first line of a CSS file."""
    return _first_line(Path(path))


def _read_with_mode(path: Path) -> tuple[Optional[bytes], Optional[int]]:
    try:
        return path.read_bytes(), path.stat().st_mode
    except OSError:
        return None, None


def _atomic_write(path: Path, data: bytes, mode: Optional[int] = None) -> None:
    """Write *data* to *path* atomically (temp file + ``os.replace``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp{os.getpid()}")
    if mode is None and path.exists():
        try:
            mode = path.stat().st_mode
        except OSError:
            mode = None
    with open(temp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    if mode is not None:
        try:
            os.chmod(temp, mode & 0o7777)
        except OSError:
            pass
    os.replace(temp, path)


def _normalized(data: bytes) -> bytes:
    """Content used for the idempotency check.

    Drops the volatile ``Installed at`` line and per-line trailing
    whitespace (the padding appended to match the original size), so a
    second identical run is recognised as "no diff".
    """
    lines: list[str] = []
    for line in data.decode("utf-8", errors="replace").split("\n"):
        if line.strip().startswith(PATCH_INSTALLED_PREFIX):
            continue
        lines.append(line.rstrip())
    return "\n".join(lines).strip().encode("utf-8")


def _write_if_changed(path: Path, data: bytes, mode: Optional[int] = None) -> bool:
    """Write only when the normalised content differs. Returns whether it wrote."""
    if path.is_file():
        try:
            if _normalized(path.read_bytes()) == _normalized(data):
                return False
        except OSError:
            pass
    _atomic_write(path, data, mode)
    return True


def _rmtree_quiet(path: Path) -> None:
    if path.exists():
        try:
            shutil.rmtree(path)
        except OSError as error:
            logging.warning("Could not remove %s: %s", path, error)


class _Transaction:
    """Minimal undo/commit registry used to roll an install back on failure."""

    def __init__(self) -> None:
        self._undo: list[Callable[[], None]] = []
        self._commit: list[Callable[[], None]] = []

    def undo_on_failure(self, action: Callable[[], None]) -> None:
        self._undo.append(action)

    def run_on_commit(self, action: Callable[[], None]) -> None:
        self._commit.append(action)

    def commit(self) -> None:
        for action in self._commit:
            try:
                action()
            except OSError as error:
                logging.warning("Commit action failed: %s", error)
        self._undo.clear()
        self._commit.clear()

    def rollback(self) -> None:
        for action in reversed(self._undo):
            try:
                action()
            except OSError as error:
                logging.warning("Rollback action failed: %s", error)
        self._undo.clear()
        self._commit.clear()


def _snapshotter(path: Path) -> Callable[[], None]:
    """Return a callable that restores *path* to its current state."""
    data, mode = _read_with_mode(path)

    def restore() -> None:
        if data is None:
            if path.exists():
                path.unlink()
        else:
            _atomic_write(path, data, mode)

    return restore


# ── Patch helpers ────────────────────────────────────────────────────────


def _backup_name(css_name: str) -> str:
    return Path(css_name).with_suffix(BACKUP_SUFFIX).name


def _build_patch_bytes(patch_key: str, version: str, installed_at: str) -> bytes:
    """Header + version + date + imports, exactly as upstream ``_build_patch``."""
    entrypoint = f"{patch_key}.min.css"
    lines = [
        PATCH_HEADER,
        f"{PATCH_VERSION_PREFIX}{version}{PATCH_COMMENT_SUFFIX}",
        f"{PATCH_INSTALLED_PREFIX}{installed_at}{PATCH_COMMENT_SUFFIX}",
        f'@import url("{_backup_name(PATCH_FILES[patch_key])}");',
        f'@import url("../{SKIN_DIR_NAME}/{entrypoint}");',
    ]
    if patch_key == "base":
        lines.append(f'@import url("../{SKIN_DIR_NAME}/{CONFIG_CSS_NAME}");')
    return ("\n".join(lines) + "\n").encode("utf-8")


def info_do_patch(css_path: "str | Path") -> dict[str, str]:
    """Read the marker/version/date from a patched CSS file.

    Returns an empty dict when the file is not ours or cannot be read.
    """
    path = Path(css_path)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            first = handle.readline().strip()
            if first != PATCH_HEADER:
                return {}
            info: dict[str, str] = {"header": first}
            for _ in range(2):
                line = handle.readline().strip()
                if line.startswith(PATCH_VERSION_PREFIX):
                    info["version"] = line[len(PATCH_VERSION_PREFIX):].rsplit(" ", 1)[0].strip()
                elif line.startswith(PATCH_INSTALLED_PREFIX):
                    info["installed_at"] = line[len(PATCH_INSTALLED_PREFIX):].rsplit(" ", 1)[0].strip()
    except OSError:
        return {}
    return info


# ── config.css ───────────────────────────────────────────────────────────


def _system_accent_css() -> str:
    """Resolve the system accent to a CSS value, falling back to Adwaita blue."""
    try:
        from gi.repository import Gio  # local import: installer works without GI

        interface = Gio.Settings.new("org.gnome.desktop.interface")
        name = interface.get_string("accent-color").strip().lower()
        if name in NAMED_ACCENTS:
            return f"var(--adw-accent-{name})"

        appearance = Gio.Settings.new("org.freedesktop.appearance")
        values = appearance.get_value("accent-color").unpack()
        if isinstance(values, tuple) and len(values) == 3:
            return "#" + "".join(format(round(float(c) * 255), "02x") for c in values)
    except Exception as error:  # pylint: disable=broad-exception-caught
        logging.debug("Could not resolve system accent: %s", error)
    return "var(--adw-accent-blue)"


def _accent_to_css(accent: object) -> Optional[str]:
    """Map an accent option to the ``--adw-system-accent`` declaration."""
    if accent is None:
        return None
    raw = str(accent).strip()
    if not raw or raw.lower() == "theme":
        return None
    low = raw.lower()
    if low == "auto":
        return f"--adw-system-accent: {_system_accent_css()};"
    if low in NAMED_ACCENTS:
        return f"--adw-system-accent: var(--adw-accent-{low});"
    if _RE_HEX.match(raw) or _RE_RGB.match(low):
        return f"--adw-system-accent: {raw};"
    logging.warning("Ignoring unsupported accent colour: %r", accent)
    return None


def _build_config_css(
    tema_slug: str,
    accent: object,
    mode: str,
    opcoes: dict,
    skin_dir: Path,
) -> str:
    """Compose the skin ``config.css`` (mirrors upstream ``AdwColors.to_css``)."""
    opcoes = opcoes or {}
    imports: list[str] = []

    def _add(relative: str, comment: str) -> None:
        if (skin_dir / relative).is_file():
            imports.append(f'@import url("{relative}") /* {comment} */;')
        else:
            logging.info("Skipping %s: not present in the skin tree", relative)

    if tema_slug and tema_slug != DEFAULT_COLORTHEME:
        _add(f"colorthemes/{tema_slug}/{tema_slug}.css", f"Color theme: {tema_slug}")

    for extra in opcoes.get("extras") or []:
        _add(f"extras/{extra}.css", f"Extra: {extra}")

    font = opcoes.get("font")
    if font:
        _add(f"fonts/{font}/{font}.css", f"Font: {font}")

    if opcoes.get("custom_css"):
        _add("custom.css", "Custom CSS")

    windowcontrols = opcoes.get("windowcontrols_theme")
    if windowcontrols:
        _add(f"windowcontrols/{windowcontrols}.css", f"Window controls theme: {windowcontrols}")

    if opcoes.get("windowcontrols_layout"):
        logging.info("Window-controls layout is not vendored; skipping it")

    variables: list[str] = []
    accent_css = _accent_to_css(accent)
    if accent_css:
        variables.append(accent_css)
    scheme = str(mode or "auto").strip().lower()
    if scheme in ("light", "dark"):
        variables.append(f"--adw-color-scheme: {scheme};")

    lines = list(imports)
    if variables:
        lines.append("")
        lines.append(":root")
        lines.append("{")
        lines.extend(f"    {variable}" for variable in variables)
        lines.append(f"}} /* Accent color: {accent}, color scheme: {mode} */")
    return "\n".join(lines) + "\n"


# ── Skin tree build ──────────────────────────────────────────────────────


def _default_entry_css(name: str, version: str) -> str:
    """Minimal entry stylesheet used when the vendor does not supply one."""
    if name == "base.css":
        return (
            '@import url("css/_colors/palette.css");\n'
            "\n"
            ":root\n"
            "{\n"
            f'    --adw-version: "{version}";\n'
            "}\n"
        )
    stem = name.rsplit(".", 1)[0]
    return f"/* Adwaita-for-Steam {stem} entry (structural CSS not vendored) */\n"


def _inline_css_imports(file: Path, seen: Optional[set[Path]] = None) -> str:
    seen = seen if seen is not None else set()
    try:
        resolved = file.resolve()
    except OSError:
        return ""
    if resolved in seen:
        return ""
    seen.add(resolved)
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError:
        return ""
    result: list[str] = []
    for line in text.splitlines():
        match = _RE_IMPORT.match(line)
        if match:
            result.append(_inline_css_imports(resolved.parent / match.group("path"), seen))
        else:
            result.append(line)
    return "\n".join(result)


def _minify_css(css: str) -> str:
    css = _RE_COMMENT.sub("", css)
    css = _RE_BLOCK.sub(r"\1", css)
    css = _RE_MULTISPACE.sub(" ", css)
    return css.strip()


def _bundle_css(entry: Path) -> Path:
    bundle = entry.with_suffix(".min.css")
    _write_if_changed(bundle, _minify_css(_inline_css_imports(entry)).encode("utf-8"))
    return bundle


def _build_skin_tree(
    build_dir: Path,
    tema_slug: str,
    accent: object,
    mode: str,
    opcoes: dict,
) -> None:
    """Materialise the complete skin tree inside *build_dir*."""
    build_dir.mkdir(parents=True, exist_ok=True)

    palette = vendor.palette_path()
    if not palette.is_file():
        raise SkinError("vendor palette.css is missing")
    destination_palette = build_dir / PALETTE_RELATIVE
    destination_palette.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(palette, destination_palette)

    colorthemes = vendor.colorthemes_dir()
    if colorthemes.is_dir():
        shutil.copytree(colorthemes, build_dir / "colorthemes", dirs_exist_ok=True)

    root = vendor.vendor_root()
    for name in ("VERSION", "LICENSE"):
        source = root / name
        if source.is_file():
            shutil.copy2(source, build_dir / name)

    custom = opcoes.get("custom_css") if opcoes else None
    if custom:
        custom_path = expand_steam_path(custom)
        if custom_path.is_file():
            shutil.copy2(custom_path, build_dir / "custom.css")

    version = vendor.vendor_version()
    for name in ENTRY_CSS_NAMES.values():
        target = build_dir / name
        if not target.is_file():
            target.write_text(_default_entry_css(name, version), encoding="utf-8")

    for name in ENTRY_CSS_NAMES.values():
        _bundle_css(build_dir / name)

    config = _build_config_css(tema_slug, accent, mode, opcoes or {}, build_dir)
    (build_dir / CONFIG_CSS_NAME).write_text(config, encoding="utf-8")


def _dir_snapshot(root: Path) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    if not root.is_dir():
        return snapshot
    for path in root.rglob("*"):
        if path.is_file():
            try:
                snapshot[str(path.relative_to(root))] = path.read_bytes()
            except OSError:
                continue
    return snapshot


def _replace_skin(steam: Path, build_dir: Path, tx: _Transaction) -> bool:
    """Swap the built skin tree into place, atomically and idempotently."""
    target = diretorio_skin(steam)
    if _dir_snapshot(build_dir) == _dir_snapshot(target):
        _rmtree_quiet(build_dir)
        return False

    old = target.with_name(f"{target.name}.old{os.getpid()}")
    had_target = target.exists()
    if had_target:
        _rmtree_quiet(old)
        os.replace(target, old)
        tx.undo_on_failure(lambda: _restore_old_skin(target, old))
        tx.run_on_commit(lambda: _rmtree_quiet(old))
    else:
        tx.undo_on_failure(lambda: _rmtree_quiet(target))

    os.replace(build_dir, target)
    return True


def _restore_old_skin(target: Path, old: Path) -> None:
    _rmtree_quiet(target)
    if old.exists():
        os.replace(old, target)


# ── Patch application ────────────────────────────────────────────────────


def _refresh_backup(tx: _Transaction, path: Path, backup: Path) -> int:
    """Ensure ``backup`` holds *path*'s pristine content; return its size.

    When a backup already exists and differs from the current file, Steam
    (or the user) replaced the file: the old backup is stale and is
    refreshed, but never blindly trusted to overwrite the new content.
    """
    current = path.read_bytes()
    tx.undo_on_failure(_snapshotter(backup))
    if backup.is_file():
        try:
            previous = backup.read_bytes()
        except OSError:
            previous = b""
        if previous != current:
            logging.info(
                "Refreshing stale backup %s (%d -> %d bytes)",
                backup.name,
                len(previous),
                len(current),
            )
            _atomic_write(backup, current)
    else:
        _atomic_write(backup, current)
    return len(current)


def _apply_patch_file(
    tx: _Transaction,
    steam: Path,
    patch_key: str,
    css_name: str,
    version: str,
    installed_at: str,
) -> bool:
    path = _patch_path(steam, css_name)
    backup = caminho_backup(steam, css_name)
    first = _first_line(path)

    if first == PATCH_HEADER_V3:
        if not backup.is_file():
            logging.warning("Found Adwaita-for-Steam v3 patch on %s without backup; skipping", css_name)
            return False
        original_size = backup.stat().st_size
    elif first == PATCH_HEADER:
        if backup.is_file():
            original_size = backup.stat().st_size
        else:
            logging.warning("Patch on %s has no backup; original size unknown", css_name)
            original_size = 0
    else:
        original_size = _refresh_backup(tx, path, backup)

    payload = _build_patch_bytes(patch_key, version, installed_at)
    if original_size and len(payload) > original_size:
        raise PatchTooLargeError(
            f"patch for {css_name} ({len(payload)} bytes) exceeds original ({original_size} bytes)"
        )
    padded = payload + b" " * max(0, original_size - len(payload))

    tx.undo_on_failure(_snapshotter(path))
    return _write_if_changed(path, padded)


# ── Public API ───────────────────────────────────────────────────────────


def instalar(
    steam_path: "str | Path",
    tema_slug: str,
    accent: object = "auto",
    mode: str = "auto",
    opcoes_avancadas: Optional[dict] = None,
) -> bool:
    """Install/refresh the skin for *steam_path*.

    Returns ``True`` when something changed, ``False`` when the requested
    state already matched the installed one (idempotent). Raises
    :class:`SkinError` when the target is invalid or a step fails — in which
    case all changes are rolled back.
    """
    steam = expand_steam_path(steam_path)
    if not is_steam_path_valid(steam):
        raise SkinError(f"not a valid Steam interface directory: {steam}")
    if not vendor.vendor_available():
        raise SkinError("Adwaita-for-Steam vendor tree is missing")

    opcoes = opcoes_avancadas or {}
    build_dir = (steam / STEAMUI_DIR) / f".{SKIN_DIR_NAME}.build{os.getpid()}"
    tx = _Transaction()
    changed = False
    try:
        _rmtree_quiet(build_dir)
        _build_skin_tree(build_dir, tema_slug, accent, mode, opcoes)
        changed = _replace_skin(steam, build_dir, tx) or changed

        version = vendor.vendor_version()
        installed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for patch_key, css_name in PATCH_FILES.items():
            if not (diretorio_css(steam) / css_name).is_file():
                logging.info("Skipping %s patch: file not present", css_name)
                continue
            changed = _apply_patch_file(tx, steam, patch_key, css_name, version, installed_at) or changed

        tx.commit()
        logging.info("Steam skin installed to %s (changed=%s)", steam, changed)
        return changed
    except Exception as error:  # noqa: BLE001 - rollback then re-raise as SkinError
        tx.rollback()
        _rmtree_quiet(build_dir)
        logging.error("Steam skin install failed for %s: %s", steam, error)
        if isinstance(error, SkinError):
            raise
        raise SkinError(str(error)) from error


def restaurar(steam_path: "str | Path") -> bool:
    """Restore the original Steam CSS files and remove the skin directory.

    Idempotent: returns ``False`` when there is nothing to restore.
    """
    steam = expand_steam_path(steam_path)
    css_dir = diretorio_css(steam)
    changed = False

    for css_name in PATCH_FILES.values():
        path = css_dir / css_name
        backup = caminho_backup(steam, css_name)
        if not backup.is_file():
            if path.is_file() and _first_line(path) == PATCH_HEADER:
                logging.warning("Cannot restore %s: backup is missing", css_name)
            continue
        try:
            if path.is_file() and path.read_bytes() == backup.read_bytes():
                backup.unlink()
                changed = True
                continue
        except OSError:
            pass
        os.replace(backup, path)
        changed = True
        logging.info("Restored %s from backup", css_name)

    skin = diretorio_skin(steam)
    if skin.is_dir():
        _rmtree_quiet(skin)
        changed = True

    if changed:
        logging.info("Steam skin restored for %s", steam)
    return changed


def esta_instalada(steam_path: "str | Path") -> bool:
    """``True`` when at least one Steam CSS file carries our patch header."""
    css_dir = diretorio_css(steam_path)
    for css_name in PATCH_FILES.values():
        path = css_dir / css_name
        if path.is_file() and _first_line(path) == PATCH_HEADER:
            return True
    return False


def totalmente_instalada(steam_path: "str | Path") -> bool:
    """``True`` when every present patch file carries our header."""
    css_dir = diretorio_css(steam_path)
    found = False
    for css_name in PATCH_FILES.values():
        path = css_dir / css_name
        if not path.is_file():
            continue
        found = True
        if _first_line(path) != PATCH_HEADER:
            return False
    return found
