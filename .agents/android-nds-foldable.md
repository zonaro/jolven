# Android tablet/foldable and Nintendo DS UI (#148)

First increment:
- Jolven's ROM shelf already has adaptive card grids and filters. A dedicated Nintendo DS layout guide is built with Flutter `LayoutBuilder`, `ConstrainedBox` and `AspectRatio`, and supports portrait, landscape and larger displays.
- The guide illustrates stacked and side-by-side dual-screen layouts and documents where to configure touch, screen order/scale and gamepad buttons in the **external emulator**.
- Adds detection of **DraStic** (`com.dsemu.drastic`) as a user-installed external app, using package visibility only; no ROM launch contract is claimed for DraStic. RetroArch is likewise external.
- Changing the preview changes **only Jolven UI**, never modifies an external emulator, its private files or game window.
- Flutter widget test covers toggling layout preview without any native method channels.

Still required before #148 can be closed: actual hardware fold posture/hinge/safe-region measurements, tests on tablet and foldable, approved live emulation layout settings through documented public APIs (if any), persisted UI preferences and end-to-end accessibility. No claims of guaranteed Nintendo DS gameplay on all versions.
