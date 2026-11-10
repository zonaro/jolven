# Libretro thumbnail provider — Android #145

The Android ROM menu now offers **Find cover on Libretro** as a one-at-a-time, explicit user action. It does **not** scrape game art in the background or distribute thumbnails with the app. The user may edit the title before requesting, and an existing cover requires explicit confirmation before replacement.

The source is `https://thumbnails.libretro.com/{official system playlist name}/Named_Boxarts/{game name}.png`; the sanitized name follows Libretro's published naming convention (characters `&*/:`<>?\\|"` replaced with underscores). Only an allowlisted set of console IDs may construct a URL. URL path segments are encoded by Android `Uri.Builder`. No arbitrary URL input, redirects, HTTP fallback, or extra requests.

The native provider:
- HTTPS fetch only, 8-second connect and 15-second read timeouts;
- HTTP 200 required, no redirects, maximum 8 MiB, validated PNG/JPEG/WebP signature and decoded dimensions;
- stream into Jolven-private storage and keep source URL as `coverSource`;
- manual cover selection clears remote provenance; clearing cover removes its local file/provenance;
- a failure never claims the image was found or modifies the original ROM;
- downloaded art is not bundled or re-shared by default.

**Limits:** matching is by title, not ROM hash; some systems/title conventions differ. A missing filename yields a recoverable failure. A future provider UI can add multiple sources, caching, limits, manual crop, and license/source selection, but those are not part of this increment. Libretro's repository contains scans whose rights may be owned by their creators or publishers; the user is responsible for appropriate use and Jolven does not assert ownership.

References:
- https://github.com/libretro-thumbnails/libretro-thumbnails
- https://docs.libretro.com/guides/roms-playlists-thumbnails/

#145 still requires Android device/network tests, additional artwork providers and full per-game artwork management.
