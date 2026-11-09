import 'package:flutter_test/flutter_test.dart';
import 'package:jolven_flutter/src/models.dart';

void main() {
  test('installed emulator does not imply verified launch support', () {
    final emulator = EmulatorInfo.fromMap({
      'id': 'retroarch64',
      'name': 'RetroArch 64',
      'packageName': 'com.retroarch.aarch64',
      'installed': true,
      'romLaunch': 'manual',
    });
    expect(emulator.installed, isTrue);
    expect(emulator.canAttemptView, isFalse);
  });

  test('experimental VIEW integration is never guaranteed', () {
    final emulator = EmulatorInfo.fromMap({
      'id': 'ppsspp',
      'name': 'PPSSPP',
      'packageName': 'org.ppsspp.ppsspp',
      'installed': true,
      'romLaunch': 'view_unverified',
    });
    expect(emulator.canAttemptView, isTrue);
    final handoff = LaunchOutcome.fromMap({
      'status': 'handoff_requested_unverified',
    });
    expect(handoff.confirmedGameStarted, isFalse);
  });

  test('ROM model stores only a user-granted document URI', () {
    final rom = RomItem.fromMap({
      'uri': 'content://provider/document/123',
      'name': 'Homebrew.gba',
    });
    expect(rom.name, 'Homebrew.gba');
    expect(rom.uri, startsWith('content://'));
  });
}
