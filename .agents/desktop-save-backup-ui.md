# Desktop save file backup GUI

The + menu offers **Export emulator saves…** and **Restore emulator saves…**. Each uses native GTK FileDialog pickers to select *specific* save files or an existing Jolven ZIP, then a destination file or folder. File I/O runs off GTK's main thread; success/failure is announced via the existing toast queue.

Core:
- Versioned ZIP manifest + SHA-256, no emulator sandbox discovery;
- Refuses symlinks and malicious ZIP entries, stages and validates restore before writing any output;
- Restore never overwrites existing saves. Existing data is preserved on error.
- User selects source/destination and is responsible for cross-core save compatibility.

Limitations: no batch progress/cancellation UI, no per-emulator compatibility validation, no scheduling/auto-backup and no remote share in this increment. Test Gtk.FileDialog and accessibility on actual GNOME/Flatpak installs before closing #153.
