import 'package:flutter/material.dart';

import 'android_bridge.dart';
import 'models.dart';

/// Save file organizer, never a privileged reader of an emulator's private data.
class SaveVaultPage extends StatefulWidget {
  const SaveVaultPage({super.key});

  @override
  State<SaveVaultPage> createState() => _SaveVaultPageState();
}

class _SaveVaultPageState extends State<SaveVaultPage> {
  final _bridge = const AndroidBridge();
  List<SaveFileRecord> _saves = [];
  List<RomItem> _roms = [];
  RomItem? _associatedRom;
  bool _busy = false;

  String _t(String pt, String en, String es) {
    final lang = Localizations.localeOf(context).languageCode;
    return lang == 'en' ? en : (lang == 'es' ? es : pt);
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _toast(String text) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  Future<void> _load() async {
    try {
      final saves = await _bridge.listSavedFiles();
      final roms = await _bridge.listRoms();
      if (!mounted) return;
      setState(() { _saves = saves; _roms = roms; });
    } catch (e) {
      if (mounted) _toast(e.toString());
    }
  }

  Future<void> _import() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final saved = await _bridge.pickSaveFile(rom: _associatedRom);
      if (saved != null && mounted) {
        _toast(_t('Save importado', 'Save imported', 'Guardado importado'));
        await _load();
      }
    } catch (e) {
      if (mounted) _toast(e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _export(SaveFileRecord record) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final report = await _bridge.exportSaveFile(record);
      if (mounted && report.status == 'exported') {
        _toast(_t('Save exportado', 'Save exported', 'Guardado exportado'));
      }
    } catch (e) {
      if (mounted) _toast(e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _delete(SaveFileRecord record) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(_t('Excluir cópia local?', 'Delete local copy?',
            '¿Borrar copia local?')),
        content: Text(record.name),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: Text(_t('Cancelar', 'Cancel', 'Cancelar')),
          ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: Text(_t('Excluir', 'Delete', 'Borrar')),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await _bridge.deleteSaveFile(record);
      if (mounted) await _load();
    } catch (e) {
      if (mounted) _toast(e.toString());
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Save Vault')),
        body: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text(_t(
                'Saves de emuladores externos só podem ser importados após '
                'você exportá-los ou escolher o arquivo via Android. '
                'O Jolven não acessa o armazenamento privado de outro aplicativo.',
                'External emulator saves must first be exported or selected '
                'manually. Jolven cannot read another app\'s private storage.',
                'Los guardados de emuladores externos deben exportarse '
                'o seleccionarse manualmente. Jolven no lee datos privados.')),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: _associatedRom?.uri,
              isExpanded: true,
              decoration: InputDecoration(
                labelText: _t('Associar ao jogo (opcional)', 'Associate with game (optional)',
                    'Asociar al juego (opcional)'),
              ),
              items: [
                DropdownMenuItem<String>(
                  value: null,
                  child: Text(_t('Sem associação', 'No association', 'Sin asociación')),
                ),
                for (final rom in _roms)
                  DropdownMenuItem<String>(
                    value: rom.uri,
                    child: Text(rom.name, overflow: TextOverflow.ellipsis),
                  ),
              ],
              onChanged: (selected) {
                setState(() {
                  _associatedRom = null;
                  for (final rom in _roms) {
                    if (rom.uri == selected) _associatedRom = rom;
                  }
                });
              },
            ),
            const SizedBox(height: 14),
            FilledButton.icon(
              onPressed: _busy ? null : _import,
              icon: const Icon(Icons.file_open),
              label: Text(_t('Importar save', 'Import save', 'Importar guardado')),
            ),
            const SizedBox(height: 12),
            if (_busy) const LinearProgressIndicator(),
            for (final save in _saves)
              Card(
                child: ListTile(
                  title: Text(save.name),
                  subtitle: Text('${save.sizeBytes} bytes · SHA-256 '
                      '${save.sha256.substring(0, 12)}…'),
                  trailing: PopupMenuButton<String>(
                    onSelected: (action) {
                      if (action == 'export') _export(save);
                      if (action == 'delete') _delete(save);
                    },
                    itemBuilder: (context) => [
                      PopupMenuItem(
                        value: 'export',
                        child: Text(_t('Exportar', 'Export', 'Exportar')),
                      ),
                      PopupMenuItem(
                        value: 'delete',
                        child: Text(_t('Excluir', 'Delete', 'Borrar')),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      );
}
