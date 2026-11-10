# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit one-shot Jolven Nearby file sender over pinned HTTPS.

This is a desktop-side, opt-in primitive, NOT a running service. A receiving
client must pin the displayed certificate fingerprint AND provide the
ephemeral 256-bit token. No mDNS, cloud, automatic file acceptance or
write endpoint is provided.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import http.server
import ipaddress
import json
import secrets
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from cartridges.utils.nearby_manifest import create_manifest, decode_manifest, verify_file


SESSION_SECONDS = 300
MAX_REQUESTS = 512
CHUNK_BYTES = 128 * 1024


@dataclass(frozen=True)
class NearbySessionInfo:
    port: int
    bind_address: str
    fingerprint: str
    token: str
    expires_at: float


def _build_certificate(folder: Path) -> tuple[Path, Path, str]:
    openssl = shutil.which("openssl")
    if not openssl:
        raise RuntimeError("OpenSSL is required for a local TLS session")
    certificate = folder / "session.crt"
    key = folder / "session.key"
    subprocess.run(
        [
            openssl, "req", "-new", "-x509", "-newkey", "rsa:3072",
            "-sha256", "-nodes", "-days", "1",
            "-keyout", str(key), "-out", str(certificate),
            "-subj", "/CN=Jolven Nearby Session",
        ],
        check=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=30,
    )
    key.chmod(0o600)
    cert_pem = certificate.read_text(encoding="ascii")
    der = ssl.PEM_cert_to_DER_cert(cert_pem)
    fingerprint = hashlib.sha256(der).hexdigest()
    return certificate, key, fingerprint


def _parse_selection(items: list[str]) -> list[tuple[Path, str]]:
    selected: list[tuple[Path, str]] = []
    for raw in items:
        kind, separator, name = raw.partition(":")
        if not separator or not name:
            raise ValueError("Each file must be kind:/absolute/path")
        path = Path(name).expanduser()
        if not path.is_absolute():
            raise ValueError("Only explicit absolute file paths are allowed")
        selected.append((path, kind))
    return selected


def create_sender(
    files: list[tuple[Path, str]],
    *,
    bind_address: str = "127.0.0.1",
    port: int = 0,
    session_seconds: int = SESSION_SECONDS,
):
    """Return a TLS-wrapped HTTPServer, temporary certificate and session info.

    Caller must explicitly run serve_sender and close the context. No
    background service is created. Bind only IPv4 interfaces, and never
    accept non-private source addresses.
    """
    host = ipaddress.ip_address(bind_address)
    if host.version != 4 or not (host.is_private or host.is_unspecified):
        raise ValueError("Bind address must be IPv4 private/loopback/0.0.0.0")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("Invalid port")
    if type(session_seconds) is not int or not 10 <= session_seconds <= 600:
        raise ValueError("Invalid session duration")

    selections = list(files)
    manifest = create_manifest(selections)
    entries = decode_manifest(manifest)
    paths = [Path(p) for p, _ in selections]
    token = secrets.token_urlsafe(32)
    deadline = time.monotonic() + session_seconds
    expiry_wall = time.time() + session_seconds
    ephemeral = tempfile.TemporaryDirectory(prefix="jolven-nearby-")
    work = Path(ephemeral.name)
    try:
        cert, key, fingerprint = _build_certificate(work)
        request_counter = 0

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def do_GET(self):
                nonlocal request_counter
                request_counter += 1
                if request_counter > MAX_REQUESTS or time.monotonic() > deadline:
                    self.send_error(403, "Session expired")
                    return
                remote = ipaddress.ip_address(self.client_address[0])
                if not (remote.is_private or remote.is_loopback):
                    self.send_error(403, "Private LAN only")
                    return
                auth = self.headers.get("Authorization", "")
                if not hmac.compare_digest(auth, "Bearer " + token):
                    self.send_error(403, "Pairing required")
                    return
                route = urlsplit(self.path).path
                if route == "/manifest":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(manifest)))
                    self.end_headers()
                    self.wfile.write(manifest)
                    return
                if not route.startswith("/file/"):
                    self.send_error(404, "Not found")
                    return
                index_text = route.removeprefix("/file/")
                if not index_text.isdecimal() or len(index_text) > 4:
                    self.send_error(404, "Invalid index")
                    return
                index = int(index_text)
                if index >= len(paths):
                    self.send_error(404, "Unknown file")
                    return
                selected, entry = paths[index], entries[index]
                try:
                    if not verify_file(selected, entry):
                        self.send_error(409, "Source file changed")
                        return
                    with selected.open("rb") as stream:
                        self.send_response(200)
                        self.send_header("Content-Type", "application/octet-stream")
                        self.send_header("Content-Disposition", "attachment")
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Content-Length", str(entry.size))
                        self.end_headers()
                        total = 0
                        while data := stream.read(CHUNK_BYTES):
                            total += len(data)
                            if total > entry.size:
                                return
                            self.wfile.write(data)
                except (OSError, BrokenPipeError, ConnectionError):
                    # Failure is handled by client's checksum verification.
                    return

            def do_POST(self):
                self.send_error(405, "Read-only session")

            def log_message(self, _format, *_args):
                # No filenames, source IPs or tokens in logs.
                return

        server = http.server.HTTPServer((bind_address, port), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=str(cert), keyfile=str(key))
        server.socket = context.wrap_socket(server.socket, server_side=True)
        server.timeout = 1
        info = NearbySessionInfo(
            server.server_address[1], bind_address,
            fingerprint, token, expiry_wall,
        )
        return server, ephemeral, info, deadline
    except Exception:
        ephemeral.cleanup()
        raise


def serve_sender(
    server: http.server.HTTPServer, temporary, deadline: float,
    stop_event: threading.Event | None = None,
) -> None:
    """Serve only for the explicitly requested lifetime and then release port."""
    try:
        while time.monotonic() < deadline and (
            stop_event is None or not stop_event.is_set()
        ):
            server.handle_request()
    finally:
        server.server_close()
        temporary.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Jolven Nearby TLS send session")
    parser.add_argument("--bind", default="127.0.0.1",
                        help="IPv4 bind address; 0.0.0.0 exposes to local LAN")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("files", nargs="+",
                        help="kind:/absolute/path for rom/save/cover/label")
    arguments = parser.parse_args(argv)
    files = _parse_selection(arguments.files)
    server, temporary, info, deadline = create_sender(
        files, bind_address=arguments.bind, port=arguments.port,
        session_seconds=arguments.seconds,
    )
    print("Jolven Nearby session: copy these values on the receiving device.")
    print("TLS certificate SHA256:", info.fingerprint)
    print("Session token:", info.token)
    print("Address: https://<computer-LAN-IP>:" + str(info.port))
    print("Expires after", arguments.seconds, "seconds; Ctrl+C to stop")
    try:
        serve_sender(server, temporary, deadline)
    except KeyboardInterrupt:
        server.server_close()
        temporary.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
