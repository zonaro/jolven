import 'models.dart';
import 'platform_catalog.dart';

/// External emulator heuristics, NOT an assertion of successful game launch.
/// This catalog does not contain emulation engines, cores or proprietary data.
enum EmulatorFit {
  documentedIntent,
  experimentalIntent,
  retroArchPathsUnverified,
  manualOnly,
  unknownSystem,
  differentSystem,
}

const _knownPlatforms = <String, Set<String>>{
  'ppsspp': {'psp'},
  'ppsspp-legacy': {'psp'},
  'ppssppgold': {'psp'},
  'dolphin': {'gc', 'wii'},
  'mupen64': {'n64'},
  'duckstation': {'ps1'},
  'azahar': {'3ds'},
  'drastic': {'nds'},
};

const _retroArchPlatforms = <String>{
  'nes', 'snes', 'gb', 'gbc', 'gba', 'n64', 'nds', 'genesis', 'sms',
  'gg', 'ps1', 'psp', 'saturn', 'dreamcast', 'pce', 'atari2600',
  'atari7800', 'arcade', 'c64',
};

String? romPlatformId(RomItem rom) =>
    rom.platformId ?? identifyPlatform(rom.name).confidentId;

/// These are recommendations about console families, not installed cores.
/// If the format/console cannot be identified, no compatibility is claimed.
EmulatorFit emulatorFit(RomItem rom, EmulatorInfo emulator) {
  final platform = romPlatformId(rom);
  if (platform == null) return EmulatorFit.unknownSystem;
  final supported = emulator.id.startsWith('retroarch')
      ? _retroArchPlatforms
      : _knownPlatforms[emulator.id];
  if (supported == null || !supported.contains(platform)) {
    return EmulatorFit.differentSystem;
  }
  if (emulator.id.startsWith('retroarch')) {
    return rom.retroCorePath?.isNotEmpty == true &&
            rom.retroRomPath?.isNotEmpty == true
        ? EmulatorFit.retroArchPathsUnverified
        : EmulatorFit.manualOnly;
  }
  if (emulator.romLaunch == 'view_documented') {
    return EmulatorFit.documentedIntent;
  }
  if (emulator.romLaunch == 'view_unverified') {
    return EmulatorFit.experimentalIntent;
  }
  return EmulatorFit.manualOnly;
}

/// Per-game preference outranks per-console default, neither overrides
/// whether an external emulator is actually installed or compatible.
List<EmulatorInfo> rankEmulators(
  RomItem rom,
  Iterable<EmulatorInfo> emulators, {
  Map<String, String> consoleDefaults = const {},
}) {
  final platform = romPlatformId(rom);
  final preferredConsolePackage =
      platform == null ? null : consoleDefaults[platform];

  final candidates = emulators.where((e) => e.installed).toList();
  int rank(EmulatorInfo emulator) {
    final fit = emulatorFit(rom, emulator);
    final fitScore = switch (fit) {
      EmulatorFit.documentedIntent => 0,
      EmulatorFit.retroArchPathsUnverified => 1,
      EmulatorFit.experimentalIntent => 2,
      EmulatorFit.manualOnly => 3,
      EmulatorFit.unknownSystem => 4,
      EmulatorFit.differentSystem => 5,
    };
    // A stale preference for a different console must not outrank
    // compatible emulators. Users can still open it manually.
    if (fit == EmulatorFit.differentSystem) return 100 + fitScore;
    if (emulator.packageName == rom.emulatorPackage) return fitScore - 40;
    if (emulator.packageName == preferredConsolePackage) return fitScore - 20;
    return fitScore;
  }

  candidates.sort((a, b) {
    final byRank = rank(a).compareTo(rank(b));
    return byRank != 0 ? byRank :
      a.name.toLowerCase().compareTo(b.name.toLowerCase());
  });
  return candidates;
}
