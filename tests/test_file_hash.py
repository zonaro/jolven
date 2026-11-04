# Tests for the file hash utility (Taiga F1).

import hashlib
import tempfile
import unittest
from pathlib import Path

from cartridges.utils.file_hash import sha256_of_file, sha256_of_first_matching


class FileHashTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def _write(self, name: str, content: bytes) -> Path:
        path = self.tmp / name
        path.write_bytes(content)
        return path

    def test_sha256_of_file(self):
        path = self._write("game.exe", b"installer bytes")
        expected = hashlib.sha256(b"installer bytes").hexdigest()
        self.assertEqual(sha256_of_file(path), expected)

    def test_sha256_of_file_none_when_missing(self):
        self.assertIsNone(sha256_of_file(self.tmp / "nonexistent.exe"))

    def test_sha256_of_first_matching_returns_first_existing(self):
        a = self._write("a.exe", b"first")
        b = self._write("b.bin", b"second")
        self.assertEqual(
            sha256_of_first_matching([self.tmp / "nope.exe", a, b]),
            hashlib.sha256(b"first").hexdigest(),
        )

    def test_sha256_of_first_matching_none_when_nothing_exists(self):
        self.assertIsNone(
            sha256_of_first_matching([self.tmp / "nope.exe", self.tmp / "nada.bin"])
        )


if __name__ == "__main__":
    unittest.main()
