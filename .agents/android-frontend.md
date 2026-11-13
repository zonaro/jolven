# Jolven Android — frontend-only architecture (2026-11-09)

Decision: **no emulator engines, cores, BIOS, or games bundled**. The Android app uses Flutter for UI and Kotlin adapters to Android package manager, SAF, and public intents. [OpenEmux](https://github.com/guilhermefeitosa66/OpenEmux) is a reference for UX, not an embedded runtime. [Kwiq](https://github.com/zonaro/Kwiq) legacy Gaming Mode supplied the architectural examples for per-extension platform routing, external emulator packages and streaming client discovery.

## Deliveries

- `android/jolven_flutter/`: Dart models, ROM/import views, known installed Android games, installed emulator list and public launch actions. Initial pt-BR/en/es.
- `lib/src/platform_catalog.dart`: curated console-platform table; intentionally marks archives/disc images as ambiguous instead of falsely guessing. Completeness is not promised; hashes/header verification remain future work.
- `MainActivity.kt`: method channel, ACTION_OPEN_DOCUMENT with MULTIPLE, ACTION_OPEN_DOCUMENT_TREE, persist grants, existing-ROM deduplication by URI and simple metadata (favorite, platform, emulator preference). Only catalog entries are removed, not source files. At most 250 picked files per selection.
- `SafRomScanner.kt`: bounded background BFS over SAF tree with visited-set, max depth 8, max 2000 ROMs/max 6000 inspected documents. Does not extract archives. User-granted tree permission persists, and document URIs remain tied to that grant.
- Emulators are installed and updated independently by user. RetroArch is `manual_only`. For PPSSPP/Dolphin, experimental ACTION_VIEW URI handoff does not mean the ROM really opened.
- `.github/workflows/jolven-android.yml`: analysis, tests, debug APK build and artifact upload; generated Flutter/Android scaffold until files are committed.

## Privacy/security

No QUERY_ALL_PACKAGES, MANAGE_EXTERNAL_STORAGE or access to emulators' private data. No root, NDK, libretro or background input injection. SAF bookmarks are stored locally. Importing ZIP indexes a file as-is; **no decompression, automatic ROM extraction or untrusted file parsing**.

## Remaining blockers

- Hardware Android 11+ QA (gamepad, storage providers, URI revocation, multiple emulators and package versions).
- Per-package public integration contracts and core handling; do not guess private RetroArch paths.
- Explicit console choice for ambiguous extension during import (UI currently available in item menu), stronger identity based on hashes/serials, ZIP inspection with limits, game list manual inclusion, artwork.
- Collection/playlists, remote play, patcher, recording, sharing, RetroAchievements, tablet, NDS and desktop feature parity.
- Native instrumentation/performance tests, docs/release signatures/privacy disclosure.

Roadmap: https://github.com/zonaro/jolven/issues/89.
