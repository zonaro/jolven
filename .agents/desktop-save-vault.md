# Jolven Desktop save archive core (#153)

A backend-only first increment adds explicit save-file backup/restore in cartridges/utils/emulator_saves.py. It does not access private emulator paths or alter existing save slots automatically.

Create:
- Caller provides an explicit list of regular files; symlinks and duplicates are refused.
- Versioned Jolven ZIP contains exactly a JSON manifest and fixed filenames under files/ with SHA-256 and lengths; original full paths are not included.
- Restricts 500 files, 512 MiB per file and 1 GiB total; writes to temporary archive then renames only after success.

Restore:
- Must target an existing user-selected directory.
- Validates archive manifest/version, entry paths, CRC/checksums and declared sizes before restoring.
- Rejects suspicious compression ratios, unexpected files, invalid names and encrypted entries.
- Stages locally and uses exclusive hardlink creation; never overwrites existing saves. A failure removes newly created outputs, leaving existing files untouched.

Unit tests cover round-trip, conflicts, traversal, bad sources and manifest.

**Still needed for #153:** GTK backup/restore interface, progress/cancel, portable game/core/version identity, compatibility warnings across emulators, RetroArch Flatpak/natively installed path discovery with consent, automatic snapshots only through supported APIs, Android Nearby interop and hardware QA. No cloud service and no forced destination.
