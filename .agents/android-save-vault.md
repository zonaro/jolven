# Jolven Android — user-selected save vault (partial #140)

**No access to private data of RetroArch, PPSSPP, Dolphin or other apps.** The user must select exported save files using Android Storage Access Framework. Jolven cannot initiate autosave or manage the other emulator's in-game state slots.

Implemented:
- Import one save file with a user-selected URI, optional ROM association, SHA-256 checksum, UTF-8 display name, copy into Jolven's private vault, and deduplication by content checksum + size.
- A local list of saves and independent export via ACTION_CREATE_DOCUMENT; verify the local file's SHA-256 before exporting.
- Delete a local vault copy only. Original selected file is never modified; files shared/exported by the user are outside Jolven's control.
- Limits: file 32 MiB; aggregate 128 MiB; at most 250 records. No hidden filesystem paths and no full-storage permissions. Errors are surfaced, with attempts to delete partially exported new documents.

Pending for #140: validated compatibility by core/emulator/version; portable ZIP backups and manifests, conflict handling/restoration guides, rollback, full lifecycle/SAF provider tests, large save-state support and hardware QA. 'Autosave on pause' belongs to the external emulator and **cannot** be implemented by controlling it from the Jolven hub.

Related: #85 external emulator contract, #146 Nearby for user-authorized files, #110 ROM identity.
