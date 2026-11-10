# Android external emulator compatibility matrix — implementation status

**Jolven contains no emulators, ROMs, BIOS, or cores.**

| External package | Android launch mechanism | Evidence | Status |
| --- | --- | --- | --- |
| org.ppsspp.ppsspp | ACTION_VIEW with explicit org.ppsspp.ppsspp.PpssppActivity, user-granted content URI | PPSSPP official frontend integration docs | Documented protocol; **needs device test** |
| org.ppsspp.ppssppgold | ACTION_VIEW with explicit org.ppsspp.ppsspp.PpssppActivity | PPSSPP official docs | Documented protocol; **needs device test** |
| org.ppsspp.ppsspplegacy | Same explicit Activity and content URI | PPSSPP official docs | Documented protocol; **needs device test** |
| org.dolphinemu.dolphinemu | ACTION_VIEW with package/URI | Kwiq Gaming legacy configuration, no version contract proven | **Experimental/unverified** |
| com.retroarch / com.retroarch.aarch64 / com.retroarch.ra32 | Default: open app only. Opt-in advanced user-entered ROM absolute path and LIBRETRO full .so path sent to RetroActivityFuture | Libretro official Android CLI docs; issues #17433, #19357 | **Experimental opt-in**, still requires hardware verification; incorrect paths may black-screen |
| org.mupen64plusae.v3.fzurita | Open app only | Kwiq legacy references variants/activities | Manual |
| org.duckstation.android | Open app only | Kwiq legacy `bootPath` (not revalidated) | Manual |
| org.azahar_emu.azahar | Open app only | Requires own contract | Manual |

The documented PPSSPP Android launcher uses an ACTION_VIEW intent for a SAF content URI; args may include `org.ppsspp.ppsspp.Args` but Jolven avoids modifying runtime behavior until tested. An Android intent being accepted is *not proof* the game opened.

RetroArch official docs require `ROM` as **full path** and `LIBRETRO` as full **core path**. Jolven has a SAF URI, not a reliable readable file path across all Android versions, and cannot introspect cores in another app sandbox. A hardcoded `/data/data/.../cores/snes9x...` from Kwiq would be fragile and unsafe; do not port it as default. See RetroArch issue #19357 for user-visible black-screen outcomes on wrong core paths.

References:
- https://www.ppsspp.org/docs/reference/front-end-integration/
- https://www.ppsspp.org/docs/reference/command-line/
- https://docs.libretro.com/guides/cli-intro/
- https://github.com/libretro/RetroArch/issues/17433
- https://github.com/libretro/RetroArch/issues/19357
- https://github.com/zonaro/Kwiq/blob/main/app/src/main/java/br/com/redclaw/kwiq/emulator/EmulatorConfig.kt

**Physical test ledger (not yet executed):** test Android 11/13/15, PPSSPP Free+Gold at a pinned version, homebrew `.iso` via SAF, URI permission revoked, missing package, core missing, return to hub. Record actual results and device names before upgrading any item to tested.

## Opt-in advanced RetroArch launch (not a default)

The ROM's action menu now offers `RetroArch: advanced paths`. The user types an absolute ROM path readable by the **external RetroArch** and the exact installed core full `.so` path copied from that app's settings. Jolven validates only simple path syntax and then passes official `ROM`/`LIBRETRO` intent extras. It does **not** read/verify the other app's core directory, convert arbitrary SAF URIs into guessed filesystem paths, install a core, or claim successful play. The normal safe default remains to open RetroArch and let the user browse their ROM there. Do not advertise this advanced path as broadly compatible before on-device tests.

## Preferred external emulators by console — 10/11/2026 (issue #85/#151)

The Android hub now reads a separate persisted preference for **each console** (in Android's private `jolven_console_emulator_defaults` SharedPreferences). A game-level override always wins over its console default. The user can set or clear this from each ROM menu → **Emulador padrão deste console**; the selector also shows a default marker.

`lib/src/emulator_compatibility.dart` ranks only **installed** emulator packages from Jolven's known adapter list. A conservative static console-family heuristic puts PPSSPP next to PSP content, Dolphin next to GameCube/Wii, Mupen64 next to N64, DuckStation next to PS1, Azahar next to 3DS and DraStic next to NDS. RetroArch is treated as a **manual** option until the user enters its real external ROM/core paths, and even then the handoff is labeled **unverified**. The heuristic does **not** infer whether any core, BIOS, file format or emulator version actually works. Unknown/ambiguous ROM extensions get no compatibility claim.

Other installed emulators are hidden under **Mostrar outros emuladores instalados** when there is an appropriate console family. Choosing one of those unrelated apps opens it **without** sending a ROM intent. Users can still configure an emulator per-game. Removed/uninstalled packages are filtered out at the point of display.

### Acceptance still pending

- Actual on-device install/launch results for each external package/Android version; evidence must distinguish successful intent dispatch from successful game loading.
- Version-based capability metadata from public emulator APIs (if any) and a device-tested matrix; do not label generic intents as verified solely because package exists.
- Game collections and console defaults share only catalog metadata, never private data from other emulators.
- A physical-gamepad-friendly selector and return-to-hub path after external apps; tests on Android 11–15, Android TV, tablets and budget devices.

Tests: `flutter test test/emulator_compatibility_test.dart`, Kotlin MethodChannel smoke tests on Android emulator.
