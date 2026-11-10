# Android firmware/BIOS guide (#142)

- The Jolven Android app provides offline explanatory profiles for NES, SNES, GB/GBC, GBA, PS1, Saturn, Dreamcast, PSP and NDS. They are **guidance**, not proof of exact requirements for any particular third-party emulator version or core.
- Only the user can choose an image/file via Android SAF. The app calculates SHA-256 and size (maximum 64 MiB for inspection) on a worker, without copying it to emulator directories. Checksum calculation does **not** establish that the file is authentic, compatible or installed.
- No BIOS/firmware ROM downloads, bundled assets or private-directory reads; no full-storage permission. For setup, open the external emulator and follow its documentation.
- The guide can be used without RetroArch installed and offline.
- Remaining for completion: versioned core-specific required/optional manifests with verifiable official references, expected BIOS hashes, confident status from an authorized API, tests on two consoles with real external emulators, and permission-denial/revocation QA.
