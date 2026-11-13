import 'package:flutter_test/flutter_test.dart';
import 'package:jolven_flutter/src/overlay_editor_page.dart';

void main() {
  test('exported CFG uses whitelisted names and normalized coordinates', () {
    final data = RetroOverlayFormat.generate([
      const OverlayControl('a', 0.8, 0.7),
      const OverlayControl('start', 0.5, 0.9),
    ]);
    expect(data, contains('overlays = 1'));
    expect(data, contains('jolven.png'));
    expect(data, contains('overlay0_desc0 = "a,640,315,radial,35,35"'));
    expect(data, contains('overlay0_descs = 2'));
  });

  test('export rejects invalid action and coordinates', () {
    expect(
      () => RetroOverlayFormat.generate([
        const OverlayControl('../../evil', 0.4, 0.5),
      ]),
      throwsFormatException,
    );
    expect(
      () => RetroOverlayFormat.generate([
        const OverlayControl('a', -1, 0.5),
      ]),
      throwsFormatException,
    );
  });

  test('button dragging is clamped to safe canvas range', () {
    final moved = const OverlayControl('a', 0.5, 0.5).at(12, -10);
    expect(moved.x, 0.96);
    expect(moved.y, 0.04);
  });
}
