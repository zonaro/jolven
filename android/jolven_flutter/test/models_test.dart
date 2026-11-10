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

  test('local covers and cartridge labels are independent', () {
    final rom = RomItem.fromMap({
      'uri': 'content://a/b', 'name': 'Homebrew.gba',
      'coverPath': '/data/user/0/jolven/files/artwork/a-cover.png',
      'labelPath': '/data/user/0/jolven/files/artwork/a-label.webp',
    });
    expect(rom.coverPath, isNot(equals(rom.labelPath)));
    expect(RomItem.fromMap({
      'uri': 'content://a/b', 'name': 'Homebrew.gba',
      'coverPath': '', 'labelPath': ''
    }).coverPath, null);
  });

  test('advanced RetroArch fields do not imply a verified launch', () {
    final rom = RomItem.fromMap({
      'uri': 'content://rom/123', 'name': 'Homebrew.nes',
      'retroCorePath': '/data/data/com.retroarch/cores/test_libretro_android.so',
      'retroRomPath': '/storage/emulated/0/Roms/Homebrew.nes',
    });
    expect(rom.retroCorePath, endsWith('.so'));
    expect(rom.retroRomPath, startsWith('/'));
    expect(LaunchOutcome.fromMap({'status': 'handoff_requested_unverified'})
        .confirmedGameStarted, false);
  });

  test('native gamepad discovery returns an identifiable device', () {
    final gamepad = GamepadInfo.fromMap({'id': '5', 'name': 'Xbox Wireless Controller'});
    expect(gamepad.id, '5');
    expect(gamepad.name, contains('Xbox'));
  });

  test('save vault records preserve user-provided association and integrity', () {
    final saved = SaveFileRecord.fromMap({
      'id': 'uuid-1',
      'name': 'progress.srm',
      'romUri': 'content://rom/123',
      'sha256': '0123456789abcdef',
      'sizeBytes': '4096',
    });
    expect(saved.name, 'progress.srm');
    expect(saved.sizeBytes, 4096);
    expect(saved.romUri, 'content://rom/123');
  });

  test('screen capture status never implies recording without service state', () {
    final requested = RecordingInfo.fromMap({
      'recording': false,
      'lastVideoUri': '',
      'error': '',
    });
    expect(requested.recording, false);
    expect(requested.lastVideoUri, isEmpty);
    final active = RecordingInfo.fromMap({'recording': true});
    expect(active.recording, true);
  });

  test('ROM fingerprint is only displayed when actually computed', () {
    final fresh = RomItem.fromMap({
      'uri': 'content://provider/rom/1',
      'name': 'homebrew.nes',
    });
    expect(fresh.sha256, null);
    final scanned = RomItem.fromMap({
      'uri': 'content://provider/rom/1',
      'name': 'homebrew.nes',
      'sha256': 'a' * 64,
      'sizeBytes': '123',
    });
    expect(scanned.sha256, 'a' * 64);
    expect(scanned.sizeBytes, 123);
  });

  test('libretro artwork provenance remains distinct from local cover', () {
    final rom = RomItem.fromMap({
      'uri': 'content://game/1',
      'name': 'Homebrew.nes',
      'coverPath': '/data/jolven/cover.png',
      'coverSource': 'https://thumbnails.libretro.com/Nintendo/Named_Boxarts/Homebrew.png',
    });
    expect(rom.coverSource, startsWith('https://'));
    expect(RomItem.fromMap({
      'uri': 'content://game/1', 'name': 'Homebrew.nes',
      'coverPath': '/data/jolven/local.png', 'coverSource': '',
    }).coverSource, null);
  });

  test('native app identity is the actual package name', () {
    final game = AndroidGame.fromMap({
      'packageName': 'org.example.game',
      'name': 'My game',
    });
    expect(game.packageName, 'org.example.game');
  });
}
