import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'src/android_bridge.dart';
import 'src/models.dart';
import 'src/platform_catalog.dart';

void main() => runApp(const JolvenApp());

const _strings = <String, Map<String, String>>{
  'pt': {
    'title': 'Jolven',
    'subtitle': 'Biblioteca e emuladores externos',
    'roms': 'Minhas ROMs',
    'emulators': 'Emuladores instalados',
    'androidGames': 'Jogos Android',
    'addAndroid': 'Adicionar app instalado',
    'remote': 'Remote Play',
    'noRemote': 'Instale Moonlight, Steam Link ou outro cliente de streaming.',
    'openRemote': 'Abrir cliente',
    'noGames': 'Nenhum jogo Android detectado (a classificação do sistema pode omitir alguns).',
    'openGame': 'Abrir jogo',
    'import': 'Importar ROM',
    'importFiles': 'Selecionar arquivos',
    'importFolder': 'Importar pasta',
    'platform': 'Definir console',
    'favorite': 'Adicionar aos favoritos',
    'unfavorite': 'Remover dos favoritos',
    'preferred': 'Emulador preferido',
    'unknownPlatform': 'Console ainda não selecionado',
    'favoritesOnly': 'Somente favoritos',
    'allGames': 'Todos',
    'imported': 'Arquivos adicionados à biblioteca',
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
    'androidGames': 'Android games',
    'addAndroid': 'Add installed app',
    'remote': 'Remote Play',
    'noRemote': 'Install Moonlight, Steam Link or another streaming client.',
    'openRemote': 'Open client',
    'noGames': 'No Android games found (system classification may omit some).',
    'openGame': 'Open game',
    'import': 'Import ROM',
    'importFiles': 'Select files',
    'importFolder': 'Import folder',
    'platform': 'Set console',
    'favorite': 'Add to favorites',
    'unfavorite': 'Remove from favorites',
    'preferred': 'Preferred emulator',
    'unknownPlatform': 'Console not selected',
    'favoritesOnly': 'Favorites only',
    'allGames': 'All',
    'imported': 'Files added to library',
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
    'androidGames': 'Juegos Android',
    'addAndroid': 'Agregar app instalada',
    'remote': 'Juego remoto',
    'noRemote': 'Instala Moonlight, Steam Link u otro cliente de streaming.',
    'openRemote': 'Abrir cliente',
    'noGames': 'No se encontraron juegos Android (la clasificación puede omitir algunos).',
    'openGame': 'Abrir juego',
    'import': 'Importar ROM',
    'importFiles': 'Seleccionar archivos',
    'importFolder': 'Importar carpeta',
    'platform': 'Elegir consola',
    'favorite': 'Agregar a favoritos',
    'unfavorite': 'Quitar de favoritos',
    'preferred': 'Emulador preferido',
    'unknownPlatform': 'Consola sin seleccionar',
    'favoritesOnly': 'Solo favoritos',
    'allGames': 'Todos',
    'imported': 'Archivos añadidos a biblioteca',
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
  List<AndroidGame> _androidGames = [];
  List<RemoteClient> _remoteClients = [];
  bool _loading = false;
  bool _favoritesOnly = false;

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
      final androidGames = await _bridge.listAndroidGames();
      final remoteClients = await _bridge.listRemoteClients();
      if (!mounted) return;
      setState(() {
        _emulators = emulators;
        _roms = roms;
        _androidGames = androidGames;
        _remoteClients = remoteClients;
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
    final mode = await showModalBottomSheet<String>(
      context: context,
      builder: (sheetContext) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(
            leading: const Icon(Icons.file_open),
            title: Text(_t('importFiles')),
            onTap: () => Navigator.pop(sheetContext, 'files'),
          ),
          ListTile(
            leading: const Icon(Icons.folder_open),
            title: Text(_t('importFolder')),
            onTap: () => Navigator.pop(sheetContext, 'folder'),
          ),
        ]),
      ),
    );
    if (mode == null) return;
    try {
      final selected = mode == 'folder'
          ? await _bridge.importFolder()
          : await _bridge.importRoms();
      if (selected.isNotEmpty && mounted) _message('${_t('imported')}: ${selected.length}');
      if (mounted) await _refresh();
    } catch (error) {
      if (mounted) _message('${_t('error')}: $error');
    }
  }

  Future<void> _setPlatform(RomItem rom) async {
    final selected = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => SafeArea(
        child: SizedBox(
          height: MediaQuery.sizeOf(context).height * 0.7,
          child: ListView(children: [
            ListTile(title: Text(_t('platform'))),
            for (final platform in platforms)
              ListTile(
                title: Text(platform.label),
                onTap: () => Navigator.pop(sheetContext, platform.id),
              ),
          ]),
        ),
      ),
    );
    if (selected == null) return;
    try {
      await _bridge.updateRom(rom, platformId: selected);
      if (mounted) await _refresh();
    } catch (error) {
      if (mounted) _message('${_t('error')}: $error');
    }
  }

  Future<void> _setPreferred(RomItem rom) async {
    final installed = _emulators.where((e) => e.installed).toList();
    if (installed.isEmpty) {
      _message(_t('none'));
      return;
    }
    final selected = await showModalBottomSheet<EmulatorInfo>(
      context: context,
      builder: (sheetContext) => SafeArea(
        child: ListView(shrinkWrap: true, children: [
          ListTile(title: Text(_t('preferred'))),
          for (final emulator in installed)
            ListTile(
              title: Text(emulator.name),
              onTap: () => Navigator.pop(sheetContext, emulator),
            ),
        ]),
      ),
    );
    if (selected == null) return;
    try {
      await _bridge.updateRom(rom, emulatorPackage: selected.packageName);
      if (mounted) await _refresh();
    } catch (error) {
      if (mounted) _message('${_t('error')}: $error');
    }
  }

  Future<void> _toggleFavorite(RomItem rom) async {
    try {
      await _bridge.updateRom(rom, favorite: !rom.favorite);
      if (mounted) await _refresh();
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

  Future<void> _addAndroidApp() async {
    try {
      final apps = await _bridge.listLaunchableApps();
      if (!mounted) return;
      final selected = await showModalBottomSheet<AndroidGame>(
        context: context,
        isScrollControlled: true,
        builder: (sheetContext) => SafeArea(
          child: SizedBox(
            height: MediaQuery.sizeOf(context).height * 0.65,
            child: ListView(children: [
              ListTile(title: Text(_t('addAndroid'))),
              for (final app in apps)
                ListTile(
                  leading: const Icon(Icons.apps),
                  title: Text(app.name),
                  subtitle: Text(app.packageName),
                  onTap: () => Navigator.pop(sheetContext, app),
                ),
            ]),
          ),
        ),
      );
      if (selected == null) return;
      await _bridge.addAndroidGame(selected);
      if (mounted) await _refresh();
    } catch (error) {
      if (mounted) _message('${_t('error')}: $error');
    }
  }

  Future<void> _openRemoteClient(RemoteClient client) async {
    try {
      final outcome = await _bridge.openRemoteClient(client);
      if (mounted && outcome.status != 'client_opened') _message(_t('missing'));
    } catch (error) {
      if (mounted) _message('${_t('error')}: $error');
    }
  }

  Future<void> _openAndroidGame(AndroidGame game) async {
    try {
      final result = await _bridge.openAndroidGame(game);
      if (mounted && result.status != 'game_opened') _message(_t('missing'));
    } catch (error) {
      if (mounted) _message('${_t('error')}: $error');
    }
  }

  Future<void> _chooseEmulator(RomItem rom) async {
    final installed = _emulators.where((e) => e.installed).toList()
      ..sort((a, b) {
        final aPreferred = a.packageName == rom.emulatorPackage ? 0 : 1;
        final bPreferred = b.packageName == rom.emulatorPackage ? 0 : 1;
        return aPreferred.compareTo(bPreferred);
      });
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
            Text(_t('androidGames'), style: Theme.of(context).textTheme.titleLarge),
            Row(children: [
              Expanded(child: TextButton.icon(
                onPressed: _addAndroidApp,
                icon: const Icon(Icons.add_circle_outline),
                label: Text(_t('addAndroid')),
              )),
            ]),
            if (_androidGames.isEmpty) ListTile(title: Text(_t('noGames'))),
            for (final game in _androidGames)
              ListTile(
                leading: const Icon(Icons.smartphone),
                title: Text(game.name),
                subtitle: Text(game.packageName),
                trailing: TextButton(
                  onPressed: () => _openAndroidGame(game),
                  child: Text(_t('openGame')),
                ),
              ),
            const SizedBox(height: 24),
            Text(_t('remote'), style: Theme.of(context).textTheme.titleLarge),
            if (!_remoteClients.any((client) => client.installed))
              ListTile(title: Text(_t('noRemote'))),
            for (final client in _remoteClients.where((client) => client.installed))
              ListTile(
                leading: const Icon(Icons.cast_connected),
                title: Text(client.name),
                trailing: TextButton(
                  onPressed: () => _openRemoteClient(client),
                  child: Text(_t('openRemote')),
                ),
              ),
            const SizedBox(height: 24),
            Text(_t('roms'), style: Theme.of(context).textTheme.titleLarge),
            if (_roms.isEmpty) ListTile(title: Text(_t('empty'))),
            SwitchListTile(
              title: Text(_t('favoritesOnly')),
              value: _favoritesOnly,
              onChanged: (checked) => setState(() => _favoritesOnly = checked),
            ),
            for (final rom in _roms.where((rom) => !_favoritesOnly || rom.favorite))
              Card(
                child: ListTile(
                  leading: Icon(rom.favorite ? Icons.favorite : Icons.videogame_asset),
                  title: Text(rom.name),
                  subtitle: Text(
                    rom.platformId == null
                        ? (identifyPlatform(rom.name).confidentId == null
                            ? _t('unknownPlatform')
                            : platformLabel(identifyPlatform(rom.name).confidentId))
                        : platformLabel(rom.platformId),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  onTap: () => _chooseEmulator(rom),
                  trailing: PopupMenuButton<String>(
                    onSelected: (value) {
                      if (value == 'play') _chooseEmulator(rom);
                      if (value == 'platform') _setPlatform(rom);
                      if (value == 'preferred') _setPreferred(rom);
                      if (value == 'favorite') _toggleFavorite(rom);
                      if (value == 'remove') _remove(rom);
                    },
                    itemBuilder: (context) => [
                      PopupMenuItem(value: 'play', child: Text(_t('play'))),
                      PopupMenuItem(value: 'platform', child: Text(_t('platform'))),
                      PopupMenuItem(value: 'preferred', child: Text(_t('preferred'))),
                      PopupMenuItem(value: 'favorite', child: Text(
                        _t(rom.favorite ? 'unfavorite' : 'favorite'))),
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
