#!/usr/bin/env python3
"""Generate version.py from version.py.in using the frozen UTC build version."""

import sys
from pathlib import Path

from versioning import build_version


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: write-version.py <template-in> <output-py>")
    template, output = map(Path, sys.argv[1:])
    output.write_text(
        template.read_text(encoding="utf-8").replace("@VCS_TAG@", build_version()),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
