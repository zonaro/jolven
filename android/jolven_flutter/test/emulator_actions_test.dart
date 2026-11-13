import 'package:flutter_test/flutter_test.dart';
import 'package:jolven_flutter/src/emulator_actions.dart';
import 'package:jolven_flutter/src/models.dart';

void main() {
  const retro = EmulatorInfo(
    id: 'retroarch64', name: 'RetroArch 64',
    packageName: 'com.retroarch.aarch64',
    installed: true, romLaunch: 'manual',
  );
  const dolphin = EmulatorInfo(
    id: 'dolphin', name: 'Dolphin',
    packageName: 'org.dolphinemu.dolphinemu',
    installed: true, romLaunch: 'view_unverified',
  );

  test('no in-game actions are falsely exposed as remotely callable', () {
    for (final emulator in [retro, dolphin]) {
      for (final action in EmulatorActionCatalog.forEmulator(emulator, 'pt')) {
        expect(action.availability, ExternalActionAvailability.instructionsOnly);
      }
    }
  });

  test('hints are localized into Portuguese, English, Spanish', () {
    final portuguese = EmulatorActionCatalog.forEmulator(retro, 'pt');
    final english = EmulatorActionCatalog.forEmulator(retro, 'en');
    final spanish = EmulatorActionCatalog.forEmulator(retro, 'es');
    expect(portuguese, hasLength(5));
    expect(portuguese.first.title, 'Pausar e retomar');
    expect(english.first.title, 'Pause and resume');
    expect(spanish.first.title, 'Pausar y continuar');
  });

  test('missing runtime has no remote capabilities', () {
    final actions = EmulatorActionCatalog.forEmulator(retro, 'pt');
    expect(actions.any((action) =>
      action.availability != ExternalActionAvailability.instructionsOnly), false);
  });
}
