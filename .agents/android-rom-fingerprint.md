# On-demand ROM SHA-256 fingerprinting (#82 / #110 / #154)

The Android frontend can optionally compute the SHA-256 of a user-selected ROM. The ROM remains stored in the user's chosen SAF provider and **is never modified**.

Implementation:
- In ROM item action menu, select **Compute SHA-256**.
- Kotlin `RomFingerprint` streams the content in 64 KiB chunks on a background executor, with a 512 MiB size limit to protect low-memory Android devices.
- Saves digest and byte count in Jolven's local metadata, preserving favorites/console/artwork when updating. The hash appears in ROM list view only when computed.
- If the SAF permission was revoked, the ROM is unreadable or it exceeds the limit, it returns a recoverable error. Never invent a hash based on the file name.
- Native JVM tests include known SHA-256 fixture for `abc` and oversize rejection, and Flutter tests verify legacy/fingerprinted model mapping.

Scope and limitations:
- SHA-256 is a **content identity** and is not yet a RetroAchievements game ID. Official RA hashing may use specialized per-console hashes; do not equate them.
- Disc images larger than 512 MiB remain un-hashed until a streaming/cancellation UI is designed and tested.
- The current catalog still uses SAF URI as the primary key. Full hash-based duplicate reconciliation and cross-platform portable IDs await #110/#111.
- No upload, telemetry or automatic background hashing.
