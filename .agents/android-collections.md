# Collections and shelves — first Android increment

From the [OpenEmux](https://github.com/guilhermefeitosa66/OpenEmux) shelf/playlists design, implemented without emulation in the Jolven frontend.

- Collections are persisted offline by `JolvenCollections.kt`, separate from the library; create, rename, delete, toggle membership.
- References are scoped and stable as long as the same ROM SAF URI or Android package remains available: `rom:content://…`, `android:<package>`, `remote:<package>`. The original ROM, app and streaming client are not changed or deleted by editing a collection.
- Favorites are persisted per-ROM in Jolven's local catalog. Filter for favorites and collections on the shared screen.
- Limits: maximum 100 collections, 2000 distinct members each, title length 72 and reference length 2048. Malformed JSON is skipped, no network or third-party access.

**Gaps**: rename/move reconciliation via hash; artwork-backed cover/cartridge views; sort, search, multi-select; gamepad-only journey and 1000-item performance; portable schema/backup and desktop collections. Android app favorites should be added after catalog unification. These stay open under #147 / #82 / #110 / #111.
