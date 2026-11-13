import 'package:flutter_test/flutter_test.dart';
import 'package:jolven_flutter/src/emulator_compatibility.dart';
import 'package:jolven_flutter/src/models.dart';

const ppsspp = EmulatorInfo(
  id: 'ppsspp', name: 'PPSSPP', packageName: 'org.ppsspp.ppsspp',
  installed: true, romLaunch: 'view_documented',
);
const dolphin = EmulatorInfo(
  id: 'dolphin', name: 'Dolphin', packageName: 'org.dolphinemu.dolphinemu',
  installed: true, romLaunch: 'view_unverified',
);
const retro = EmulatorInfo(
  id: 'retroarch64', name: 'RetroArch', packageName: 'com.retroarch.aarch64',
  installed: true, romLaunch: 'manual',
);
const notInstalled = EmulatorInfo(
  id: 'mupen64', name: 'Mupen', packageName: 'test.mupen',
  installed: false, romLaunch: 'manual',
);

void main() {
  test('PPSSPP recommended only for PSP and never claimed launched', () {
    const psp = RomItem(uri: 'content://psp', name: 'Homebrew.iso', platformId: 'psp');
    const nes = RomItem(uri: 'content://nes', name: 'Homebrew.nes');
    expect(emulatorFit(psp, ppsspp), EmulatorFit.documentedIntent);
    expect(emulatorFit(nes, ppsspp), EmulatorFit.differentSystem);
    expect(emulatorFit(nes, retro), EmulatorFit.manualOnly);
    expect(emulatorFit(nes, dolphin), EmulatorFit.differentSystem);
  });

  test('RetroArch explicit paths remain unverified, never ready/confirmed', () {
    const rom = RomItem(
      uri: 'content://rom', name: 'Homebrew.nes',
      retroCorePath: '/data/core.so', retroRomPath: '/storage/homebrew.nes',
    );
    expect(emulatorFit(rom, retro), EmulatorFit.retroArchPathsUnverified);
    expect(const LaunchOutcome(status: 'handoff_requested_unverified')
        .confirmedGameStarted, false);
  });

  test('unknown image format does not pretend compatibility', () {
    const rom = RomItem(uri: 'content://unknown', name: 'archive.zip');
    expect(emulatorFit(rom, retro), EmulatorFit.unknownSystem);
    expect(emulatorFit(rom, ppsspp), EmulatorFit.unknownSystem);
  });

  test('console default applies unless per-game preference exists', () {
    const rom = RomItem(uri: 'content://rom', name: 'Homebrew.iso', platformId: 'psp');
    final sorted = rankEmulators(
      rom, [retro, ppsspp, notInstalled],
      consoleDefaults: {'psp': retro.packageName},
    );
    expect(sorted.map((e) => e.id).toList(), ['retroarch64', 'ppsspp']);

    const override = RomItem(
      uri: 'content://rom', name: 'Homebrew.iso', platformId: 'psp',
      emulatorPackage: 'org.ppsspp.ppsspp',
    );
    final overridden = rankEmulators(
      override, [retro, ppsspp],
      consoleDefaults: {'psp': retro.packageName},
    );
    expect(overridden.first.id, 'ppsspp');
  });

  test('incorrect-console preference cannot outrank compatible emulator', () {
    const rom = RomItem(
      uri: 'content://rom', name: 'Homebrew.nes',
      emulatorPackage: 'org.ppsspp.ppsspp',
    );
    expect(rankEmulators(rom, [ppsspp, retro]).first.id, 'retroarch64');
  });

  test('Dolphin Wii/GC intent remains explicitly experimental', () {
    const wii = RomItem(uri: 'content://wii', name: 'Game.wbfs');
    expect(emulatorFit(wii, dolphin), EmulatorFit.experimentalIntent);
  });
}
