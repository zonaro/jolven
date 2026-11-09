import 'package:flutter_test/flutter_test.dart';
import 'package:jolven_flutter/src/platform_catalog.dart';

void main() {
  test('recognizes unambiguous ROMs without assuming installed emulators', () {
    expect(identifyPlatform('Super Mario.GBA').confidentId, 'gba');
    expect(identifyPlatform('my.game.sfc').confidentId, 'snes');
    expect(identifyPlatform('zelda.z64').confidentId, 'n64');
  });

  test('disc images and archives always require explicit console choice', () {
    for (final name in ['disc.iso', 'disc.chd', 'game.zip', 'game.bin', 'abc.rvz']) {
      final result = identifyPlatform(name);
      expect(result.confidentId, isNull, reason: name);
      expect(result.requiresChoice, isTrue, reason: name);
    }
  });

  test('unknown extension is never silently routed', () {
    expect(identifyPlatform('notes.txt').isUnknown, isTrue);
    expect(identifyPlatform('noextension').isUnknown, isTrue);
    expect(identifyPlatform('.hidden').isUnknown, isTrue);
  });
}
