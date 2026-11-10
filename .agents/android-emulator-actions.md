# External emulator actions (Android) — #139

The Jolven Android frontend **does not own an emulator engine or game window**. A "PauseSheet" overlay from OpenEmux Mobile would imply access to an embedded RetroArch process, so it cannot be copied literally into an external-emulator launcher.

Implementation:
- `EmulatorActionCatalog`: per-emulator instructions for pause/resume, save states, shaders/speed, screenshot and hardcore RetroAchievements. Localized pt/en/es.
- `EmulatorActionsPage`: accessible from the installed emulators list. Shows package/version and opens the selected emulator with the existing public launch intent.
- All in-game capabilities are **instructionsOnly**, not command buttons. No injected input, window overlays, AccessibilityService or reading another app's private data.
- Do not claim a game was paused, resumed, saved, screenshotted or patched when only the external application was opened.
- Unit tests verify actions cannot silently become executable and localized instructions exist.

## Future interoperability
Only upgrade an action to executable when the emulator's specific version has an official, independently testable public API and user approval. Test with an Android device and record supported/unsupported/unverified in `docs/EMULATOR_MATRIX.md`. When unsupported, keep the guidance mode as fallback.

Refer to #85 for emulator adapters, #140 for separately authorized save files, #144 for external touch overlay limitations and #154 for read-only RetroAchievements progress. The Jolven-owned MediaProjection recorder (#87) is a separate opt-in feature.
