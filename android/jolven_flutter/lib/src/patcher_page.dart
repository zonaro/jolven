import 'package:flutter/material.dart';

import 'android_bridge.dart';
import 'models.dart';

/// Optional ROM patcher: processes files selected by the owner, with no
/// embedded emulation, ROM downloads or access to other apps' sandboxes.
class RomPatcherPage extends StatefulWidget {
  const RomPatcherPage({super.key});

  @override
  State<RomPatcherPage> createState() => _RomPatcherPageState();
}

class _RomPatcherPageState extends State<RomPatcherPage> {
  final _bridge = const AndroidBridge();
  List<RomItem> _roms = [];
  String? _selectedUri;
  String? _patchUri;
  bool _busy = false;

  String _t(String pt, String en, String es) {
    final language = Localizations.localeOf(context).languageCode;
    return language == 'en' ? en : (language == 'es' ? es : pt);
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final roms = await _bridge.listRoms();
      if (!mounted) return;
      setState(() => _roms = roms);
    } catch (e) {
      if (mounted) _toast(e.toString());
    }
  }

  void _toast(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message)),
    );
  }

  Future<void> _pickPatch() async {
    try {
      final uri = await _bridge.pickPatchFile();
      if (mounted && uri != null) setState(() => _patchUri = uri);
    } catch (e) {
      if (mounted) _toast(e.toString());
    }
  }

  Future<void> _export() async {
    if (_busy || _patchUri == null || _selectedUri == null) return;
    RomItem? selected;
    for (final rom in _roms) {
      if (rom.uri == _selectedUri) selected = rom;
    }
    if (selected == null) return;
    setState(() => _busy = true);
    try {
      final result = await _bridge.exportPatchedRom(selected, _patchUri!);
      if (!mounted) return;
      if (result.status == 'exported') {
        _toast(_t('ROM modificada exportada. Importe-a na biblioteca para jogar.',
            'Patched ROM exported. Import it into your library to play.',
            'ROM modificada exportada. Impórtala en la biblioteca para jugar.'));
      } else if (result.status != 'cancelled') {
        _toast(_t('Não foi possível exportar a ROM.', 'Could not export the ROM.',
            'No se pudo exportar la ROM.'));
      }
    } catch (e) {
      if (mounted) _toast(e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('ROM Patcher')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(_t(
            'Aplique patches IPS/EBP, UPS e BPS às suas próprias ROMs. '
            'O arquivo original não será alterado. Há limites de 64 MiB para ROMs, '
            '8 MiB para patches e 96 MiB para a saída.',
            'Patch your own ROMs with IPS/EBP, UPS or BPS. The original file '
            'will not change. Limits: 64 MiB ROM, 8 MiB patch, 96 MiB output.',
            'Aplica parches IPS/EBP, UPS o BPS a tus ROMs. El archivo original '
            'no se modifica. Límites: ROM 64 MiB, parche 8 MiB, salida 96 MiB.',
          )),
          const SizedBox(height: 20),
          DropdownButtonFormField<String>(
            isExpanded: true,
            initialValue: _selectedUri,
            decoration: InputDecoration(
              labelText: _t('ROM da biblioteca', 'Library ROM', 'ROM de la biblioteca'),
            ),
            items: [
              for (final rom in _roms)
                DropdownMenuItem<String>(
                  value: rom.uri,
                  child: Text(rom.name, overflow: TextOverflow.ellipsis),
                ),
            ],
            onChanged: _busy ? null : (uri) => setState(() => _selectedUri = uri),
          ),
          if (_roms.isEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(_t('Importe uma ROM na tela principal primeiro.',
                  'Import a ROM on the main screen first.',
                  'Importa una ROM en la pantalla principal primero.')),
            ),
          const SizedBox(height: 16),
          OutlinedButton.icon(
            onPressed: _busy ? null : _pickPatch,
            icon: const Icon(Icons.file_open),
            label: Text(_t('Selecionar patch', 'Choose patch', 'Seleccionar parche')),
          ),
          if (_patchUri != null)
            Padding(
              padding: const EdgeInsets.all(8),
              child: Text(_t('Patch selecionado', 'Patch selected', 'Parche seleccionado')),
            ),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: _busy || _selectedUri == null || _patchUri == null
                ? null : _export,
            icon: const Icon(Icons.save_alt),
            label: Text(_t('Aplicar e exportar', 'Apply and export',
                'Aplicar y exportar')),
          ),
          if (_busy) const Padding(
            padding: EdgeInsets.only(top: 16),
            child: LinearProgressIndicator(),
          ),
        ],
      ),
    );
  }
}
