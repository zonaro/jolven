# Android gamepad diagnostics (#85, #144)

Kwiq Gaming Mode's diagnostic concept is now adapted to the Jolven Flutter frontend.

- `GamepadDiagnosticsPage` shows controller devices already detected by the Android bridge and passively observes key presses and left joystick motion via an `EventChannel`.
- `MainActivity` forwards input **without consuming it**: both `dispatchKeyEvent` and `onGenericMotionEvent` return the results from `super`. No input injection or remapping of another application.
- Diagnostic stream exists only while the page is subscribed; joystick events are sampled at most every ~65 ms to avoid saturating the Flutter UI.
- No permission to capture another emulator's controller. Controls during emulation are managed by the external emulator. This does not imply in-game skin support.

**Still open:** Android physical controller hardware testing, connection/disconnection updates while screen open, full gamepad-only UI navigation, touch overlay export formats, controller profile persistence. Do not close #144 just because the diagnostics screen works.
