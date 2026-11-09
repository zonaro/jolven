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

  Future<List<RomItem>> importRoms() async {
    final rows = await _channel.invokeMethod<List<dynamic>>('importRoms') ?? [];
    return rows.map((row) => RomItem.fromMap(row as Map)).toList();
  }

  Future<List<RomItem>> importFolder() async {
    final rows = await _channel.invokeMethod<List<dynamic>>('importFolder') ?? [];
    return rows.map((row) => RomItem.fromMap(row as Map)).toList();
  }

  Future<void> updateRom(RomItem rom, {
    String? platformId,
    String? emulatorPackage,
    bool? favorite,
    String? retroCorePath,
    String? retroRomPath,
  }) async {
    await _channel.invokeMethod<void>('updateRom', {
      'uri': rom.uri,
      if (platformId != null) 'platformId': platformId,
      if (emulatorPackage != null) 'emulatorPackage': emulatorPackage,
      if (favorite != null) 'favorite': favorite,
      if (retroCorePath != null) 'retroCorePath': retroCorePath,
      if (retroRomPath != null) 'retroRomPath': retroRomPath,
    });
  }

  Future<String?> pickArtwork(RomItem rom, String kind) async {
    return _channel.invokeMethod<String>('pickArtwork', {
      'uri': rom.uri, 'kind': kind,
    });
  }

  Future<bool> clearArtwork(RomItem rom, String kind) async {
    return await _channel.invokeMethod<bool>('clearArtwork', {
      'uri': rom.uri, 'kind': kind,
    }) ?? false;
  }

  Future<List<GameCollection>> listCollections() async {
    final rows = await _channel.invokeMethod<List<dynamic>>('listCollections') ?? [];
    return rows.map((row) => GameCollection.fromMap(row as Map)).toList();
  }

  Future<GameCollection> createCollection(String title) async {
    final data = await _channel.invokeMethod<Map<dynamic, dynamic>>(
      'createCollection', {'title': title});
    return GameCollection.fromMap(data!);
  }

  Future<void> renameCollection(GameCollection collection, String title) async {
    final ok = await _channel.invokeMethod<bool>(
      'renameCollection', {'id': collection.id, 'title': title});
    if (ok != true) throw StateError('Could not rename collection');
  }

  Future<void> deleteCollection(GameCollection collection) async {
    final ok = await _channel.invokeMethod<bool>(
      'deleteCollection', {'id': collection.id});
    if (ok != true) throw StateError('Could not delete collection');
  }

  Future<bool> toggleCollectionMember(GameCollection collection, String ref) async {
    return await _channel.invokeMethod<bool>(
          'toggleCollectionMember', {'id': collection.id, 'ref': ref}) ??
        false;
  }

  Future<List<AndroidGame>> listAndroidGames() async {
    final rows = await _channel.invokeMethod<List<dynamic>>('listAndroidGames') ?? [];
    return rows.map((row) => AndroidGame.fromMap(row as Map)).toList();
  }

  Future<List<AndroidGame>> listLaunchableApps() async {
    final rows = await _channel.invokeMethod<List<dynamic>>('listLaunchableApps') ?? [];
    return rows.map((row) => AndroidGame.fromMap(row as Map)).toList();
  }

  Future<void> addAndroidGame(AndroidGame game) async {
    final result = await _channel.invokeMethod<Map<dynamic, dynamic>>(
      'addAndroidGame', {'packageName': game.packageName});
    if (result?['status'] != 'added') {
      throw PlatformException(code: 'GAME_NOT_FOUND', message: game.packageName);
    }
  }

  Future<List<GamepadInfo>> listGamepads() async {
    final rows = await _channel.invokeMethod<List<dynamic>>('listGamepads') ?? [];
    return rows.map((row) => GamepadInfo.fromMap(row as Map)).toList();
  }

  Future<LaunchOutcome> openRetroArchGuide() async {
    final row = await _channel.invokeMethod<Map<dynamic, dynamic>>('openRetroArchGuide');
    return LaunchOutcome.fromMap(row ?? {});
  }

  Future<List<RemoteClient>> listRemoteClients() async {
    final rows = await _channel.invokeMethod<List<dynamic>>('listRemoteClients') ?? [];
    return rows.map((row) => RemoteClient.fromMap(row as Map)).toList();
  }

  Future<LaunchOutcome> openRemoteClient(RemoteClient client) async {
    final result = await _channel.invokeMethod<Map<dynamic, dynamic>>(
      'openRemoteClient', {'packageName': client.packageName});
    return LaunchOutcome.fromMap(result ?? {});
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
      if (rom.retroCorePath != null) 'retroCorePath': rom.retroCorePath,
      if (rom.retroRomPath != null) 'retroRomPath': rom.retroRomPath,
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
