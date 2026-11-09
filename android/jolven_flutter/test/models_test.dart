import 'package:flutter_test/flutter_test.dart';
import 'package:jolven_flutter/src/models.dart';

void main() {
  test('an installed RetroArch is not automatically launch-capable', () {
    final emulator = EmulatorInfo.fromMap({
      'id': 'retroarch64',
      'name': 'RetroArch 64',
      'packageName': 'com.retroarch.aarch64',
      'installed': true,
      'romLaunch': 'manual',
    });
    expect(emulator.installed, true);
    expect(emulator.canAttemptView, false);
  });

  test('experimental ROM handoff never confirms a running game', () {
    final emulator = EmulatorInfo.fromMap({
      'id': 'ppsspp',
      'name': 'PPSSPP',
      'packageName': 'org.ppsspp.ppsspp',
      'installed': true,
      'romLaunch': 'view_unverified',
    });
    expect(emulator.canAttemptView, true);
    final outcome = LaunchOutcome.fromMap({'status': 'handoff_requested_unverified'});
    expect(outcome.confirmedGameStarted, false);
  });

  test('ROM metadata survives a bridge roundtrip', () {
    final rom = RomItem.fromMap({
      'uri': 'content://provider/document/123',
      'name': 'Homebrew.gba',
      'platformId': 'gba',
      'emulatorPackage': 'com.retroarch.aarch64',
      'favorite': 'true',
    });
    expect(rom.platformId, 'gba');
    expect(rom.favorite, true);
    expect(rom.emulatorPackage, 'com.retroarch.aarch64');
  });

  test('legacy records without metadata remain readable', () {
    final rom = RomItem.fromMap({'uri': 'content://doc/1', 'name': 'Game.nes'});
    expect(rom.platformId, null);
    expect(rom.favorite, false);
    expect(rom.emulatorPackage, null);
  });

  test('remote-play client presence does not imply host discovery', () {
    final client = RemoteClient.fromMap({
      'id': 'moonlight',
      'name': 'Moonlight',
      'packageName': 'com.limelight',
      'installed': true,
    });
    expect(client.installed, true);
    expect(client.packageName, 'com.limelight');
  });

  test('collection membership uses stable scoped identifiers', () {
    final collection = GameCollection.fromMap({
      'id': 'collection-123',
      'title': 'Retro',
      'refs': ['rom:content://provider/document/123', 'android:org.example.game'],
    });
    expect(collection.contains('rom:content://provider/document/123'), true);
    expect(collection.contains('remote:com.limelight'), false);
  });

  test('native app identity is the actual package name', () {
    final game = AndroidGame.fromMap({
      'packageName': 'org.example.game',
      'name': 'My game',
    });
    expect(game.packageName, 'org.example.game');
  });
}
