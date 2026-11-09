/// Plain models: no Flutter or Android dependency, so they can be tested alone.
class EmulatorInfo {
  const EmulatorInfo({
    required this.id,
    required this.name,
    required this.packageName,
    required this.installed,
    required this.romLaunch,
    this.versionName,
  });

  final String id;
  final String name;
  final String packageName;
  final bool installed;

  /// One of manual, view_unverified. Never infer core support from package name.
  final String romLaunch;
  final String? versionName;

  factory EmulatorInfo.fromMap(Map<dynamic, dynamic> data) => EmulatorInfo(
        id: data['id'] as String,
        name: data['name'] as String,
        packageName: data['packageName'] as String,
        installed: data['installed'] == true,
        romLaunch: data['romLaunch'] as String? ?? 'manual',
        versionName: data['versionName'] as String?,
      );

  bool get canAttemptView =>
      installed && (romLaunch == 'view_unverified' || romLaunch == 'view_documented');
  bool get documentedIntegration => romLaunch == 'view_documented';
}

class RomItem {
  const RomItem({
    required this.uri,
    required this.name,
    this.platformId,
    this.emulatorPackage,
    this.favorite = false,
    this.coverPath,
    this.labelPath,
    this.retroCorePath,
    this.retroRomPath,
  });

  final String uri;
  final String name;
  final String? platformId;
  final String? emulatorPackage;
  final bool favorite;
  final String? coverPath;
  final String? labelPath;
  final String? retroCorePath;
  final String? retroRomPath;

  factory RomItem.fromMap(Map<dynamic, dynamic> data) => RomItem(
        uri: data['uri'] as String,
        name: data['name'] as String,
        platformId: (data['platformId'] as String?)?.isEmpty == true
            ? null : data['platformId'] as String?,
        emulatorPackage: (data['emulatorPackage'] as String?)?.isEmpty == true
            ? null : data['emulatorPackage'] as String?,
        favorite: data['favorite'] == true || data['favorite'] == 'true',
        coverPath: (data['coverPath'] as String?)?.isEmpty == true
            ? null : data['coverPath'] as String?,
        labelPath: (data['labelPath'] as String?)?.isEmpty == true
            ? null : data['labelPath'] as String?,
        retroCorePath: (data['retroCorePath'] as String?)?.isEmpty == true
            ? null : data['retroCorePath'] as String?,
        retroRomPath: (data['retroRomPath'] as String?)?.isEmpty == true
            ? null : data['retroRomPath'] as String?,
      );
}

class AndroidGame {
  const AndroidGame({required this.packageName, required this.name});

  final String packageName;
  final String name;

  factory AndroidGame.fromMap(Map<dynamic, dynamic> data) => AndroidGame(
        packageName: data['packageName'] as String,
        name: data['name'] as String,
      );
}

class GameCollection {
  const GameCollection({
    required this.id,
    required this.title,
    required this.refs,
  });

  final String id;
  final String title;
  final List<String> refs;

  factory GameCollection.fromMap(Map<dynamic, dynamic> data) => GameCollection(
        id: data['id'] as String,
        title: data['title'] as String,
        refs: (data['refs'] as List<dynamic>).cast<String>(),
      );

  bool contains(String ref) => refs.contains(ref);
}

class GamepadInfo {
  const GamepadInfo({required this.id, required this.name});
  final String id;
  final String name;
  factory GamepadInfo.fromMap(Map<dynamic, dynamic> data) => GamepadInfo(
        id: data['id'] as String, name: data['name'] as String);
}

class RemoteClient {
  const RemoteClient({
    required this.id,
    required this.name,
    required this.packageName,
    required this.installed,
  });

  final String id;
  final String name;
  final String packageName;
  final bool installed;

  factory RemoteClient.fromMap(Map<dynamic, dynamic> data) => RemoteClient(
        id: data['id'] as String,
        name: data['name'] as String,
        packageName: data['packageName'] as String,
        installed: data['installed'] == true,
      );
}

class LaunchOutcome {
  const LaunchOutcome({required this.status, this.detail});

  final String status;
  final String? detail;

  factory LaunchOutcome.fromMap(Map<dynamic, dynamic> data) => LaunchOutcome(
        status: data['status'] as String? ?? 'unknown',
        detail: data['detail'] as String?,
      );

  /// Android intent handoff does not prove that the game actually started.
  bool get confirmedGameStarted => false;
}
