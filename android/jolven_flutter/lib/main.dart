import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'src/android_bridge.dart';
import 'src/models.dart';
import 'src/platform_catalog.dart';
import 'src/patcher_page.dart';
import 'src/save_vault_page.dart';

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
    'setCover': 'Escolher capa local',
    'setLabel': 'Escolher etiqueta de cartucho',
    'clearCover': 'Remover capa',
    'clearLabel': 'Remover etiqueta',
    'useLabels': 'Exibir etiquetas',
    'favorite': 'Adicionar aos favoritos',
    'unfavorite': 'Remover dos favoritos',
    'preferred': 'Emulador preferido',
    'retroAdvanced': 'RetroArch: caminhos avançados',
    'retroWarning': 'Use apenas caminhos obtidos na configuração do RetroArch. Não é possível verificar os cores de outro app; um caminho errado pode causar tela preta.',
    'retroCore': 'Caminho absoluto do core (.so)',
    'retroRom': 'Caminho absoluto da ROM acessível ao RetroArch',
    'retroReady': 'Tentativa de abertura por intent (não verificada)',

    'unknownPlatform': 'Console ainda não selecionado',
    'favoritesOnly': 'Somente favoritos',
    'collections': 'Coleções',
    'newCollection': 'Nova coleção',
    'renameCollection': 'Renomear coleção',
    'deleteCollection': 'Excluir coleção',
    'addToCollection': 'Adicionar/remover da coleção',
    'collectionName': 'Nome da coleção',
    'save': 'Salvar',
    'delete': 'Excluir',
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
    'documented': 'Abertura documentada (confirmar no emulador)',
    'retroGuide': 'Configurar RetroArch externo',
    'retroGuideBody': 'Instale o RetroArch por um canal oficial e selecione os cores dentro dele. O Jolven não consegue confirmar se o core está instalado nem lê arquivos privados.',
    'coreUnverified': 'Core não verificado',
    'openGuide': 'Abrir guia oficial',
    'search': 'Buscar jogos',
    'allPlatforms': 'Todos os consoles',
    'viewList': 'Lista',
    'viewCover': 'Capas',
    'viewLabel': 'Cartuchos',
    'gamepads': 'Controles conectados',
    'noGamepads': 'Nenhum gamepad detectado',
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
    'setCover': 'Choose local cover',
    'setLabel': 'Choose cartridge label',
    'clearCover': 'Remove cover',
    'clearLabel': 'Remove label',
    'useLabels': 'Show labels',
    'favorite': 'Add to favorites',
    'unfavorite': 'Remove from favorites',
    'preferred': 'Preferred emulator',
    'retroAdvanced': 'RetroArch: advanced paths',
    'retroWarning': 'Use paths found inside RetroArch settings. Jolven cannot check another app’s cores; wrong paths may cause a black screen.',
    'retroCore': 'Absolute core path (.so)',
    'retroRom': 'Absolute ROM path readable by RetroArch',
    'retroReady': 'Attempt launch via intent (unverified)',

    'unknownPlatform': 'Console not selected',
    'favoritesOnly': 'Favorites only',
    'collections': 'Collections',
    'newCollection': 'New collection',
    'renameCollection': 'Rename collection',
    'deleteCollection': 'Delete collection',
    'addToCollection': 'Add/remove from collection',
    'collectionName': 'Collection name',
    'save': 'Save',
    'delete': 'Delete',
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
    'documented': 'Documented launch (verify in emulator)',
    'retroGuide': 'Set up external RetroArch',
    'retroGuideBody': 'Install RetroArch from an official source and choose cores inside it. Jolven cannot verify installed cores or read private app files.',
    'coreUnverified': 'Core not verified',
    'openGuide': 'Open official guide',
    'search': 'Search games',
    'allPlatforms': 'All consoles',
    'viewList': 'List',
    'viewCover': 'Covers',
    'viewLabel': 'Cartridges',
    'gamepads': 'Connected gamepads',
    'noGamepads': 'No gamepad detected',
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
    'setCover': 'Elegir portada local',
    'setLabel': 'Elegir etiqueta de cartucho',
    'clearCover': 'Quitar portada',
    'clearLabel': 'Quitar etiqueta',
    'useLabels': 'Mostrar etiquetas',
    'favorite': 'Agregar a favoritos',
    'unfavorite': 'Quitar de favoritos',
    'preferred': 'Emulador preferido',
    'retroAdvanced': 'RetroArch: rutas avanzadas',
    'retroWarning': 'Usa las rutas indicadas en RetroArch. Jolven no puede comprobar los cores de otra app; una ruta incorrecta puede mostrar una pantalla negra.',
    'retroCore': 'Ruta absoluta del core (.so)',
    'retroRom': 'Ruta absoluta de la ROM legible por RetroArch',
    'retroReady': 'Intentar iniciar mediante intent (sin verificar)',

    'unknownPlatform': 'Consola sin seleccionar',
    'favoritesOnly': 'Solo favoritos',
    'collections': 'Colecciones',
    'newCollection': 'Nueva colección',
    'renameCollection': 'Renombrar colección',
    'deleteCollection': 'Borrar colección',
    'addToCollection': 'Agregar/quitar de colección',
    'collectionName': 'Nombre de colección',
    'save': 'Guardar',
    'delete': 'Borrar',
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
    'documented': 'Inicio documentado (comprobar en emulador)',
    'retroGuide': 'Configurar RetroArch externo',
    'retroGuideBody': 'Instala RetroArch desde una fuente oficial y elige los cores dentro de la aplicación. Jolven no puede verificar los cores ni leer archivos privados.',
    'coreUnverified': 'Core sin verificar',
    'openGuide': 'Abrir guía oficial',
    'search': 'Buscar juegos',
    'allPlatforms': 'Todas las consolas',
    'viewList': 'Lista',
    'viewCover': 'Portadas',
    'viewLabel': 'Cartuchos',
    'gamepads': 'Mandos conectados',
    'noGamepads': 'No se detectaron mandos',
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
  List<GameCollection> _collections = [];
  List<GamepadInfo> _gamepads = [];
  String? _activeCollectionId;
  bool _loading = false;
  bool _favoritesOnly = false;
  bool _showLabels = false;
  String _query = '';
  String? _platformFilter;
  String _romView = 'list';

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
      final collections = await _bridge.listCollections();
      final gamepads = await _bridge.listGamepads();
      if (!mounted) return;
      setState(() {
        _emulators = emulators;
        _roms = roms;
        _androidGames = androidGames;
        _remoteClients = remoteClients;
        _collections = collections;
        _gamepads = gamepads;
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

  Future<void> _selectArtwork(RomItem rom, String kind) async {
    try {
      await _bridge.pickArtwork(rom, kind);
      if (mounted) await _refresh();
    } catch (error) {
      if (mounted) _message('${_t('error')}: $error');
    }
  }

  Future<void> _clearArtwork(RomItem rom, String kind) async {
    try {
      await _bridge.clearArtwork(rom, kind);
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

  Future<void> _configureRetroArch(RomItem rom) async {
    final core = TextEditingController(text: rom.retroCorePath ?? '');
    final path = TextEditingController(text: rom.retroRomPath ?? '');
    try {
      final save = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: Text(_t('retroAdvanced')),
          content: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Text(_t('retroWarning')),
              TextField(
                controller: core,
                decoration: InputDecoration(labelText: _t('retroCore')),
              ),
              TextField(
                controller: path,
                decoration: InputDecoration(labelText: _t('retroRom')),
              ),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(dialogContext, false),
              child: Text(_t('cancel'))),
            TextButton(onPressed: () => Navigator.pop(dialogContext, true),
              child: Text(_t('save'))),
          ],
        ),
      );
      if (save != true) return;
      await _bridge.updateRom(
        rom,
        retroCorePath: core.text.trim(),
        retroRomPath: path.text.trim(),
      );
      if (mounted) await _refresh();
    } catch (error) {
      if (mounted) _message('${_t('error')}: $error');
    } finally {
      core.dispose();
      path.dispose();
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

  Future<void> _openRetroArchGuide() async {
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(_t('retroGuide')),
        content: Text(_t('retroGuideBody')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext),
            child: Text(_t('cancel'))),
          TextButton(
            onPressed: () async {
              Navigator.pop(dialogContext);
              try {
                final outcome = await _bridge.openRetroArchGuide();
                if (mounted && outcome.status != 'guide_requested') _message(_t('unsupported'));
              } catch (error) {
                if (mounted) _message('${_t('error')}: $error');
              }
            },
            child: Text(_t('openGuide')),
          ),
        ],
      ),
    );
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

  GameCollection? get _selectedCollection {
    for (final collection in _collections) {
      if (collection.id == _activeCollectionId) return collection;
    }
    return null;
  }

  Future<void> _createCollection() async {
    var name = '';
    final selected = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(_t('newCollection')),
        content: TextField(
          autofocus: true,
          maxLength: 72,
          decoration: InputDecoration(labelText: _t('collectionName')),
          onChanged: (value) => name = value.trim(),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: Text(_t('cancel')),
          ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, name),
            child: Text(_t('save')),
          ),
        ],
      ),
    );
    if (selected == null || selected.isEmpty) return;
    try {
      final collection = await _bridge.createCollection(selected);
      if (mounted) {
        await _refresh();
        setState(() => _activeCollectionId = collection.id);
      }
    } catch (error) {
      if (mounted) _message('${_t('error')}: $error');
    }
  }

  Future<void> _renameCollection(GameCollection collection) async {
    var title = collection.title;
    final selected = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(_t('renameCollection')),
        content: TextField(
          autofocus: true,
          maxLength: 72,
          controller: TextEditingController(text: collection.title),
          onChanged: (value) => title = value.trim(),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: Text(_t('cancel')),
          ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, title),
            child: Text(_t('save')),
          ),
        ],
      ),
    );
    if (selected == null || selected.isEmpty) return;
    try {
      await _bridge.renameCollection(collection, selected);
      if (mounted) await _refresh();
    } catch (error) {
      if (mounted) _message('${_t('error')}: $error');
    }
  }

  Future<void> _deleteCollection(GameCollection collection) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(_t('deleteCollection')),
        content: Text(collection.title),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: Text(_t('cancel')),
          ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: Text(_t('delete')),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await _bridge.deleteCollection(collection);
      if (mounted) {
        setState(() => _activeCollectionId = null);
        await _refresh();
      }
    } catch (error) {
      if (mounted) _message('${_t('error')}: $error');
    }
  }

  Future<void> _toggleCollection(String ref) async {
    if (_collections.isEmpty) {
      await _createCollection();
      return;
    }
    final selected = await showModalBottomSheet<GameCollection>(
      context: context,
      builder: (sheetContext) => SafeArea(
        child: ListView(shrinkWrap: true, children: [
          ListTile(title: Text(_t('addToCollection'))),
          for (final collection in _collections)
            ListTile(
              leading: Icon(collection.contains(ref)
                  ? Icons.check_box : Icons.check_box_outline_blank),
              title: Text(collection.title),
              onTap: () => Navigator.pop(sheetContext, collection),
            ),
        ]),
      ),
    );
    if (selected == null) return;
    try {
      await _bridge.toggleCollectionMember(selected, ref);
      if (mounted) await _refresh();
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
                subtitle: Text(e.id.startsWith('retroarch') &&
                        rom.retroCorePath != null && rom.retroRomPath != null
                    ? _t('retroReady')
                    : (e.documentedIntegration ? _t('documented') :
                        (e.canAttemptView ? _t('experimental') : _t('manual')))),
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

  String _romConsole(RomItem rom) {
    final system = rom.platformId ?? identifyPlatform(rom.name).confidentId;
    return system == null ? _t('unknownPlatform') : platformLabel(system);
  }

  Widget _romArtwork(RomItem rom, {double width = 52, double height = 68}) {
    final path = (_romView == 'label' || _showLabels)
        ? rom.labelPath : rom.coverPath;
    if (path == null) {
      return Icon(rom.favorite ? Icons.favorite : Icons.videogame_asset, size: 36);
    }
    return Image.file(
      File(path),
      width: width, height: height,
      fit: BoxFit.contain,
      errorBuilder: (context, error, stack) =>
          const Icon(Icons.broken_image_outlined),
    );
  }

  Widget _romMenu(RomItem rom) => PopupMenuButton<String>(
    onSelected: (value) {
      if (value == 'play') _chooseEmulator(rom);
      if (value == 'platform') _setPlatform(rom);
      if (value == 'preferred') _setPreferred(rom);
      if (value == 'retroAdvanced') _configureRetroArch(rom);
      if (value == 'favorite') _toggleFavorite(rom);
      if (value == 'cover') _selectArtwork(rom, 'cover');
      if (value == 'label') _selectArtwork(rom, 'label');
      if (value == 'clearCover') _clearArtwork(rom, 'cover');
      if (value == 'clearLabel') _clearArtwork(rom, 'label');
      if (value == 'collection') _toggleCollection('rom:${rom.uri}');
      if (value == 'remove') _remove(rom);
    },
    itemBuilder: (context) => [
      PopupMenuItem(value: 'play', child: Text(_t('play'))),
      PopupMenuItem(value: 'platform', child: Text(_t('platform'))),
      PopupMenuItem(value: 'preferred', child: Text(_t('preferred'))),
      PopupMenuItem(value: 'retroAdvanced', child: Text(_t('retroAdvanced'))),
      PopupMenuItem(value: 'favorite', child: Text(
        _t(rom.favorite ? 'unfavorite' : 'favorite'))),
      PopupMenuItem(value: 'cover', child: Text(_t('setCover'))),
      PopupMenuItem(value: 'label', child: Text(_t('setLabel'))),
      if (rom.coverPath != null)
        PopupMenuItem(value: 'clearCover', child: Text(_t('clearCover'))),
      if (rom.labelPath != null)
        PopupMenuItem(value: 'clearLabel', child: Text(_t('clearLabel'))),
      PopupMenuItem(value: 'collection', child: Text(_t('addToCollection'))),
      PopupMenuItem(value: 'remove', child: Text(_t('remove'))),
    ],
  );

  Widget _romListItem(RomItem rom) => Card(
    child: ListTile(
      leading: _romArtwork(rom),
      title: Text(rom.name),
      subtitle: Text(_romConsole(rom), maxLines: 1,
        overflow: TextOverflow.ellipsis),
      onTap: () => _chooseEmulator(rom),
      trailing: _romMenu(rom),
    ),
  );

  Widget _romGridItem(RomItem rom) => Card(
    clipBehavior: Clip.antiAlias,
    child: InkWell(
      onTap: () => _chooseEmulator(rom),
      child: Padding(
        padding: const EdgeInsets.all(8),
        child: Column(children: [
          Expanded(child: Center(child: _romArtwork(rom, width: 140, height: 150))),
          Text(rom.name, maxLines: 2, overflow: TextOverflow.ellipsis,
            textAlign: TextAlign.center),
          Row(children: [
            Expanded(child: Text(_romConsole(rom), maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 10))),
            _romMenu(rom),
          ]),
        ]),
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    final installed = _emulators.where((e) => e.installed).toList();
    final activeCollection = _selectedCollection;
    final visibleRoms = _roms.where((rom) =>
      (!_favoritesOnly || rom.favorite) &&
      (activeCollection == null || activeCollection.contains('rom:${rom.uri}')) &&
      (_platformFilter == null ||
        (rom.platformId ?? identifyPlatform(rom.name).confidentId) == _platformFilter) &&
      (rom.name.toLowerCase().contains(_query.toLowerCase()))).toList()
      ..sort((a, b) => a.name.toLowerCase().compareTo(b.name.toLowerCase()));
    return Scaffold(
      appBar: AppBar(
        title: Text(_t('title')),
        actions: [
          IconButton(
            tooltip: 'Save Vault',
            icon: const Icon(Icons.save_outlined),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (context) => const SaveVaultPage(),
              ),
            ),
          ),
          IconButton(
            tooltip: 'ROM Patcher',
            icon: const Icon(Icons.auto_fix_high),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (context) => const RomPatcherPage(),
              ),
            ),
          ),
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
            const SizedBox(height: 20),
            Row(children: [
              Expanded(child: Text(_t('collections'),
                  style: Theme.of(context).textTheme.titleLarge)),
              IconButton(
                tooltip: _t('newCollection'),
                icon: const Icon(Icons.playlist_add),
                onPressed: _createCollection,
              ),
              if (activeCollection != null)
                PopupMenuButton<String>(
                  onSelected: (choice) {
                    if (choice == 'rename') _renameCollection(activeCollection);
                    if (choice == 'delete') _deleteCollection(activeCollection);
                  },
                  itemBuilder: (context) => [
                    PopupMenuItem(value: 'rename', child: Text(_t('renameCollection'))),
                    PopupMenuItem(value: 'delete', child: Text(_t('deleteCollection'))),
                  ],
                ),
            ]),
            Wrap(spacing: 8, children: [
              ChoiceChip(
                label: Text(_t('allGames')),
                selected: activeCollection == null,
                onSelected: (_) => setState(() => _activeCollectionId = null),
              ),
              for (final collection in _collections)
                ChoiceChip(
                  label: Text(collection.title),
                  selected: activeCollection?.id == collection.id,
                  onSelected: (_) => setState(
                    () => _activeCollectionId = collection.id),
                ),
            ]),
            const SizedBox(height: 12),
            TextField(
              decoration: InputDecoration(
                labelText: _t('search'),
                prefixIcon: const Icon(Icons.search),
              ),
              onChanged: (value) => setState(() => _query = value),
            ),
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
            for (final game in _androidGames.where(
              (game) => (activeCollection == null ||
                  activeCollection.contains('android:${game.packageName}')) &&
                  game.name.toLowerCase().contains(_query.toLowerCase())))
              ListTile(
                leading: const Icon(Icons.smartphone),
                title: Text(game.name),
                subtitle: Text(game.packageName),
                trailing: PopupMenuButton<String>(
                  onSelected: (value) {
                    if (value == 'open') _openAndroidGame(game);
                    if (value == 'collection') _toggleCollection('android:${game.packageName}');
                  },
                  itemBuilder: (context) => [
                    PopupMenuItem(value: 'open', child: Text(_t('openGame'))),
                    PopupMenuItem(value: 'collection', child: Text(_t('addToCollection'))),
                  ],
                ),
              ),
            const SizedBox(height: 24),
            Text(_t('remote'), style: Theme.of(context).textTheme.titleLarge),
            if (!_remoteClients.any((client) => client.installed))
              ListTile(title: Text(_t('noRemote'))),
            for (final client in _remoteClients.where((client) =>
              client.installed && (activeCollection == null ||
                  activeCollection.contains('remote:${client.packageName}')) &&
                  client.name.toLowerCase().contains(_query.toLowerCase())))
              ListTile(
                leading: const Icon(Icons.cast_connected),
                title: Text(client.name),
                trailing: PopupMenuButton<String>(
                  onSelected: (value) {
                    if (value == 'open') _openRemoteClient(client);
                    if (value == 'collection') _toggleCollection('remote:${client.packageName}');
                  },
                  itemBuilder: (context) => [
                    PopupMenuItem(value: 'open', child: Text(_t('openRemote'))),
                    PopupMenuItem(value: 'collection', child: Text(_t('addToCollection'))),
                  ],
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
            SwitchListTile(
              title: Text(_t('useLabels')),
              value: _showLabels,
              onChanged: (checked) => setState(() => _showLabels = checked),
            ),
            DropdownButton<String?>(
              isExpanded: true,
              value: _platformFilter,
              items: [
                DropdownMenuItem<String?>(value: null, child: Text(_t('allPlatforms'))),
                for (final system in platforms)
                  DropdownMenuItem<String?>(value: system.id, child: Text(system.label)),
              ],
              onChanged: (value) => setState(() => _platformFilter = value),
            ),
            Wrap(spacing: 8, children: [
              ChoiceChip(
                label: Text(_t('viewList')),
                selected: _romView == 'list',
                onSelected: (_) => setState(() => _romView = 'list'),
              ),
              ChoiceChip(
                label: Text(_t('viewCover')),
                selected: _romView == 'cover',
                onSelected: (_) => setState(() => _romView = 'cover'),
              ),
              ChoiceChip(
                label: Text(_t('viewLabel')),
                selected: _romView == 'label',
                onSelected: (_) => setState(() => _romView = 'label'),
              ),
            ]),
            if (_romView == 'list')
              for (final rom in visibleRoms) _romListItem(rom),
            if (_romView != 'list')
              LayoutBuilder(builder: (context, constraints) => GridView.builder(
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                gridDelegate: SliverGridDelegateWithMaxCrossAxisExtent(
                  maxCrossAxisExtent: constraints.maxWidth < 500 ? 175 : 220,
                  childAspectRatio: 0.74,
                  crossAxisSpacing: 8,
                  mainAxisSpacing: 8,
                ),
                itemCount: visibleRoms.length,
                itemBuilder: (context, index) => _romGridItem(visibleRoms[index]),
              )),
            const SizedBox(height: 20),
            Text(_t('gamepads'), style: Theme.of(context).textTheme.titleLarge),
            if (_gamepads.isEmpty) ListTile(title: Text(_t('noGamepads'))),
            for (final gamepad in _gamepads)
              ListTile(
                leading: const Icon(Icons.gamepad),
                title: Text(gamepad.name),
              ),
            const SizedBox(height: 20),
            Text(_t('emulators'), style: Theme.of(context).textTheme.titleLarge),
            ListTile(
              leading: const Icon(Icons.info_outline),
              title: Text(_t('retroGuide')),
              subtitle: Text(_t('coreUnverified')),
              trailing: TextButton(onPressed: _openRetroArchGuide,
                child: Text(_t('openGuide'))),
            ),
            if (installed.isEmpty) ListTile(title: Text(_t('none'))),
            for (final emulator in installed)
              ListTile(
                leading: const Icon(Icons.gamepad_outlined),
                title: Text(emulator.name),
                subtitle: Text('\${emulator.packageName} · \${emulator.versionName ?? ''}'),
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
