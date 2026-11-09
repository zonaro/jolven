/// Plain models: no Flutter or Android dependency, so they can be tested alone.
class EmulatorInfo {
  const EmulatorInfo({
    required this.id,
    required this.name,
    required this.packageName,
    required this.installed,
    required this.romLaunch,
  });

  final String id;
  final String name;
  final String packageName;
  final bool installed;

  /// One of manual, view_unverified. Never infer core support from package name.
  final String romLaunch;

  factory EmulatorInfo.fromMap(Map<dynamic, dynamic> data) => EmulatorInfo(
        id: data['id'] as String,
        name: data['name'] as String,
        packageName: data['packageName'] as String,
        installed: data['installed'] == true,
        romLaunch: data['romLaunch'] as String? ?? 'manual',
      );

  bool get canAttemptView => installed && romLaunch == 'view_unverified';
}

class RomItem {
  const RomItem({required this.uri, required this.name});

  final String uri;
  final String name;

  factory RomItem.fromMap(Map<dynamic, dynamic> data) => RomItem(
        uri: data['uri'] as String,
        name: data['name'] as String,
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
