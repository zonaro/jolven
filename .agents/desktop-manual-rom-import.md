# Desktop manual ROM importer kernel — #150

Jolven already imports RetroArch `.lpl` playlists, but importing individual ROMs without playlists needs a separate user-controlled flow. This increment adds pure Python components under `cartridges/importer/manual_roms.py`:

- Resolve platform candidates from extensions, requiring explicit console choice for ambiguous `.bin/.cue/.iso/.chd/.zip/.7z` etc. No console is guessed from only a filename.
- Bounded scan from user-selected paths: max depth 8 and max 5,000 inspected files, skips symlink paths and avoids infinite directory loops by inode.
- Inspect ZIP central directory without extracting anything. Reject path traversal, absolute/drive paths, symlink entries, encrypted entries, over-large archives and suspicious compression ratios.
- Quote user file/core paths using `shlex.join` when building native or Flatpak RetroArch launch commands. No global RetroArch config modification or emulation binaries bundled.
- `tests/test_manual_roms.py` covers unique/ambiguous extension, traversal, symlink scan, malicious ZIP, safe shell quoting.

This is a **non-UI backend increment**, not a completed importer. Remains open: file-picker GTK GUI, preview/console selection, copy-vs-link choice, integration with the existing `Store` and imports, consistent backup/reindexing and cancellation, ZIP extraction strategy (only if necessary), interaction with Flatpak portals, desktop/Jolven Session hardware tests. Existing `RetroarchSource` and source registry are unchanged.
