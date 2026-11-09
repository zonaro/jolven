# Jolven Android — frontend-only architecture (2026-11-09)

Product decision: **no emulators, cores, BIOS or ROMs bundled** on Android (or desktop). Reference OpenEmux for library UX; use emulator apps **installed and updated by the user**. Port suitable Kwiq Gaming concepts, not its HOME launcher/dashboard.

## First code increment

Source: `android/jolven_flutter/`. Flutter UI for ROM catalog + categorized Android games + installed emulator status. Android native bridge: `jolven/external_emulators`.

Native actions:
- `listEmulators`: explicit Android <queries> package names; version-independent **presence only**.
- `listAndroidGames`: launchable packages tagged CATEGORY_GAME (known false negatives).
- `importRom`: ACTION_OPEN_DOCUMENT, persist read permission; local URI reference only.
- `listRoms` / `removeRom`: local catalog; removal never deletes user's ROM.
- `launchRom`: direct VIEW URI handoff *experimental* for PPSSPP/Dolphin, status `handoff_requested_unverified`. RetroArch opens manually until a public external intent is validated per version.
- `openEmulator` / `openAndroidGame`: ordinary OS launch intent; never access another app's sandbox.

No QUERY_ALL_PACKAGES or MANAGE_EXTERNAL_STORAGE; no AccessibilityService or display overlay. No private paths, NDK, RetroArch/libretro code, embedded cores, or rights-restricted games.

## Capability model and test policy

A discovered package is not equivalent to a working ROM launcher or installed core. A launch intent being accepted proves **only handoff**, not game start. Keep capability state as supported (measured on real hardware/version), unsupported, unverified. Never show a 'successfully started game' message on handoff alone.

Android 11+ tests: installed/missing app; emulator updated; SAF revoked; ambiguous ROM; app with no VIEW handler; user cancels picker; game category missing; return to hub; Bluetooth/USB gamepad; locale pt-BR/en/es; offline. Test PPSSPP/Dolphin, and explore RetroArch public contract (#141/#151) before enabling direct ROM mode.

## Separation and dependencies

- Android UI can use Flutter; native bridge stays as small Kotlin code for SAF, package manager and intents (#83).
- Catalog and identifiers can share schema with Jolven Desktop (#82/#110), not runtime code or emulator process.
- Save states, cheats, shaders, fast-forward and in-game touch controls belong to the **external emulator**. Jolven may export user-owned files or guide the user to settings, not control a foreign Activity without documented API (#139/#140/#144/#154).
- Remote Play (#84) and captures with user authorization (#87) are independent.
- OpenEmux code/assets must not be copied without assessing each component's license and attribution.

## Build and release

Flutter and Android SDK required; bootstrap via `flutter create --org com.redclaw --project-name jolven_flutter --platforms android .` before tests. CI workflow: `.github/workflows/jolven-android.yml`. No Android SDK or Flutter SDK was available in the assistant's working runtime; tests and APK build must be verified by CI/hardware.

Next: per-game emulator choices, stable persistence/migrations, multi-ROM/folder SAF importer, core/BIOS guide, screenshots, artwork, installed game icon/metadata, accessibility and gamepad full journey. Keep issue #89 as the roadmap and do not close unverified features.
