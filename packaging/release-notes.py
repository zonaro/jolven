#!/usr/bin/env python3
"""Write English-only GitHub Release notes for the verified desktop bundles."""

from __future__ import annotations

import argparse
from pathlib import Path

REPOSITORY = "https://github.com/zonaro/jolven"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--built-at", required=True)
    parser.add_argument("--previous", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    commit_link = f"{REPOSITORY}/commit/{args.commit}"
    comparison = (
        f"{REPOSITORY}/compare/{args.previous}...v{args.version}"
        if args.previous
        else f"{REPOSITORY}/commits/v{args.version}"
    )
    text = f"""# Jolven {args.version}

This release contains the **Jolven Linux desktop application** built from
the same source commit using a single UTC build version.

- **Build version:** `{args.version}` (`YY.DDD.HHmm`, UTC).
- **Build started:** {args.built_at}.
- **Source commit:** [{args.commit[:12]}]({commit_link}).
- **Changes since the previous release:** [View the GitHub comparison]({comparison}).

## Downloads

- **AppImage (x86_64):** standalone desktop bundle for compatible modern Linux systems.
- **RPM (x86_64):** install with `sudo dnf install ./jolven-{args.version}-1.x86_64.rpm`.
- **DEB (amd64):** install with `sudo apt install ./jolven_{args.version}_amd64.deb`.
- **SHA256SUMS:** SHA-256 checksums for all three binaries.

The RPM and DEB packages use system libraries and integrate with the system's
GSettings and desktop services. The AppImage bundles its Python/GTK runtime;
it does not install a privileged polkit helper and is intended for desktop
use. The Jolven Session requires a native system installation and an available
Gamescope/Wayland environment.

**Compatibility:** modern Linux distributions with the required GTK4 and
libadwaita versions. The AppImage still depends on a compatible Linux host
(graphics drivers, kernel and glibc); test it on your distribution before
relying on it for an unattended gaming session.

**Security:** verify your download using `SHA256SUMS`. The release does not
change or delete existing game libraries, saves or user settings.
"""
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
