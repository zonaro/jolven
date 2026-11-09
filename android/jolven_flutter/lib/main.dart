import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'src/android_bridge.dart';
import 'src/models.dart';

void main() => runApp(const JolvenApp());

const _strings = <String, Map<String, String>>{
  'pt': {
    'title': 'Jolven',
    'subtitle': 'Biblioteca e emuladores externos',
    'roms': 'Minhas ROMs',
    'emulators': 'Emuladores instalados',
    'import': 'Importar ROM',
    'refresh': 'Atualizar',
    'empty': 'Importe uma ROM de sua propriedade para começar.',
    'none': 'Nenhum emulador compatível detectado. Instale um separadamente.',
    'play': 'Jogar',
    'open': 'Abrir emulador',
    'remove': 'Remover da biblioteca',
    'cancel': 'Cancelar',
    'manual': 'Abra o emulador e selecione a ROM manualmente.',
    'unverified': 'A solicitação foi enviada. Confirme no emulador se o jogo abriu.',
    'missing': 'Emulador ausente ou indisponível.',
    'unsupported': 'A abertura direta não é suportada ou não foi verificada.',
    'noAccess': 'Arquivo inacessível: importe novamente para conceder acesso.',
    'error': 'Falha na operação',
    'select': 'Escolha um emulador instalado',
    'experimental': 'Tentar abrir ROM (experimental)',
    'note': 'O Jolven não inclui emuladores, cores, jogos ou BIOS.',
  },
  'en': {
    'title': 'Jolven',
    'subtitle': 'Library and external emulators',
    'roms': 'My ROMs',
    'emulators': 'Installed emulators',
    'import': 'Import ROM',
    'refresh': 'Refresh',
    'empty': 'Import a ROM you own to get started.',
    'none': 'No compatible emulator found. Install one separately.',
    'play': 'Play',
    'open': 'Open emulator',
    'remove': 'Remove from library',
    'cancel': 'Cancel',
    'manual': 'Open the emulator and select the ROM manually.',
    'unverified': 'Request sent. Check in the emulator whether the game opened.',
    'missing': 'Emulator missing or unavailable.',
    'unsupported': 'Direct launch is unsupported or unverified.',
    'noAccess': 'File unavailable: import it again to grant access.',
    'error': 'Operation failed',
    'select': 'Choose an installed emulator',
    'experimental': 'Try opening ROM (experimental)',
    'note': 'Jolven does not include emulators, cores, games or BIOS.',
  },
  'es': {
    'title': 'Jolven',
    'subtitle': 'Biblioteca y emuladores externos',
    'roms': 'Mis ROMs',
    'emulators': 'Emuladores instalados',
    'import': 'Importar ROM',
    'refresh': 'Actualizar',
    'empty': 'Importa una ROM propia para comenzar.',
    'none': 'No hay emuladores compatibles. Instala uno por separado.',
    'play': 'Jugar',
    'open': 'Abrir emulador',
    'remove': 'Quitar de la biblioteca',
    'cancel': 'Cancelar',
    'manual': 'Abre el emulador y selecciona la ROM manualmente.',
    'unverified': 'Solicitud enviada. Comprueba si el juego se abrió.',
    'missing': 'Emulador ausente o no disponible.',
    'unsupported': 'El inicio directo no es compatible o no está verificado.',
    'noAccess': 'Archivo inaccesible: impórtalo otra vez.',
    'error': 'Error en la operación',
    'select': 'Elige un emulador instalado',
    'experimental': 'Intentar abrir ROM (experimental)',
    'note': 'Jolven no incluye emuladores, núcleos, juegos ni BIOS.',
  },
};

class JolvenApp extends StatelessWidget {
  const JolvenApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Jolven',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          useMaterial3: true,
          brightness: Brightness.dark,
          colorSchemeSeed: const Color(0xFF9C75ED),
        ),
        supportedLocales: const [Locale('pt'), Locale('en'), Locale('es')],
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        home: const JolvenHome(),
      );
}

class JolvenHome extends StatefulWidget {
  const JolvenHome({super.key});

  @override
  State<JolvenHome> createState() => _JolvenHomeState();
}

class _JolvenHomeState extends State<JolvenHome> {
  final _bridge = const AndroidBridge();
  List<EmulatorInfo> _emulators = [];
  List<RomItem> _roms = [];
  bool _loading = false;

  String _t(String key) {
    final language = Localizations.localeOf(context).languageCode;
    return (_strings[language] ?? _strings['pt']!)[key] ?? key;
  }

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    if (_loading) return;
    setState(() => _loading = true);
    try {
      final emulators = await _bridge.listEmulators();
      final roms = await _bridge.listRoms();
      if (!mounted) return;
      setState(() {
        _emulators = emulators;
        _roms = roms;
      });
    } catch (error) {
      if (mounted) _message('${_t('error')}: $error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _message(String value) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(value), duration: const Duration(seconds: 5)),
    );
  }

  Future<void> _import() async {
    try {
      final selected = await _bridge.importRom();
      if (selected != null) await _refresh();
    } catch (error) {
      if (mounted) _message('${_t('error')}: $error');
    }
  }

  Future<void> _remove(RomItem rom) async {
    try {
      await _bridge.removeRom(rom);
      await _refresh();
    } catch (error) {
      if (mounted) _message('${_t('error')}: $error');
    }
  }

  Future<void> _openEmulator(EmulatorInfo emulator) async {
    try {
      final outcome = await _bridge.openEmulator(emulator);
      if (!mounted) return;
      _message(outcome.status == 'emulator_opened' ? _t('manual') : _t('missing'));
    } catch (error) {
      if (mounted) _message('${_t('error')}: $error');
    }
  }

  Future<void> _chooseEmulator(RomItem rom) async {
    final installed = _emulators.where((e) => e.installed).toList();
    if (installed.isEmpty) {
      _message(_t('none'));
      return;
    }
    final choice = await showModalBottomSheet<EmulatorInfo>(
      context: context,
      builder: (sheetContext) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            ListTile(title: Text(_t('select'))),
            for (final e in installed)
              ListTile(
                leading: const Icon(Icons.sports_esports_outlined),
                title: Text(e.name),
                subtitle: Text(e.canAttemptView ? _t('experimental') : _t('manual')),
                onTap: () => Navigator.pop(sheetContext, e),
              ),
          ],
        ),
      ),
    );
    if (choice == null || !mounted) return;
    try {
      final outcome = await _bridge.launchRom(rom, choice);
      if (!mounted) return;
      final key = switch (outcome.status) {
        'handoff_requested_unverified' => 'unverified',
        'manual_only' => 'manual',
        'no_file_permission' => 'noAccess',
        'missing' => 'missing',
        _ => 'unsupported',
      };
      _message(_t(key));
      if (key == 'manual' || key == 'unsupported') {
        await _openEmulator(choice);
      }
    } catch (error) {
      if (mounted) _message('${_t('error')}: $error');
    }
  }

  @override
  Widget build(BuildContext context) {
    final installed = _emulators.where((e) => e.installed).toList();
    return Scaffold(
      appBar: AppBar(
        title: Text(_t('title')),
        actions: [
          IconButton(
            tooltip: _t('refresh'),
            onPressed: _loading ? null : _refresh,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _loading ? null : _import,
        icon: const Icon(Icons.add),
        label: Text(_t('import')),
      ),
      body: FocusTraversalGroup(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 100),
          children: [
            Text(_t('subtitle'), style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            Text(_t('note'), style: Theme.of(context).textTheme.bodySmall),
            if (_loading) const LinearProgressIndicator(),
            const SizedBox(height: 24),
            Text(_t('roms'), style: Theme.of(context).textTheme.titleLarge),
            if (_roms.isEmpty) ListTile(title: Text(_t('empty'))),
            for (final rom in _roms)
              Card(
                child: ListTile(
                  leading: const Icon(Icons.videogame_asset),
                  title: Text(rom.name),
                  subtitle: Text(rom.uri, maxLines: 1, overflow: TextOverflow.ellipsis),
                  onTap: () => _chooseEmulator(rom),
                  trailing: PopupMenuButton<String>(
                    onSelected: (value) {
                      if (value == 'play') _chooseEmulator(rom);
                      if (value == 'remove') _remove(rom);
                    },
                    itemBuilder: (context) => [
                      PopupMenuItem(value: 'play', child: Text(_t('play'))),
                      PopupMenuItem(value: 'remove', child: Text(_t('remove'))),
                    ],
                  ),
                ),
              ),
            const SizedBox(height: 20),
            Text(_t('emulators'), style: Theme.of(context).textTheme.titleLarge),
            if (installed.isEmpty) ListTile(title: Text(_t('none'))),
            for (final emulator in installed)
              ListTile(
                leading: const Icon(Icons.gamepad_outlined),
                title: Text(emulator.name),
                subtitle: Text(emulator.packageName),
                trailing: TextButton(
                  onPressed: () => _openEmulator(emulator),
                  child: Text(_t('open')),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
