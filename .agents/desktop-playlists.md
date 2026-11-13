# Jolven Desktop playlists — #155 increment

The + menu includes **My Playlists**, a native libadwaita dialog to create, rename and delete offline collections, and add/remove the currently focused game from a collection. It uses the existing Game.game_id identifiers in the Jolven Store. Editing a playlist never changes or deletes any game files, metadata or source launcher.

Backend:
- Pure standard-library PlaylistStore; versioned compact JSON at shared.app_dir/playlists.json.
- Atomic temporary write + fsync + replace; user-data file mode 0600.
- Up to 100 playlists with 10k distinct game IDs each. Validates UUIDs, names and member IDs; corrupt/unsupported files are reported without overwriting them.
- Preserves manual order, supports explicit reorder, de-duplicates members and supports safe rename/delete.
- Unit tests cover persistence, membership, ordering, duplicate titles, corrupt data and unaffected game records.

UI:
- Native Adw.Dialog and Gtk.ListBox, New/Rename/Delete controls, and a contextual Add/Remove current game action.
- Requires further full GTK/Flatpak tests, sorting UI, full cover/cartridge/list modes and gamepad-only interaction, filter main library by playlist, drag-and-drop/selection batches and stable hash reconciliation before #155 can be considered done.
