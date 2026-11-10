# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable UDP loopback fixtures for RetroArch action integration."""

import socket
import threading
import tempfile
from pathlib import Path
import unittest

from cartridges.utils.retroarch_nci import query_status, request_action, request_shader


class FakeRetroArch:
    def __enter__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.settimeout(0.75)
        self.seen = []
        self.running = True
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()
        return self

    def serve(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
            except (socket.timeout, OSError):
                continue
            cmd = data.decode("ascii", errors="replace")
            self.seen.append(cmd)
            if cmd == "GET_STATUS":
                try:
                    self.sock.sendto(b"GET_STATUS PLAYING nes,homebrew,crc32=00000000", addr)
                except OSError:
                    return

    def __exit__(self, *_):
        self.running = False
        self.sock.close()
        self.thread.join(timeout=1)


class RetroArchNetworkTests(unittest.TestCase):
    def test_documented_action_is_localhost_only_and_unverified(self):
        with FakeRetroArch() as emulator:
            state = query_status(emulator.port)
            self.assertTrue(state.available)
            self.assertTrue(state.playing)
            request = request_action("SCREENSHOT", port=emulator.port)
            self.assertTrue(request.sent)
            self.assertEqual(request.feedback, "request_sent_unverified")

    def test_no_remote_address_or_unlisted_command(self):
        for command in ("QUIT", "WRITE_CORE_RAM", "SAVE_STATE;evil", "SET_SHADER", ""):
            with self.subTest(command=command):
                with self.assertRaises(ValueError):
                    request_action(command)

    def test_invalid_port_and_timeout_rejected(self):
        with self.assertRaises(ValueError):
            query_status(80)
        with self.assertRaises(ValueError):
            query_status(True)
        with self.assertRaises(ValueError):
            query_status(55355, timeout=5)

    def test_shaders_accept_only_selected_local_preset(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            preset = root / "crt.slangp"
            preset.write_text("shaders = 1", encoding="utf-8")
            with FakeRetroArch() as emulator:
                response = request_shader(preset, port=emulator.port)
                self.assertTrue(response.sent)
                self.assertEqual(response.feedback, "request_sent_unverified")
            forbidden = root / "malicious;RESET.slangp"
            forbidden.write_text("shaders = 1", encoding="utf-8")
            with self.assertRaises(ValueError):
                request_shader(forbidden)
            with self.assertRaises(ValueError):
                request_shader(root / "does-not-exist.slangp")
            invalid = root / "not-a-preset.txt"
            invalid.write_text("shader = 1", encoding="utf-8")
            with self.assertRaises(ValueError):
                request_shader(invalid)

    def test_no_retroarch_returns_unknown_not_success(self):
        unused = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        unused.bind(("127.0.0.1", 0))
        port = unused.getsockname()[1]
        unused.close()
        state = query_status(port, timeout=0.05)
        self.assertFalse(state.available)
        result = request_action("PAUSE_TOGGLE", port=port, timeout=0.05)
        self.assertFalse(result.sent)


if __name__ == "__main__":
    unittest.main()
