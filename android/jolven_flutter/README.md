# Jolven Android — external emulators only

This is an **early implementation** of the Android frontend. It lives in the main Jolven repo until the Android architecture is validated.

## Product contract

- The APK **never embeds** RetroArch/libretro, cores, BIOS, or ROMs.
- Users install and update emulators independently; Jolven queries **known packages only**, with Android 11+ package visibility declarations.
- ROMs are chosen via Storage Access Framework (ACTION_OPEN_DOCUMENT). Jolven stores a persisted document URI and display name; removing a library item **does not delete** the ROM.
- RetroArch launches in **manual mode** until a public, tested intent/core contract is documented. PPSSPP and Dolphin receive an **experimental ACTION_VIEW** URI attempt; an accepted intent is *not evidence that the game started*. The user can open the emulator and choose the ROM manually.
- No access to private emulator app data. No injection of input, overlay on another activity, or save state/core management inside other apps.
- UI strings: pt-BR, en, es. The initial screen is navigable through touch and standard Flutter focus; complete gamepad mapping and native installed-games discovery are **not yet implemented**.

## Bootstrap and run

A Flutter SDK + Android SDK are required (not available in the environment where this first commit was prepared).

From this directory:

    flutter create --org com.redclaw --project-name jolven_flutter --platforms android .
    flutter pub get
    flutter analyze
    flutter test
    flutter run

Run **without** the --overwrite flag to preserve the committed Kotlin MainActivity and AndroidManifest; inspect generated changes before committing. The Flutter generator supplies platform Gradle files, launcher icons and wrapper assets omitted from this source-first scaffold.

Package is com.redclaw.jolven_flutter. Do not change package name without updating the Kotlin directory and Android manifest.

## Current delivery

- Flutter material UI for selected ROM documents and detected external emulators
- Kotlin MethodChannel: list known installed emulators, import ROM through SAF, persist read permission and library references, remove a reference, open installed emulator
- Version-agnostic experimental VIEW URI handoff for PPSSPP and Dolphin only
- Explicit warnings for unsupported/unverified direct launch; fallback to opening the emulator
- Dart model tests for capability semantics

## Still open / must be verified on a real device

- Flutter/Gradle build, QA on Android 11+, focus/gamepad end-to-end
- Proving direct launch on specific emulator version/package; fallback manual is expected
- Core identification, external RetroArch launch with ROM, Android installed-games catalog, per-game overrides, metadata/artwork, Moonlight
- Imported files are currently single-selection; folder scan, ROM hashing, richer formats and app backup await #82
- CI and releases, native screenshots/recording, SAF revocation/rotation integration tests

## Related issues

- #89 Android epic: https://github.com/zonaro/jolven/issues/89
- #83 architecture; #82 catalog; #85 emulator adapters; #141 RetroArch external; #143 onboarding; #151 compatibility matrix.

The OpenEmux Android project is a **UX reference**, not an SDK dependency:
https://github.com/guilhermefeitosa66/openemux-android

## Native Android games (first iteration)
The hub also detects installed launchable apps that Android categorizes as games, via package visibility for MAIN/LAUNCHER. Some games are not tagged CATEGORY_GAME and may not appear; manual app addition and a richer catalog remain pending #82. Opening an Android game uses the OS launch intent, not a custom launcher or accessibility service.
