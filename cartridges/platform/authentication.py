# authentication.py
#
# Copyright 2026 Jolven contributors
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

"""Gate that requires user authentication before opening Preferences.

Low-level Linux/polkit module: **no ``gi`` import here**. The blocking
`authenticate` call belongs in a worker thread, never in GTK main loop.

Decided degradation policy:

- Fail OPEN (``UNAVAILABLE``) only when the system cannot present the
  prompt: the polkit policy for our action is not installed, ``pkcheck``
  is missing, exit ``2`` (no authentication agent available), or an exit
  code that cannot be interpreted (``126``, ``127``, negative, unknown).
- Fail CLOSED (``DENIED``) when the system asked and did not get a yes:
  exit ``1`` (not authorized), exit ``3`` (user dismissed the dialog),
  and a timeout of a prompt that was actually shown.

Rationale: user-local builds (``~/.local``) never install the polkit
policy, so that case must not lock the user out of Preferences; but a
prompt that was shown and
not answered must not open the dialog. Callers block on ``DENIED`` and
fail open on ``UNAVAILABLE``.
"""

from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Iterable
from enum import Enum
from pathlib import Path

from cartridges.platform import system_integration

AUTH_ACTION_ID = "io.github.zonaro.Jolven.preferences"

# Fonte única dos diretórios de policy: os mesmos que o polkitd lê (ver
# `system_integration.POLKIT_ACTION_DIRS`). Mantido como alias para
# compatibilidade; `policy_installed` lê a fonte viva em cada chamada para
# acompanhar substituições em teste.
POLICY_SEARCH_DIRS = system_integration.POLKIT_ACTION_DIRS

PKCHECK_TIMEOUT = 120.0

__all__ = [
    "AUTH_ACTION_ID",
    "AuthOutcome",
    "authenticate",
    "outcome_from_exit_code",
    "parse_proc_stat_starttime",
    "pkcheck_argv",
    "policy_installed",
    "process_subject",
    "read_process_starttime",
    "current_process_subject",
]


class AuthOutcome(Enum):
    AUTHORIZED = "authorized"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"


def outcome_from_exit_code(returncode: int) -> AuthOutcome:
    """Map a ``pkcheck`` exit code to an outcome (single pure mapping).

    ``0`` authorized (including via ``auth_admin_keep`` temporary
    authorization); ``1`` not authorized and ``3`` user dismissed the
    dialog are ``DENIED``. Everything else — ``2`` (no authentication
    agent available), ``126`` (malformed options / authority
    unavailable), ``127`` (polkit D-Bus error), negative or unknown
    codes — is ``UNAVAILABLE`` (fail-open: the system could not ask).
    A timeout of a shown prompt is handled by the caller as ``DENIED``,
    not here.
    """
    if returncode == 0:
        return AuthOutcome.AUTHORIZED
    if returncode in (1, 3):
        return AuthOutcome.DENIED
    return AuthOutcome.UNAVAILABLE


def policy_installed(search_dirs: Iterable[str | Path] | None = None) -> bool:
    """Whether a polkit policy for ``AUTH_ACTION_ID`` is installed (pure).

    Globs ``*.policy`` under the system policy directories and reports
    True when any file mentions our action id. User-local builds
    (``~/.local``) never install the policy, so this is False there and
    the gate fails open instead of locking the user out of Preferences.
    ``search_dirs`` exists so tests can point at a temporary directory.
    When omitted, the directories come from
    ``system_integration.POLKIT_ACTION_DIRS`` (single source shared with
    the privileged-helper resolution).
    """
    dirs = (
        [Path(d) for d in search_dirs]
        if search_dirs is not None
        else list(system_integration.POLKIT_ACTION_DIRS)
    )
    for directory in dirs:
        try:
            candidates = sorted(directory.glob("*.policy"))
        except OSError:
            continue
        for candidate in candidates:
            try:
                if AUTH_ACTION_ID in candidate.read_text(encoding="utf-8"):
                    return True
            except (OSError, UnicodeDecodeError):
                continue
    return False


def process_subject(pid: int, uid: int, starttime: int) -> str:
    """Format the polkit subject tuple as ``pkcheck --process`` expects."""
    return f"{pid},{starttime},{uid}"


def pkcheck_argv(action_id: str, subject: str) -> list[str]:
    """Build the ``pkcheck`` argv (pure; no process is spawned)."""
    return [
        "pkcheck",
        "--action-id",
        action_id,
        "--process",
        subject,
        "--allow-user-interaction",
    ]


def parse_proc_stat_starttime(stat_text: str) -> int:
    """Extract field 22 (starttime) from a ``/proc/<pid>/stat`` line.

    Field 2 (``comm``) may itself contain spaces and parentheses, so the
    line is split after the LAST ``)``; field 3 (state) is then element 0
    of the remainder and starttime (field 22) is element 19.
    """
    closing = stat_text.rfind(")")
    if closing == -1:
        raise ValueError("malformed stat line: no closing parenthesis")
    rest = stat_text[closing + 1 :].split()
    if len(rest) < 20:
        raise ValueError("malformed stat line: too few fields")
    return int(rest[19])


def read_process_starttime(pid: int) -> int | None:
    """Read the starttime of ``pid`` from ``/proc``; ``None`` on any error."""
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return parse_proc_stat_starttime(text)
    except (ValueError, IndexError):
        return None


def current_process_subject() -> str | None:
    """Subject string for this process; ``None`` when it cannot be built."""
    try:
        pid = os.getpid()
        uid = os.getuid()
    except (AttributeError, OSError):
        return None
    starttime = read_process_starttime(pid)
    if starttime is None:
        return None
    return process_subject(pid, uid, starttime)


def _authenticate_linux() -> AuthOutcome:
    # Fail OPEN only when the system cannot present the prompt: user-local
    # builds (~/.local) never install the polkit policy, so asking there
    # would always fail and lock the user out of Preferences entirely.
    if not policy_installed():
        logging.warning("Preferences auth unavailable: policy not installed")
        return AuthOutcome.UNAVAILABLE
    subject = current_process_subject()
    if subject is None:
        logging.warning("Preferences auth unavailable: no polkit subject")
        return AuthOutcome.UNAVAILABLE
    argv = pkcheck_argv(AUTH_ACTION_ID, subject)
    try:
        completed = subprocess.run(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=PKCHECK_TIMEOUT,
            check=False,
        )
    except FileNotFoundError:
        logging.warning("Preferences auth unavailable: pkcheck not installed")
        return AuthOutcome.UNAVAILABLE
    except subprocess.TimeoutExpired:
        # Fail CLOSED: the prompt was shown and got no yes — staying
        # silent must not defeat the gate.
        logging.warning("Preferences auth timed out without approval")
        return AuthOutcome.DENIED
    except OSError:
        logging.warning("Preferences auth check could not run")
        return AuthOutcome.UNAVAILABLE
    return outcome_from_exit_code(completed.returncode)


def authenticate(motivo: str) -> AuthOutcome:
    """Check Linux/polkit authorization; call from a worker thread.

    The action's system policy owns the prompt text. No user input is logged.
    """
    try:
        return _authenticate_linux()
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Preferences auth check failed; integration unavailable")
        return AuthOutcome.UNAVAILABLE
