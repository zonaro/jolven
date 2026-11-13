#!/usr/bin/env python3
"""Print the Jolven UTC build version as YY.DDD.HHmm.

Set JOLVEN_VERSION to freeze the version across Meson setup, compilation,
all release packages, the Git tag and GitHub release notes.
"""

import sys

from versioning import build_version


if __name__ == "__main__":
    try:
        print(__doc__.strip() if "--help" in sys.argv[1:] else build_version())
    except ValueError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
