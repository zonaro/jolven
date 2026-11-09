# Jolven Android — local cover art and cartridge labels

OpenEmux-inspired UI, implemented with **user-selected local images only**. No external provider, image scraping or default copyrighted pack is bundled.

- Each ROM stores distinct `coverPath` and `labelPath`; favorites/collections are independent. Toggle between cover and label display in the ROM library.
- Android ACTION_OPEN_DOCUMENT with `image/*` grants temporary access. Kotlin `JolvenArtworkStore` copies JPEG/PNG/WebP into app-private files, names files using a SHA-256 digest of the ROM's SAF URI (no user-supplied filename), and returns the local path.
- Memory / integrity controls: stream copy in 32 KiB chunks, max 8 MiB; sniff file magic, BitmapFactory bounds-only decoding, max width/height 8192 and max 24M pixels. No SVG/network/remote image processing. File moved from temporary into the local directory after validation.
- Clearing artwork deletes only files located under Jolven's canonical artwork directory; deleting a ROM catalog entry also removes its artwork (never its ROM file). Changing covers never edits the underlying game content.
- Source image remains owned by the user. Covers/labels are local app data: uninstalling the app deletes app-private copies. Future backups must include them with user consent.

**Open (#145)**: artwork search providers, provenance/licensing, caching, crop/editor, portable identity by ROM hash, cartridge frame visuals, responsive grids, extensive storage/performance and Android hardware QA.

References: https://github.com/guilhermefeitosa66/OpenEmux and https://github.com/zonaro/Kwiq
