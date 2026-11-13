# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration tests for explicit, consent-based Nearby receive sessions."""

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

from cartridges.utils.nearby_manifest import create_manifest
from cartridges.utils.nearby_receiver import create_receiver, serve_receiver


def post(url, token, payload, context):
    request = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/octet-stream"},
    )
    return urllib.request.urlopen(request, context=context, timeout=3)


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL needed")
class NearbyReceiverTests(unittest.TestCase):
    def _start(self, dest, *, approve=True):
        server, temp, state, info, _ = create_receiver(
            dest, session_seconds=10, approve_offer=lambda _: approve,
        )
        thread = threading.Thread(
            target=serve_receiver,
            args=(server, temp, state, time.monotonic() + 3),
            daemon=True,
        )
        thread.start()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with socket.create_connection(("127.0.0.1", info.port), timeout=2) as raw:
            with context.wrap_socket(raw, server_hostname="Jolven Nearby") as peer:
                fingerprint = hashlib.sha256(peer.getpeercert(binary_form=True)).hexdigest()
                self.assertEqual(fingerprint, info.fingerprint)
        url = "https://127.0.0.1:" + str(info.port)
        return server, temp, state, info, thread, context, url

    def test_accepted_offer_commit_is_exclusive_and_verified(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dest = root / "received"
            dest.mkdir()
            original = root / "homebrew.gba"
            original.write_bytes(b"homebrew testing data")
            package = create_manifest([(original, "rom")])
            server, temp, state, info, worker, ctx, url = self._start(dest)
            try:
                with post(url + "/offer", info.token, package, ctx) as response:
                    self.assertEqual(response.read(), b"ACCEPTED")
                with post(url + "/file/0", info.token, original.read_bytes(), ctx) as response:
                    self.assertEqual(response.read(), b"VERIFIED")
                with post(url + "/commit", info.token, b"", ctx) as response:
                    self.assertEqual(response.read(), b"COMMITTED")
                worker.join(timeout=5)
                self.assertEqual((dest / original.name).read_bytes(), original.read_bytes())
            finally:
                if worker.is_alive():
                    server.server_close()
                    if state["staging"] is not None:
                        state["staging"].cleanup()
                    temp.cleanup()

    def test_user_rejection_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dest = root / "dest"
            dest.mkdir()
            rom = root / "game.nes"
            rom.write_bytes(b"game")
            server, temp, state, info, worker, ctx, url = self._start(dest, approve=False)
            try:
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    post(url + "/offer", info.token, create_manifest([(rom, "rom")]), ctx)
                self.assertEqual(denied.exception.code, 403)
                self.assertEqual(list(dest.iterdir()), [])
            finally:
                worker.join(timeout=5)
                if worker.is_alive():
                    server.server_close()
                    temp.cleanup()

    def test_bad_file_hash_is_never_committed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dest = root / "dest"
            dest.mkdir()
            rom = root / "game.gba"
            rom.write_bytes(b"correct")
            server, temp, state, info, worker, ctx, url = self._start(dest)
            try:
                with post(url + "/offer", info.token, create_manifest([(rom, "rom")]), ctx):
                    pass
                with self.assertRaises(urllib.error.HTTPError) as failure:
                    post(url + "/file/0", info.token, b"WRONG!!", ctx)
                self.assertEqual(failure.exception.code, 400)
                self.assertEqual(list(dest.glob("game.gba")), [])
            finally:
                worker.join(timeout=5)
                if worker.is_alive():
                    server.server_close()
                    if state["staging"] is not None:
                        state["staging"].cleanup()
                    temp.cleanup()

    def test_receiver_can_be_cancelled_without_opening_a_file(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td)
            server, temporary, state, info, deadline = create_receiver(
                dest, session_seconds=30, approve_offer=lambda _: False,
            )
            stop = threading.Event()
            credential_dir = Path(temporary.name)
            worker = threading.Thread(
                target=serve_receiver,
                args=(server, temporary, state, deadline, stop), daemon=True,
            )
            worker.start()
            stop.set()
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive())
            self.assertFalse(credential_dir.exists())
            self.assertEqual(list(dest.iterdir()), [])

    def test_cannot_bind_to_public_address(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                create_receiver(Path(td), bind_address="8.8.8.8")


if __name__ == "__main__":
    unittest.main()
