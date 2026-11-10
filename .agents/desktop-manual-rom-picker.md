# Desktop manual ROM picker — #150 increment

The Jolven Desktop + button now offers **Import ROM…** (shortcut Ctrl+Shift+R). An asynchronous GTK FileDialog lets the user choose one ROM, the RetroArch installation type (native or Flatpak) and the specific installed `.so` libretro core. The result is opened as an editable **existing** DetailsDialog populated with the ROM title and a safely shell-quoted command. The user must confirm Add; no ROM, core or configuration file is modified. The existing `Store` remains the single library.

Safety: no auto core guess, no raw shell interpolation, no ZIP decompression, no implicit game creation. Files with unknown extensions are rejected; ambiguous formats show an explicit warning to choose a matching core. If a file or core is inaccessible, the UI gives an error. Works with user-selected readable paths; Flatpak sandbox access must be tested (core path and ROM path must be accessible inside RetroArch).

**Not yet complete:** multi-selection batch preview, console picker and richer metadata; safe ZIP extraction/copy-or-link; duplicates and moved-files reconciliation; cancellation/progress for batches; automated GTK widget tests and physical Desktop/Jolven Session QA. The manual import backend lives in `cartridges/importer/manual_roms.py`, and this UI addition lives in `manual_rom_dialog.py`.

No RetroArch binary/core/ROM is distributed by Jolven.
