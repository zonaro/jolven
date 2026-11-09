# Android Remote Play + manual Android game discovery

Adaptation of the useful parts of the **Kwiq Gaming Mode** in [`MoonlightIntegration.kt`](https://github.com/zonaro/Kwiq/blob/main/app/src/main/java/br/com/redclaw/kwiq/MoonlightIntegration.kt).

## What works in this increment

- Detects installed **Moonlight**, variants, **Steam Link**, **Parsec**, **Chiaki**, **PS Remote Play**, and GeForce NOW using explicit Android package visibility entries.
- Opens their public launch Activities with normal OS intents. **Does not** enumerate PCs, inject streaming credentials, bypass account login, or pretend to start a host/game remotely.
- Lists Android packages that declare CATEGORY_GAME and allows the user to **manually include** an otherwise unclassified launchable app. This uses Android's MAIN/LAUNCHER query with no QUERY_ALL_PACKAGES.
- Emulator packages, Jolven itself and streaming clients are excluded from general Android game candidates to avoid duplicates. Users install/update remote clients separately.

## Kwiq shortcut compatibility

Kwiq's MoonlightIntegration uses LauncherApps to discover pinned/dynamic shortcuts where available. Jolven is **not** the default HOME launcher; it cannot assume the right to enumerate pinned shortcuts. No shortcut scanning or direct Sunshine pairing is enabled until a supported authorization path is tested in a real Android release.

## Still required for #84

Test Wi-Fi streaming on real hardware, client version variations and switching back to the Jolven hub. Desktop Sunshine/Apollo discovery, host pairing and media streaming remain responsibilities of the external client. A future integration may expose *user-provided* launchable shortcuts if Android's documented permissions permit it.
