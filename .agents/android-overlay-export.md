# Android RetroArch overlay editor (OpenEmux-inspired) — #149 / #144

This increment adds a local optional visual editor for a small set of virtual gamepad buttons. It does not play a game or render controls over another application.

Implementation:
- Flutter canvas with draggable X/Y positions and accessible sliders for A/B/X/Y, D-pad directions, Start and Select.
- Live canvas preview of a single 800×450 landscape overlay.
- Pure Dart RetroOverlayFormat.generate emits a whitelisted Libretro/RetroArch .cfg with positions converted to image pixel coordinates and radial touch hitboxes.
- Flutter renders a PNG using PictureRecorder; no external artwork is bundled. Export calls the Kotlin SAF document picker, which saves a ZIP containing only jolven.cfg and jolven.png.
- The user extracts the files together and configures the overlay inside the separately installed RetroArch through Settings > On-Screen Display > On-Screen Overlay. Jolven never installs it into private app directories, injects game input, or asserts compatibility.
- Native export validates PNG magic and size (up to 5 MiB), config size (up to 64 KiB) and uses ZipOutputStream with fixed paths and user-selected destination.
- Unit tests reject invalid action names and positions and check generated CFG fields.

Still open for #149:
- Real-device validation with actual RetroArch versions, orientation-specific layouts, importing existing skins, versioned Jolven skin.json format, per-emulator feedback, save/reload presets, Delta/Manic compatibility evaluation, accessibility and backup.
- Do not advertise this as an automatic cross-emulator skin manager.

References:
https://docs.libretro.com/guides/libretro-overlays/
https://docs.libretro.com/development/retroarch/input/overlay/
