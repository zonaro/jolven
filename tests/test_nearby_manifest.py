# SPDX-License-Identifier: GPL-3.0-or-later
"""Negative and normal cases for untrusted Nearby file manifests."""

import json
import tempfile
import unittest
from pathlib import Path

from cartridges.utils.nearby_manifest import (
    create_manifest, decode_manifest, verify_file,
)


class NearbyManifestTests(unittest.TestCase):
    def test_roundtrip_and_checksum(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rom = root / "homebrew.gba"
            rom.write_bytes(b"public-domain homebrew content")
            payload = create_manifest([(rom, "rom")])
            entry, = decode_manifest(payload)
            self.assertEqual(entry.kind, "rom")
            self.assertEqual(entry.name, rom.name)
            self.assertTrue(verify_file(rom, entry))
            rom.write_bytes(b"modified")
            self.assertFalse(verify_file(rom, entry))

    def test_rejects_traversal_and_absolute_paths(self):
        base = {
            "version": 1,
            "files": [{
                "name": "good.srm", "kind": "save",
                "size": 2, "sha256": "0" * 64,
            }]
        }
        for name in ("../bad", "/etc/passwd", "..", ".hidden", "x\\y", "x:y", "x\n"):
            with self.subTest(name=name):
                base["files"][0]["name"] = name
                with self.assertRaises(ValueError):
                    decode_manifest(json.dumps(base).encode())

    def test_unknown_fields_versions_and_types_are_rejected(self):
        source = {
            "version": 1,
            "files": [{
                "name": "game.nes", "size": 1,
                "sha256": "a" * 64, "kind": "rom",
            }]
        }
        bad = [
            {**source, "unexpected": "1"},
            {**source, "version": 2},
            {**source, "version": True},
            {**source, "files": [{**source["files"][0], "extra": 0}]},
            {**source, "files": [{**source["files"][0], "size": True}]},
        ]
        for case in bad:
            with self.subTest(case=case):
                with self.assertRaises(ValueError):
                    decode_manifest(json.dumps(case).encode())

    def test_duplicate_names_are_case_insensitive(self):
        base = {"version": 1, "files": [
            {"name": n, "size": 0, "sha256": "0" * 64, "kind": "rom"}
            for n in ("GAME.GBA", "game.gba")
        ]}
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            decode_manifest(json.dumps(base).encode())

    def test_symlink_is_never_uploaded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original = root / "good.srm"
            original.write_bytes(b"a")
            link = root / "link.srm"
            link.symlink_to(original)
            with self.assertRaises(ValueError):
                create_manifest([(link, "save")])


if __name__ == "__main__":
    unittest.main()
