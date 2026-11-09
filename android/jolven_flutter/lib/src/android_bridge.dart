import 'package:flutter/services.dart';

import 'models.dart';

/// Only a bridge to Android's public APIs. No RetroArch/libretro engine.
class AndroidBridge {
  const AndroidBridge();

  static const MethodChannel _channel = MethodChannel('jolven/external_emulators');

  Future<List<EmulatorInfo>> listEmulators() async {
    final rows = await _channel.invokeMethod<List<dynamic>>('listEmulators') ?? [];
    return rows.map((row) => EmulatorInfo.fromMap(row as Map)).toList();
  }

  Future<List<RomItem>> listRoms() async {
    final rows = await _channel.invokeMethod<List<dynamic>>('listRoms') ?? [];
    return rows.map((row) => RomItem.fromMap(row as Map)).toList();
  }

  /// Uses ACTION_OPEN_DOCUMENT and persists the user-granted read URI.
  Future<RomItem?> importRom() async {
    final row = await _channel.invokeMethod<Map<dynamic, dynamic>>('importRom');
    return row == null ? null : RomItem.fromMap(row);
  }

  Future<List<AndroidGame>> listAndroidGames() async {
    final rows = await _channel.invokeMethod<List<dynamic>>('listAndroidGames') ?? [];
    return rows.map((row) => AndroidGame.fromMap(row as Map)).toList();
  }

  Future<LaunchOutcome> openAndroidGame(AndroidGame game) async {
    final row = await _channel.invokeMethod<Map<dynamic, dynamic>>(
      'openAndroidGame', {'packageName': game.packageName});
    return LaunchOutcome.fromMap(row ?? {});
  }

  Future<void> removeRom(RomItem rom) async {
    // Removes only Jolven's catalog entry, never the original user file.
    await _channel.invokeMethod<void>('removeRom', {'uri': rom.uri});
  }

  Future<LaunchOutcome> launchRom(RomItem rom, EmulatorInfo emulator) async {
    final row = await _channel.invokeMethod<Map<dynamic, dynamic>>('launchRom', {
      'uri': rom.uri,
      'packageName': emulator.packageName,
    });
    return LaunchOutcome.fromMap(row ?? {});
  }

  Future<LaunchOutcome> openEmulator(EmulatorInfo emulator) async {
    final row = await _channel.invokeMethod<Map<dynamic, dynamic>>(
      'openEmulator',
      {'packageName': emulator.packageName},
    );
    return LaunchOutcome.fromMap(row ?? {});
  }
}
