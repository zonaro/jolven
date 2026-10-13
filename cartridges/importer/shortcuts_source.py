# shortcuts_source.py
#
# Copyright 2024 kramo
# Copyright 2026 joaomgabaldi
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Windows source that imports game shortcuts (``.lnk`` / ``.url``).

Handles classic ``.lnk`` shortcuts (resolved to their target executable),
``.url`` internet shortcuts (protocol launchers such as ``steam://`` or
``com.epicgames.launcher://``) and ``.lnk`` shortcuts to UWP/Microsoft Store
apps (launched through ``shell:AppsFolder``).

``.lnk`` files are resolved in a single batch through PowerShell's
``WScript.Shell`` and ``Shell.Application`` COM objects, which requires no
third-party Python dependency and is able to read both the target path and the
AppUserModelID needed to launch Store apps.
"""

import configparser
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import NamedTuple, Optional

from cartridges import shared
from cartridges.game import Game
from cartridges.importer.source import Source, SourceIterable, SourceScanError
from cartridges.utils.name_cleaner import clean_game_name


# Match a Steam appid out of a steam:// launch URL.
_STEAM_APPID_RE = re.compile(r"steam://(?:rungameid|run)/(\d+)", re.IGNORECASE)

# Characters that must never reach a double-quoted cmd.exe argument: a quote
# would close the quoting and let metacharacters (&, |, >) inject commands; the
# same goes for control characters (new lines split commands).
_UNSAFE_CMD_CHARS_RE = re.compile(r'["\x00-\x1f]')

# Characters cmd.exe acts on when they appear outside quotes: command chaining
# and grouping (`&`, `|`, `(`, `)`), redirection (`<`, `>`) and the escape
# prefix (`^`). Inside a quoted run cmd takes them literally — see
# :func:`args_safe`.
_SHELL_METACHARS = frozenset("&|<>^()")

# Characters refused in arguments whether quoted or not: control characters
# (a line break ends the command), `%` (variable expansion happens *inside*
# quotes too, before any quoting is looked at) and `!` (the same expansion when
# delayed expansion is on — off by default, but a registry value away).
_ARGS_ALWAYS_UNSAFE_RE = re.compile(r"[\x00-\x1f%!]")

# A target that names a file on a drive or a UNC share. Such a target is a file
# path even when the file is missing right now (drive unplugged, share offline),
# and must keep the file-path identity and command — see `build_from_lnk`.
_ABSOLUTE_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]{2}[^\\/])")


def cmd_safe(value: str) -> bool:
    """Whether ``value`` can be embedded inside a double-quoted cmd.exe argument.

    Launch commands run through ``shell=True``. Shortcut files are plain data a
    user may have downloaded, so a crafted URL/target must not be able to break
    out of its quoting and execute arbitrary commands.
    """
    return not _UNSAFE_CMD_CHARS_RE.search(value)


def args_safe(value: str) -> bool:
    """Whether ``value`` can be appended *unquoted* to a cmd.exe command line.

    A shortcut's argument string cannot simply be wrapped in quotes — the game
    would then receive the whole thing as one argument instead of several — so
    it is concatenated raw, and this is the security boundary for it: outside
    quotes, `&`, `|`, `<`, `>`, `^`, `(` and `)` are interpreted by the shell,
    and any one of them turns a shortcut into a command of the attacker's
    choosing.

    Refusing every quote (the old rule) also refused real launchers: GOG's
    ``/path="D:\\GOG Games\\X"``, Battle.net's ``--exec="launch Pro"``, an
    emulator's ``"...\\Game (USA).sfc"``. So the text is walked the way cmd.exe
    walks it — every ``"`` toggles quoting, with no escape for it — and a
    metacharacter is accepted only while a quoted run is open. The quotes must
    balance, so the run cannot spill into anything appended later. `%`, `!`
    and control characters are refused everywhere (see
    ``_ARGS_ALWAYS_UNSAFE_RE``).

    The rest of the command (``start "" /D "..." "..."``) always has balanced
    quotes, so the parity here is the parity cmd sees.
    """
    if _ARGS_ALWAYS_UNSAFE_RE.search(value):
        return False
    quoted = False
    for char in value:
        if char == '"':
            quoted = not quoted
        elif not quoted and char in _SHELL_METACHARS:
            return False
    return not quoted


# Names that are clearly not games and pollute shortcut folders. "Manual",
# "Support" and "Benchmark" only as the last word ("Halo Manual"): anywhere in
# the name they also took real games ("Manual Samuel", "Tech Support: Error
# Unknown").
_SKIP_NAME_RE = re.compile(
    r"\b(uninstall|uninstaller|readme|read me|website|home\s*page)\b"
    r"|\b(manual|support|benchmark)\s*$",
    re.IGNORECASE,
)


def steam_appid_from_url(value: str) -> Optional[str]:
    """Return a plain Steam appid from a launch URL, if present.

    ``rungameid`` can encode a 64-bit composite id for mods/non-Steam
    shortcuts; only plain appids (kept short) are returned.
    """
    if not value:
        return None
    match = _STEAM_APPID_RE.search(value)
    if not match:
        return None
    appid = match.group(1)
    return appid if len(appid) <= 7 else None


def resolve_lnk_targets(paths: list[Path]) -> dict[str, dict]:
    """Resolve a batch of ``.lnk`` files via PowerShell COM.

    Returns a mapping of ``str(path)`` to a dict with ``Target``,
    ``Arguments``, ``Icon``, ``WorkingDirectory`` and ``Aumid`` keys.
    """
    if sys.platform != "win32":
        return {}
    if not paths:
        return {}

    list_file = Path(tempfile.gettempdir()) / f"jolven_lnks_{os.getpid()}.txt"
    list_file.write_text("\n".join(str(path) for path in paths), encoding="utf-8")

    # Results are emitted through the pipeline and collected once: the previous
    # `$out += ...` pattern copies the whole array per item (O(n²) for big
    # shortcut folders).
    # fmt: off
    script = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        "$ErrorActionPreference='SilentlyContinue';"
        "$wsh=New-Object -ComObject WScript.Shell;"
        "$shell=New-Object -ComObject Shell.Application;"
        f"$res=@(Get-Content -LiteralPath $env:JOLVEN_LNK_LIST -Encoding UTF8 | ForEach-Object {{"
        "  $p=[string]$_; if([string]::IsNullOrWhiteSpace($p)){return};"
        "  $sc=$wsh.CreateShortcut($p); $aumid='';"
        "  try{"
        # `.Replace`, not `-replace`: the latter is a regex and a lone backslash
        # in its replacement is an escape. The separator swap matters because
        # the shell namespace parser is stricter than the file APIs — the same
        # path that `CreateShortcut` opens happily returns a null namespace here
        # if it carries forward slashes, and the ucrt64 Python this ships with
        # produces exactly that. A null namespace means no AUMID, which means no
        # Store or Game Pass shortcut is recognised as one at all: they lose
        # their only usable target, get dropped, and `remove_games` then clears
        # every Game Pass game in the library. Fixed on the PowerShell side so
        # `File=$p` keeps echoing the path exactly as written, which is what
        # `lnk_data` is keyed by.
        "    $ns=$shell.Namespace(((Split-Path $p).Replace('/','\\')));"
        "    if($ns){$it=$ns.ParseName((Split-Path $p -Leaf));"
        "      if($it){$aumid=$it.ExtendedProperty('System.AppUserModel.ID')}}"
        "  }catch{};"
        "  [PSCustomObject]@{File=$p;Target=$sc.TargetPath;"
        "    Arguments=$sc.Arguments;Icon=$sc.IconLocation;"
        "    WorkingDirectory=$sc.WorkingDirectory;Aumid=$aumid}"
        "});"
        "$res | ConvertTo-Json -Compress"
    )
    # fmt: on

    # Pass the list path through the environment instead of embedding it in the
    # script text, so a path containing quotes or other special characters can't
    # break (or be injected into) the PowerShell command.
    env = {**os.environ, "JOLVEN_LNK_LIST": str(list_file)}

    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            timeout=180,
            check=False,
            env=env,
            # Avoid flashing a console window when launched from the GUI
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = proc.stdout.decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError) as error:
        logging.warning("Could not resolve .lnk shortcuts: %s", error)
        return {}
    finally:
        list_file.unlink(missing_ok=True)

    if not out:
        return {}

    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        logging.warning("Unexpected PowerShell output while resolving shortcuts")
        return {}

    if isinstance(data, dict):  # ConvertTo-Json unwraps single-element arrays
        data = [data]

    return {
        item["File"]: item
        for item in data
        if isinstance(item, dict) and item.get("File")
    }


def resolve_start_apps() -> list[tuple[str, str]]:
    """Return ``(display name, launch AUMID)`` for every installed Start app.

    Xbox/Store ``.lnk`` files carry a ``System.AppUserModel.ID`` that is only a
    taskbar-grouping id (e.g. ``XboxGames.<pkg>_<app>``), which
    ``shell:AppsFolder`` cannot launch — it just opens the Apps folder. The real
    launch id comes from ``Get-StartApps``, matched against the shortcut.
    """
    if sys.platform != "win32":
        return []
    script = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            timeout=60,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = proc.stdout.decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError) as error:
        logging.warning("Could not list Start apps: %s", error)
        return []

    if not out:
        return []

    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []

    if isinstance(data, dict):  # ConvertTo-Json unwraps single-element arrays
        data = [data]

    return [
        (item["Name"], item["AppID"])
        for item in data
        if isinstance(item, dict) and item.get("Name") and item.get("AppID")
    ]


# GSettings keys for the shortcuts folder. Read directly: the keys are part
# of the schema, so no `list_keys()` dance is needed.
_SHORTCUTS_LOCATION_KEY = "shortcuts-location"
_SHORTCUTS_RECURSIVE_KEY = "shortcuts-recursive"


def _windows_default_folders() -> list[Path]:
    """Well-known Windows folders scanned when no folder is configured.

    Per-user and all-users Start Menu Programs plus the per-user Desktop,
    derived from the environment with `Path.home()` fallbacks. The registry
    is never consulted (no winreg dependency).
    """
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
    program_data = Path(os.environ.get("ProgramData") or r"C:\ProgramData")
    user_profile = Path(os.environ.get("USERPROFILE") or home)
    start_menu = Path("Microsoft") / "Windows" / "Start Menu" / "Programs"
    return [
        appdata / start_menu,
        program_data / start_menu,
        user_profile / "Desktop",
    ]


def _shortcuts_folder_candidates() -> list[Path]:
    """Candidate roots for the shortcuts scan, in preference order.

    THE one place for the default-folder policy: the configured folder wins
    when non-blank; otherwise, on Windows, the well-known folders above are
    used. Off Windows the list is empty (`is_available` is False there
    anyway), and the schema is never touched, so the module keeps importing
    cleanly on Linux.
    """
    if sys.platform != "win32":
        return []
    location = (shared.schema.get_string(_SHORTCUTS_LOCATION_KEY) or "").strip()
    if location:
        return [Path(location).expanduser()]
    return _windows_default_folders()


def _shortcuts_recursive() -> bool:
    """Whether the scan descends into subfolders (default off)."""
    if sys.platform != "win32":
        return False
    return shared.schema.get_boolean(_SHORTCUTS_RECURSIVE_KEY)


def atalhos_da_pasta() -> list[Path]:
    """Os ``.lnk`` e ``.url`` das pastas de atalhos, com ou sem subpastas
    conforme a preferência. Lista vazia se nenhuma pasta existir.

    Compartilhada pela varredura e pela janela de pendências da restauração,
    que precisa oferecer exatamente os atalhos que a importação enxerga.
    """
    roots = [root for root in _shortcuts_folder_candidates() if root.is_dir()]
    if not roots:
        return []

    recursive = _shortcuts_recursive()
    entries: list[Path] = []
    for root in roots:
        if recursive:
            # os.walk, not rglob: rglob descends into NTFS junctions (creatable
            # without admin rights), and one looping back to a parent repeated
            # every shortcut dozens of times. os.walk already skips symlinks;
            # junctions are pruned here, as `install_size.folder_size` does.
            # (os.path.isjunction runs here, at scan time — never at import.)
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [
                    d
                    for d in dirnames
                    if not os.path.isjunction(os.path.join(dirpath, d))
                ]
                entries += (Path(dirpath, filename) for filename in filenames)
        else:
            entries.extend(root.glob("*"))

    return [
        entry
        for entry in entries
        if entry.is_file() and entry.suffix.lower() in (".lnk", ".url")
    ]


class ShortcutsSourceIterable(SourceIterable):
    source: "ShortcutsSource"

    def __init__(self, source: "ShortcutsSource") -> None:
        super().__init__(source)
        self._aumid_by_name: dict[str, str] = {}
        self._aumid_by_pkgkey: dict[str, str] = {}

    def __iter__(self):
        """Generator method producing games from shortcut files.

        A pasta existir já é checado antes (`ShortcutsSource.is_available`);
        `atalhos_da_pasta` devolve lista vazia se ela sumir no meio."""

        url_files: list[Path] = []
        lnk_files: list[Path] = []
        for entry in atalhos_da_pasta():
            if entry.suffix.lower() == ".url":
                url_files.append(entry)
            else:
                lnk_files.append(entry)

        # The `.url` shortcuts first, deliberately: they are parsed here, in
        # process, and cannot be taken down by the PowerShell failures guarded
        # below. Yielding them before the risky part means a scan that has to
        # give up still counts every game it did manage to see.
        for entry in url_files:
            yield self.build_from_url(entry)

        lnk_data = resolve_lnk_targets(lnk_files)
        # An empty result for a non-empty batch is a failure, not a folder
        # without shortcuts: `resolve_lnk_targets` returns {} for a missing
        # PowerShell, a blocked execution policy and a timed-out batch alike.
        # Treated as "no games", it used to mark every .lnk game as removed —
        # permanently, since coming back needs the shortcut's mtime to rise and
        # nothing touched the files. The `.url` games (Steam, Epic) are resolved
        # separately and kept reporting fine, so a guard on the source producing
        # nothing at all would never have caught this: the batch is what failed,
        # so the batch is what has to be checked.
        if lnk_files and not lnk_data:
            raise SourceScanError(
                _("Não foi possível ler os atalhos"),
                _(
                    "O Windows não conseguiu resolver os atalhos (.lnk) da pasta. "
                    "Verifique se o PowerShell está disponível e tente importar novamente."
                ),
            )

        # Map shortcut grouping AUMIDs to real, launchable ones (Xbox/Store).
        # Get-StartApps spawns a whole PowerShell (1-3 s), so only pay for it
        # when at least one shortcut actually carries an AUMID (UWP/Store app).
        needs_start_apps = any(
            (item.get("Aumid") or "").strip() for item in lnk_data.values()
        )
        start_apps = resolve_start_apps() if needs_start_apps else []
        # Same reasoning as above, and it matters more here: a machine with
        # Store shortcuts always has Start apps, so an empty list means the
        # lookup broke (its own 60 s timeout, most likely).
        #
        # What carrying on would cost is worth being exact about, because the
        # obvious answer stopped being true. It is no longer that the games get
        # an unlaunchable command — the fallback below launches the shortcut
        # itself, which works. It is that every Xbox and Game Pass game (the
        # ones whose shortcut carries a grouping id and so needs resolving at
        # all) would be *written* down to that fallback.
        if needs_start_apps and not start_apps:
            raise SourceScanError(
                _("Não foi possível ler os aplicativos do menu Iniciar"),
                _(
                    "O problema afeta jogos da Microsoft Store e do Game Pass. "
                    "Verifique se o PowerShell está disponível e tente importar "
                    "novamente."
                ),
            )
        self._aumid_by_name = {name.casefold(): appid for name, appid in start_apps}
        self._aumid_by_pkgkey = {}
        for _name, appid in start_apps:
            # "<pkgname>_<hash>!<app>" -> key "<pkgname>_<app>"
            if "!" in appid and "_" in (pfn := appid.split("!", 1)[0]):
                pkgname = pfn.rsplit("_", 1)[0]
                self._aumid_by_pkgkey[f"{pkgname}_{appid.split('!', 1)[1]}".casefold()] = (
                    appid
                )

        for entry in lnk_files:
            yield self.build_from_lnk(entry, lnk_data.get(str(entry)))

    def build_from_url(self, entry: Path):
        """Build a game from a ``.url`` internet shortcut"""
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            raw = entry.read_bytes()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                # Windows writes .url files in the ANSI code page, not UTF-8: an
                # accented IconFile path made the whole file unreadable, and a
                # game already in the library was then marked removed.
                text = raw.decode("mbcs")
            parser.read_string(text)
        except (configparser.Error, OSError, UnicodeDecodeError, LookupError) as error:
            logging.warning("Unreadable internet shortcut %s: %s", entry.name, error)
            return None

        if not parser.has_section("InternetShortcut"):
            return None

        url = parser.get("InternetShortcut", "URL", fallback="").strip()
        if not url or url.lower().startswith(("http://", "https://")):
            # Plain web bookmarks are not games
            return None

        # Security: the URL is embedded in a cmd.exe command; refuse anything
        # that could escape its quoting (command injection via a crafted .url)
        if not cmd_safe(url):
            logging.warning("Ignoring unsafe URL in shortcut %s", entry)
            return None

        name = clean_game_name(entry.stem)
        if _SKIP_NAME_RE.search(name):
            return None

        additional_data: dict = {}
        if appid := steam_appid_from_url(url):
            additional_data["steam_appid"] = appid
        # Same reasoning as the .lnk branch: the file is the stable thing, the
        # URL inside it is not. A launcher re-issuing its URI scheme, or an Epic
        # shortcut rewritten with a new catalog id, renames the game exactly the
        # way a patched target does.
        additional_data["identity_anchor"] = str(entry)

        return (
            self._make_game(
                name, f'start "" "{url}"', url, self._mtime(entry), str(entry)
            ),
            additional_data,
        )

    def build_from_lnk(self, entry: Path, data: Optional[dict]):
        """Build a game from a ``.lnk`` shortcut using resolved COM data"""
        name = clean_game_name(entry.stem)
        if _SKIP_NAME_RE.search(name):
            return None

        if not data:
            logging.debug("Could not resolve shortcut %s", entry)
            return None

        target = (data.get("Target") or "").strip()
        arguments = (data.get("Arguments") or "").strip()
        workdir = (data.get("WorkingDirectory") or "").strip()
        aumid = (data.get("Aumid") or "").strip()

        additional_data: dict = {}

        # Security: target and workdir are embedded in quoted cmd.exe arguments.
        # Windows paths can't legitimately contain quotes/control chars, so any
        # value that does is malicious or corrupt — skip the shortcut entirely.
        #
        # `arguments` is checked with them, and it is the one that actually
        # mattered: unlike the other two it is appended to the command *unquoted*
        # (a quoted argument string would be passed to the game as a single
        # argument), so it needed no quote to break out at all. A .lnk carrying
        # `Arguments = & calc.exe` produced `start "" "game.exe" & calc.exe`,
        # which `run_executable` hands straight to `shell=True` — arbitrary code
        # execution from a shortcut file the user only had to drop in the
        # scanned folder. The stricter rule below also rejects the shell
        # metacharacters that are harmless inside quotes but not outside them.
        if not cmd_safe(target) or not cmd_safe(workdir):
            logging.warning("Ignoring shortcut with unsafe target: %s", entry)
            return None

        if arguments and not args_safe(arguments):
            logging.warning("Ignoring shortcut with unsafe arguments: %s", entry)
            return None

        # A target that looks like a file path is one even while the file is
        # missing — a game on a USB drive that is unplugged during the scan.
        # Sent to the URI branch below, it hashed a different identity (`target`
        # without `|arguments`), so the game's id changed, the anchor adopted the
        # old record and replaced its command with a poorer one (no /D, no
        # arguments) — losing any command the user had edited — and the id moved
        # again when the drive came back. Only a missing path is caught here: an
        # existing folder target keeps the branch it always had, and a packaged
        # app's target (WindowsApps, unreadable) still goes to the AUMID branch.
        is_path = target and Path(target).suffix.lower() != ".lnk"
        if is_path and (
            Path(target).is_file()
            or (
                not aumid
                and _ABSOLUTE_PATH_RE.match(target)
                and not Path(target).exists()
            )
        ):
            # Classic executable target
            executable = 'start ""'
            if workdir:
                executable += f' /D "{workdir}"'
            executable += f' "{target}"'
            if arguments:
                executable += f" {arguments}"
            identity = f"{target}|{arguments}"
            if appid := (
                steam_appid_from_url(arguments) or steam_appid_from_url(target)
            ):
                additional_data["steam_appid"] = appid

        elif aumid:
            # UWP / Microsoft Store app.
            #
            # The identity is the AUMID *as the shortcut carries it*, never the
            # resolved one below. Resolution goes through Get-StartApps, and a
            # game_id must not depend on anything that can fail: a PowerShell
            # timeout changed the id, so the game looked new and its old record
            # looked missing, and `remove_games` took the playtime, cover, logo
            # and update tracking with it — permanently, because coming back
            # needs the shortcut's mtime to rise and the file was never touched.
            # The resolved AUMID is a launch detail, and belongs in the command.
            launch_aumid = self._real_aumid(entry.stem, aumid)
            identity = f"uwp:{aumid}"
            # Security: the AUMID lands unquoted in a shell command; real ones
            # only use word chars plus ".", "!", "+" and "-" (PFN!AppId form)
            if not re.fullmatch(r"[\w.!+\-]+", launch_aumid):
                logging.warning("Ignoring shortcut with unsafe AUMID: %s", entry)
                return None
            if "!" in launch_aumid:
                executable = f"explorer.exe shell:AppsFolder\\{launch_aumid}"
            elif cmd_safe(str(entry)):
                # A grouping id with no "!" is not launchable — `shell:AppsFolder`
                # just opens the Apps folder with it, which looks like a game
                # that starts and immediately does nothing. Launch the shortcut
                # itself instead: it is what the user would double-click, and
                # the shell knows what to do with it. Losing the AUMID here also
                # keeps the game out of the packaged playtime path, which had
                # nothing to watch for anyway.
                logging.info("No launchable AUMID for %s; using the shortcut", entry)
                executable = f'start "" "{entry}"'
            else:
                logging.warning("Ignoring shortcut with unsafe path: %s", entry)
                return None

        elif target:
            # A protocol/URI target (e.g. steam://), or a relative path or folder
            # (cmd_safe was already enforced on `target` above)
            if target.lower().startswith(("http://", "https://")):
                return None
            executable = f'start "" "{target}"'
            identity = target
            if appid := steam_appid_from_url(target):
                additional_data["steam_appid"] = appid

        else:
            logging.debug("Shortcut %s has no usable target", entry)
            return None

        # Let the store match on the shortcut file, for every shortcut and not
        # only the packaged ones it was first added for.
        #
        # A classic shortcut hashes `target|arguments`, so anything that edits
        # where the .lnk points — installing a patch, a launcher moving its
        # executable, the game reinstalled elsewhere — renames the game. The
        # file in the scanned folder did not change, but the id derived from it
        # did, so the scan reported a new game plus a missing one and
        # `remove_games` took the playtime, cover, logo and update tracking with
        # it. The shortcut file is what the user actually curates; the target is
        # a launch detail, and a launch detail must not be able to delete a
        # library.
        #
        # Note which half of the problem this covers. A *renamed* shortcut needs
        # nothing from the anchor: the identity does not include the file name,
        # so the id survives and the duplicate branch follows the new path. The
        # two signals move independently, and each one is what repairs the
        # other — the anchor is the direction that had no repair at all.
        additional_data["identity_anchor"] = str(entry)

        return (
            self._make_game(
                name, executable, identity, self._mtime(entry), str(entry)
            ),
            additional_data,
        )

    def _real_aumid(self, name: str, aumid: str) -> str:
        """Resolve a shortcut's AUMID to a launchable one via the Start apps.

        Xbox/Game Pass shortcuts expose a grouping id that ``shell:AppsFolder``
        can't launch. Prefer a Start app with the same display name; failing
        that, match by package identity (grouping ids lack the ``!`` of a real
        AUMID). Falls back to the original value when nothing matches.
        """
        if real := self._aumid_by_name.get(name.casefold()):
            return real

        if "!" not in aumid:  # looks like a non-launchable grouping id
            candidates = [aumid.casefold()]
            if "." in aumid:  # drop a leading vendor segment, e.g. "XboxGames."
                candidates.append(aumid.split(".", 1)[1].casefold())
            for candidate in candidates:
                if real := self._aumid_by_pkgkey.get(candidate):
                    return real

        return aumid

    def _game_id(self, identity: str) -> str:
        """The game id a launch identity hashes to."""
        digest = sha256(identity.encode("utf-8")).hexdigest()[:16]
        return self.source.game_id_format.format(game_id=digest)

    @staticmethod
    def _mtime(entry: Path) -> int:
        """Shortcut file modification time, used to detect reinstalls"""
        try:
            return int(entry.stat().st_mtime)
        except OSError:
            return 0

    def _make_game(
        self,
        name: str,
        executable: str,
        identity: str,
        mtime: int = 0,
        shortcut_path: str = "",
    ) -> Game:
        """Create a Game with a stable id derived from its launch identity"""
        # Risco arquitetural aceito, herdado do upstream: isto roda na worker
        # thread do import, e Game é um Gtk.Box — o __init__ instancia template
        # e controllers fora da main thread. Verificado no runtime real que o
        # GtkBuilder preserva o __init__ e que a construção fora da thread é
        # tolerada; o widget só é PARENTEADO na main (DisplayManager marshalla).
        # Mover a construção para a main custaria refazer o fluxo do importer
        # inteiro por um defeito nunca observado — fica registrado, não refeito.
        return Game(
            {
                "source": self.source.source_id,
                "added": shared.import_time,
                "name": name,
                "game_id": self._game_id(identity),
                "executable": executable,
                "shortcut_mtime": mtime,
                "shortcut_path": shortcut_path,
            }
        )


class ShortcutsLocations(NamedTuple):
    """Location set for the shortcuts source — intentionally empty.

    The shortcuts folder policy (configured folder, else the Windows
    well-known folders) lives in `_shortcuts_folder_candidates()`, a plain
    helper both the scan and `is_available` go through, instead of `Location`
    objects: `Location.resolve()` writes the picked candidate back into its
    schema key, which would clobber a blank `shortcuts-location` with a
    fallback path.
    """


class ShortcutsSource(Source):
    """Source importing ``.lnk`` and ``.url`` game shortcuts on Windows"""

    source_id = "shortcuts"
    name = _("Atalhos")
    available_on = {"win32"}
    iterable_class = ShortcutsSourceIterable

    locations: ShortcutsLocations

    def __init__(self) -> None:
        super().__init__()
        self.locations = ShortcutsLocations()

    @property
    def is_available(self) -> bool:
        """Available only on Windows and when a shortcuts folder exists.

        A missing folder (unset setting, disconnected drive) must skip the
        scan entirely: an "empty" scan would otherwise mark every previously
        imported game as removed.
        """
        if not super().is_available:
            return False
        return any(root.is_dir() for root in _shortcuts_folder_candidates())
