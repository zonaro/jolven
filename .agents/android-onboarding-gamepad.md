# Android emulator onboarding + gamepad discovery

This increment adds an **honest** RetroArch setup flow using the official Android installation guide and an Android InputDevice enumeration diagnostic in the hub.

- RetroArch stays external. The setup page opens https://docs.libretro.com/guides/install-android/ via the user's browser; no APK/core/BIOS downloader is embedded.
- Core installation/availability is always shown as **unverified** unless the external emulator exposes a tested public API. Even the optional advanced `LIBRETRO` path handoff cannot prove the core exists.
- Connected USB/Bluetooth controller names are listed using Android InputDevice/SOURCE_GAMEPAD/SOURCE_JOYSTICK/SOURCE_DPAD. The listing is refreshed by the hub's Refresh action. The app does not grab or remap the controller of another process.
- Standard Flutter focus navigation remains the initial controller interaction; joystick axis mapping, hotkeys, pairing changes and on-device QA remain open under #85/#88.

Legacy reference: https://github.com/zonaro/Kwiq/blob/main/app/src/main/java/br/com/redclaw/kwiq/GamepadDiagnostics.kt
