# RetroAchievements web progress (read-only) — issue #154

Jolven Android is an external-emulator frontend. It **does not** unlock achievements or control hardcore in RetroArch/Dolphin/PPSSPP.

This increment adds the optional RetroAchievements screen under Tools. It calls the official HTTPS `API_GetGameInfoAndUserProgress.php` API only when the user taps the lookup button and shows the **server-reported** total, earned and hardcore totals. It requires an independently supplied RA username/ULID, a Web API Key and an explicit RA game ID. There is no inference from a ROM filename or shell result. The API key is **not saved on disk**; the text controller is cleared/disposed when leaving the screen. The Web API Key is transmitted in the required `y` query parameter over TLS.

Safety:
- Single request per user action, no background polling, redirects disabled, 12s connection timeout, 20s response timeout, max 3 MiB JSON. HTTP and parsing errors display a generic message without echoing credentials or URL.
- Never log the user-provided API key, request URI or exception details.
- No reading credentials from the external emulator. UI remains usable offline without an RA account.
- This is not the final account integration; typing a Web API Key each session is a deliberate at-rest privacy constraint for the first increment.

Still required to close #154:
- User-chosen durable credential storage via Android Keystore and account settings (or supported OAuth alternative if published), revocation/logout, refresh/caching with rate limit.
- Link local ROM to official RA game ID using verified hash mapping/manifest (#110), rather than manual ID.
- Hardware/network tests against RA service and response field evolution, user consent and error handling.
- UI for individual achievements, per-ROM progress and offline cached results.

Official API reference: https://api-docs.retroachievements.org/v1/get-game-info-and-user-progress.html
API key docs: https://api-docs.retroachievements.org/getting-started.html
