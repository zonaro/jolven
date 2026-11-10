# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in, localhost-only RetroArch Network Control Interface adapter.

RetroArch must have Network Commands enabled by its owner. This module
never changes retroarch.cfg, connects to remote hosts, or captures inputs.
Sending a UDP packet acknowledges *transmission*, not the emulated action.
"""

from __future__ import annotations

import socket
from pathlib import Path
from dataclasses import dataclass


DEFAULT_PORT = 55355
_MAX_REPLY = 1024
_ALLOWED_COMMANDS = frozenset({
    "MENU_TOGGLE",
    "PAUSE_TOGGLE",
    "RESET",
    "SCREENSHOT",
    "FAST_FORWARD",
    "SLOWMOTION",
    "MUTE",
    "VOLUME_UP",
    "VOLUME_DOWN",
    "FULLSCREEN_TOGGLE",
    "SAVE_STATE",
    "LOAD_STATE",
    "STATE_SLOT_PLUS",
    "STATE_SLOT_MINUS",
})


@dataclass(frozen=True)
class RetroArchRuntime:
    available: bool
    playing: bool
    paused: bool
    status: str


@dataclass(frozen=True)
class CommandRequest:
    sent: bool
    command: str
    feedback: str


def _validate_port(port: int) -> int:
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("Invalid local RetroArch command port")
    return port


def _exchange(
    command: str, port: int, *, timeout: float = 0.35,
    expect_reply: bool = True
) -> tuple[bool, str]:
    """Send UDP only to loopback; never derive the destination from input."""
    _validate_port(port)
    if not 0.05 <= timeout <= 2:
        raise ValueError("Invalid command timeout")
    if (not isinstance(command, str) or not command.isascii() or
            not 1 <= len(command) <= 2048 or
            any(char in command for char in (";", chr(10), chr(13), chr(0)))):
        raise ValueError("Invalid command")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(timeout)
        client.sendto(command.encode("ascii"), ("127.0.0.1", port))
        if not expect_reply:
            return True, ""
        try:
            response, source = client.recvfrom(_MAX_REPLY)
        except socket.timeout:
            return True, ""
        # The endpoint is local and responses may still come from another
        # process on localhost; don't treat a response as authentication.
        if source != ("127.0.0.1", port):
            return True, ""
        return True, response.decode("utf-8", errors="replace").strip()


def query_status(port: int = DEFAULT_PORT, *, timeout: float = 0.35) -> RetroArchRuntime:
    """Return unavailable rather than guessing the state of the core."""
    try:
        _, response = _exchange("GET_STATUS", port, timeout=timeout)
    except OSError:
        return RetroArchRuntime(False, False, False, "unreachable")
    if response == "GET_STATUS CONTENTLESS":
        return RetroArchRuntime(True, False, False, "contentless")
    if response.startswith("GET_STATUS PAUSED"):
        return RetroArchRuntime(True, True, True, "paused")
    if response.startswith("GET_STATUS PLAYING"):
        return RetroArchRuntime(True, True, False, "playing")
    return RetroArchRuntime(False, False, False, "unverified")


def request_action(
    command: str, *, port: int = DEFAULT_PORT,
    timeout: float = 0.35,
    require_playing: bool = True,
) -> CommandRequest:
    """Request a documented command, not a confirmed in-game operation.

    An explicit action selection is required by the caller. No arbitrary
    string parameters, configuration commands, or core RAM access allowed.
    """
    if command not in _ALLOWED_COMMANDS:
        raise ValueError("RetroArch command is not approved")
    runtime = query_status(port, timeout=timeout)
    if not runtime.available:
        return CommandRequest(False, command, "network_interface_unverified")
    if require_playing and not runtime.playing:
        return CommandRequest(False, command, "no_active_game")
    try:
        sent, _ = _exchange(command, port, timeout=timeout, expect_reply=False)
    except OSError:
        return CommandRequest(False, command, "transmission_failed")
    return CommandRequest(sent, command, "request_sent_unverified")

def request_shader(
    shader_file: Path, *, port: int = DEFAULT_PORT, timeout: float = 0.35,
) -> CommandRequest:
    """Ask the user's external RetroArch to load a selected shader preset.

    The caller must explicitly select a local preset. Do not read arbitrary
    config text, send multiple commands, or claim the core accepted the
    shader. This never mutates Jolven or RetroArch global settings.
    """
    raw = Path(shader_file).expanduser()
    if not raw.is_absolute() or raw.is_symlink() or not raw.is_file():
        raise ValueError("Select an existing non-symlink shader preset")
    if raw.suffix.lower() not in {".slangp", ".glslp", ".cgp"}:
        raise ValueError("Unsupported shader preset format")
    if raw.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Shader preset exceeds 4 MiB")
    path = str(raw.resolve(strict=True))
    if (not path.isascii() or len(path) > 2000 or
            any(char in path for char in (";", chr(10), chr(13), chr(0)))):
        raise ValueError("Unsafe shader path")
    state = query_status(port, timeout=timeout)
    if not state.available or not state.playing:
        return CommandRequest(False, "SET_SHADER", "no_verified_active_game")
    try:
        sent, _ = _exchange(
            "SET_SHADER " + path, port, timeout=timeout, expect_reply=False,
        )
    except OSError:
        return CommandRequest(False, "SET_SHADER", "transmission_failed")
    return CommandRequest(sent, "SET_SHADER", "request_sent_unverified")
