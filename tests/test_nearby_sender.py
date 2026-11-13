# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration tests for an explicit ephemeral Nearby TLS sender."""

import hashlib
import json
import shutil
import socket
import ssl
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from cartridges.utils.nearby_sender import create_sender, serve_sender


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL CLI required for TLS fixture")
class NearbySenderTests(unittest.TestCase):
    def test_manifest_and_file_require_ephemeral_token_and_tls(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rom = root / "homebrew.gba"
            rom.write_bytes(b"owned homebrew test ROM")
            server, temporary, info, _ = create_sender(
                [(rom, "rom")], session_seconds=10,
            )
            self.assertEqual(info.bind_address, "127.0.0.1")
            self.assertEqual(len(info.fingerprint), 64)
            self.assertGreater(len(info.token), 32)

            thread = threading.Thread(
                target=serve_sender,
                args=(server, temporary, time.monotonic() + 3),
                daemon=True,
            )
            thread.start()

            # Fixture manually compares the self-signed certificate before
            # issuing requests. Production Android client must do the same.
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with socket.create_connection(("127.0.0.1", info.port), timeout=2) as raw:
                with ctx.wrap_socket(raw, server_hostname="Jolven Nearby") as peer:
                    digest = hashlib.sha256(peer.getpeercert(binary_form=True)).hexdigest()
                    self.assertEqual(digest, info.fingerprint)

            url = "https://127.0.0.1:" + str(info.port)
            try:
                unauthenticated = urllib.request.Request(url + "/manifest")
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    urllib.request.urlopen(unauthenticated, context=ctx, timeout=2)
                self.assertEqual(denied.exception.code, 403)

                headers = {"Authorization": "Bearer " + info.token}
                for route, expected in [
                    ("/manifest", None), ("/file/0", rom.read_bytes()),
                ]:
                    request = urllib.request.Request(url + route, headers=headers)
                    with urllib.request.urlopen(request, context=ctx, timeout=2) as result:
                        data = result.read()
                    if expected is not None:
                        self.assertEqual(data, expected)
                    else:
                        manifest = json.loads(data)
                        self.assertEqual(manifest["version"], 1)
                        self.assertEqual(manifest["files"][0]["name"], "homebrew.gba")
            finally:
                thread.join(timeout=5)
                if thread.is_alive():
                    server.server_close()
                    temporary.cleanup()

    def test_user_cancel_releases_port_and_removes_ephemeral_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            rom = Path(td) / "homebrew.gba"
            rom.write_bytes(b"homebrew")
            server, temporary, info, deadline = create_sender(
                [(rom, "rom")], session_seconds=30,
            )
            credentials_dir = Path(temporary.name)
            stopped = threading.Event()
            worker = threading.Thread(
                target=serve_sender,
                args=(server, temporary, deadline, stopped), daemon=True,
            )
            worker.start()
            stopped.set()
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive())
            self.assertFalse(credentials_dir.exists())

    def test_rejects_public_bind_address(self):
        with tempfile.TemporaryDirectory() as td:
            rom = Path(td) / "save.srm"
            rom.write_bytes(b"test")
            with self.assertRaises(ValueError):
                create_sender([(rom, "save")], bind_address="8.8.8.8")


if __name__ == "__main__":
    unittest.main()
