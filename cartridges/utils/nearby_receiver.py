# SPDX-License-Identifier: GPL-3.0-or-later
"""User-approved Jolven Nearby receiving session, HTTPS + pinned certificate.

An explicit CLI session creates an ephemeral key and secret token; no
persistent network service, LAN discovery or unattended writes.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import http.server
import ipaddress
import os
import ssl
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from cartridges.utils.nearby_manifest import (
    CHUNK_SIZE, MAX_FILE_BYTES, MAX_MANIFEST_BYTES, decode_manifest,
    verify_file,
)
from cartridges.utils.nearby_sender import (
    NearbySessionInfo, _build_certificate, SESSION_SECONDS, MAX_REQUESTS,
)

import secrets


def create_receiver(
    destination: Path,
    *,
    bind_address: str = "127.0.0.1",
    port: int = 0,
    session_seconds: int = SESSION_SECONDS,
    approve_offer=None,
):
    """Build a receiving HTTPS server, but don't start accepting yet.

    approve_offer is an explicit local callback(entries)->bool. If absent,
    offers are denied, not silently accepted.
    """
    host = ipaddress.ip_address(bind_address)
    if host.version != 4 or not (host.is_private or host.is_unspecified):
        raise ValueError("Destination must be a private/loopback IPv4 bind")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("Invalid port")
    if type(session_seconds) is not int or not 10 <= session_seconds <= 600:
        raise ValueError("Invalid session duration")
    target = Path(destination).expanduser().resolve(strict=True)
    if not target.is_dir() or target.is_symlink():
        raise ValueError("Destination must be an existing regular directory")

    temp = tempfile.TemporaryDirectory(prefix="jolven-nearby-")
    try:
        cert, key, fingerprint = _build_certificate(Path(temp.name))
        token = secrets.token_urlsafe(32)
        expires = time.monotonic() + session_seconds
        counts = {"requests": 0}
        state = {"entries": None, "staging": None, "received": set(), "finished": False}

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def _allow(self) -> bool:
                counts["requests"] += 1
                if counts["requests"] > MAX_REQUESTS or time.monotonic() >= expires:
                    self.send_error(403, "Expired")
                    return False
                ip = ipaddress.ip_address(self.client_address[0])
                if not (ip.is_private or ip.is_loopback):
                    self.send_error(403, "Not local")
                    return False
                if not hmac.compare_digest(
                    self.headers.get("Authorization", ""), "Bearer " + token,
                ):
                    self.send_error(403, "Invalid session")
                    return False
                return True

            def _reply(self, status: int, message: str) -> None:
                content = message.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def do_GET(self):
                self.send_error(405, "POST only")

            def do_POST(self):
                if not self._allow():
                    return
                path = urlsplit(self.path).path
                raw_size = self.headers.get("Content-Length", "")
                if not raw_size.isdecimal() or len(raw_size) > 16:
                    self.send_error(411, "Content-Length required")
                    return
                length = int(raw_size)
                if path == "/offer":
                    if state["entries"] is not None or state["finished"] or length > MAX_MANIFEST_BYTES:
                        self.send_error(409, "Already offered or invalid size")
                        return
                    self.connection.settimeout(15)
                    try:
                        payload = self.rfile.read(length)
                        if len(payload) != length:
                            raise ValueError("Truncated offer")
                        entries = decode_manifest(payload)
                    except (ValueError, TimeoutError, OSError):
                        self.send_error(400, "Invalid manifest")
                        return
                    if approve_offer is None or not approve_offer(entries):
                        self._reply(403, "Offer rejected by receiving user")
                        return
                    state["staging"] = tempfile.TemporaryDirectory(
                        prefix=".jolven-staging-", dir=target,
                    )
                    state["entries"] = entries
                    self._reply(200, "ACCEPTED")
                    return
                entries = state["entries"]
                if entries is None or state["finished"]:
                    self.send_error(409, "No accepted offer")
                    return
                if path == "/commit":
                    if length != 0 or len(state["received"]) != len(entries):
                        self.send_error(409, "Not all files verified")
                        return
                    staging = Path(state["staging"].name)
                    if any((target / entry.name).exists() or
                           (target / entry.name).is_symlink() for entry in entries):
                        self.send_error(409, "Destination name collision")
                        return
                    linked: list[Path] = []
                    try:
                        for i, entry in enumerate(entries):
                            staged = staging / str(i)
                            if not verify_file(staged, entry):
                                raise ValueError("Staged file checksum mismatch")
                            dest = target / entry.name
                            os.link(staged, dest)  # exclusive: never overwrite existing saves
                            linked.append(dest)
                    except (ValueError, OSError):
                        for created in linked:
                            created.unlink(missing_ok=True)
                        self.send_error(409, "Commit failed; no existing files changed")
                        return
                    state["finished"] = True
                    self._reply(200, "COMMITTED")
                    return
                if not path.startswith("/file/"):
                    self.send_error(404, "Invalid endpoint")
                    return
                index_value = path.removeprefix("/file/")
                if not index_value.isdecimal() or len(index_value) > 4:
                    self.send_error(404, "Invalid index")
                    return
                index = int(index_value)
                if index >= len(entries) or index in state["received"]:
                    self.send_error(409, "File not offered or already received")
                    return
                entry = entries[index]
                if length != entry.size or length > MAX_FILE_BYTES:
                    self.send_error(400, "Content length mismatch")
                    return
                staging_path = Path(state["staging"].name) / str(index)
                written = 0
                checksum = hashlib.sha256()
                self.connection.settimeout(20)
                try:
                    with staging_path.open("xb") as dest:
                        while written < length:
                            chunk = self.rfile.read(min(CHUNK_SIZE, length - written))
                            if not chunk:
                                raise ValueError("Truncated transfer")
                            checksum.update(chunk)
                            dest.write(chunk)
                            written += len(chunk)
                    if checksum.hexdigest() != entry.sha256:
                        raise ValueError("Checksum mismatch")
                    state["received"].add(index)
                except (ValueError, OSError, TimeoutError):
                    staging_path.unlink(missing_ok=True)
                    self.send_error(400, "Transfer failed validation")
                    return
                self._reply(200, "VERIFIED")

            def log_message(self, *_args):
                return

        server = http.server.HTTPServer((bind_address, port), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(cert), str(key))
        server.socket = context.wrap_socket(server.socket, server_side=True)
        server.timeout = 1
        info = NearbySessionInfo(
            server.server_address[1], bind_address,
            fingerprint, token, time.time() + session_seconds,
        )
        return server, temp, state, info, expires
    except Exception:
        temp.cleanup()
        raise


def serve_receiver(
    server, temporary, state, deadline,
    stop_event: threading.Event | None = None,
):
    try:
        while (
            time.monotonic() < deadline and not state["finished"] and
            (stop_event is None or not stop_event.is_set())
        ):
            server.handle_request()
    finally:
        server.server_close()
        if state["staging"] is not None:
            state["staging"].cleanup()
        temporary.cleanup()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Jolven Nearby approved TLS receive")
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--seconds", type=int, default=300)
    args = parser.parse_args(argv)

    def prompt(entries):
        print("Sender offers:")
        for entry in entries:
            print(" -", entry.name, entry.kind, entry.size, "bytes")
        return input("Accept all these files (type YES)? ").strip() == "YES"

    server, temp, state, info, deadline = create_receiver(
        args.dest, bind_address=args.bind, port=args.port,
        session_seconds=args.seconds, approve_offer=prompt,
    )
    print("Jolven Nearby receiver (explicit session)")
    print("Fingerprint SHA256:", info.fingerprint)
    print("Session token:", info.token)
    print("URL: https://<computer-LAN-IP>:" + str(info.port))
    print("Expires in", args.seconds, "seconds")
    try:
        serve_receiver(server, temp, state, deadline)
    except KeyboardInterrupt:
        server.server_close()
        if state["staging"] is not None:
            state["staging"].cleanup()
        temp.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
