/// Local, offline console identification. Derived from the Kwiq Gaming approach,
/// intentionally curated: a file extension is only a hint, not a verified ROM.
class ConsolePlatform {
  const ConsolePlatform(this.id, this.label, this.extensions);
  final String id;
  final String label;
  final Set<String> extensions;
}

const platforms = <ConsolePlatform>[
  ConsolePlatform('nes', 'Nintendo NES', {'nes', 'fds'}),
  ConsolePlatform('snes', 'Super Nintendo', {'sfc', 'smc', 'fig'}),
  ConsolePlatform('gb', 'Game Boy', {'gb'}),
  ConsolePlatform('gbc', 'Game Boy Color', {'gbc'}),
  ConsolePlatform('gba', 'Game Boy Advance', {'gba'}),
  ConsolePlatform('n64', 'Nintendo 64', {'n64', 'z64', 'v64'}),
  ConsolePlatform('nds', 'Nintendo DS', {'nds', 'dsi'}),
  ConsolePlatform('3ds', 'Nintendo 3DS', {'3ds', 'cci', 'cxi'}),
  ConsolePlatform('gc', 'GameCube', {'gcm', 'gcz', 'rvz'}),
  ConsolePlatform('wii', 'Nintendo Wii', {'wbfs', 'rvz'}),
  ConsolePlatform('genesis', 'Mega Drive / Genesis', {'md', 'smd', 'gen'}),
  ConsolePlatform('sms', 'Master System', {'sms'}),
  ConsolePlatform('gg', 'Game Gear', {'gg'}),
  ConsolePlatform('ps1', 'PlayStation', {'ccd', 'pbp', 'chd', 'bin', 'cue', 'img', 'iso'}),
  ConsolePlatform('ps2', 'PlayStation 2', {'chd', 'bin', 'cue', 'iso'}),
  ConsolePlatform('psp', 'PSP', {'cso', 'pbp', 'iso'}),
  ConsolePlatform('saturn', 'Saturn', {'chd', 'bin', 'cue', 'iso'}),
  ConsolePlatform('dreamcast', 'Dreamcast', {'gdi', 'chd', 'bin', 'cue'}),
  ConsolePlatform('pce', 'PC Engine', {'pce', 'chd', 'cue'}),
  ConsolePlatform('atari2600', 'Atari 2600', {'a26'}),
  ConsolePlatform('atari7800', 'Atari 7800', {'a78'}),
  ConsolePlatform('arcade', 'Arcade', {'zip', '7z', 'chd'}),
  ConsolePlatform('c64', 'Commodore 64', {'d64', 't64', 'prg'}),
];

/// Archives and common disc images need identification by user; don't guess.
const ambiguousExtensions = {'zip', '7z', 'rar', 'iso', 'bin', 'cue', 'chd', 'pbp', 'rvz'};

class PlatformMatch {
  const PlatformMatch(this.extension, this.candidates);
  final String extension;
  final List<ConsolePlatform> candidates;

  bool get requiresChoice => candidates.length != 1 || ambiguousExtensions.contains(extension);
  String? get confidentId => requiresChoice ? null : candidates.single.id;
  bool get isUnknown => candidates.isEmpty;
}

PlatformMatch identifyPlatform(String fileName) {
  final leaf = fileName.split(RegExp(r'[/\\]')).last;
  final point = leaf.lastIndexOf('.');
  if (point <= 0 || point == leaf.length - 1) {
    return const PlatformMatch('', []);
  }
  final extension = leaf.substring(point + 1).toLowerCase();
  final candidates = platforms.where((p) => p.extensions.contains(extension)).toList();
  return PlatformMatch(extension, candidates);
}

String platformLabel(String? id) {
  if (id == null || id.isEmpty) return '—';
  for (final p in platforms) {
    if (p.id == id) return p.label;
  }
  return id;
}
