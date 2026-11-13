import 'package:flutter/material.dart';

import 'android_bridge.dart';

class FirmwareGuidePage extends StatefulWidget {
  const FirmwareGuidePage({super.key});
  @override
  State<FirmwareGuidePage> createState() => _FirmwareGuidePageState();
}

class _FirmwareGuidePageState extends State<FirmwareGuidePage> {
  final _bridge = const AndroidBridge();
  String _selected = 'ps1';
  Map<String, String>? _inspection;
  bool _busy = false;

  static const _systems = <String, List<String>>{
    'nes': ['Nintendo NES', 'none'],
    'snes': ['Super Nintendo', 'none'],
    'gb': ['Game Boy / GBC', 'optional'],
    'gba': ['Game Boy Advance', 'optional'],
    'ps1': ['PlayStation', 'depends'],
    'saturn': ['Sega Saturn', 'depends'],
    'dreamcast': ['Dreamcast', 'depends'],
    'psp': ['PSP / PPSSPP', 'none'],
    'nds': ['Nintendo DS', 'depends'],
  };

  String _t(String pt, String en, String es) {
    final language = Localizations.localeOf(context).languageCode;
    return language == 'en' ? en : (language == 'es' ? es : pt);
  }

  String _description(String requirement) {
    return switch (requirement) {
      'none' => _t(
          'Geralmente não requer BIOS em emuladores comuns. '
          'Confirme os requisitos da versão instalada.',
          'Usually no BIOS required for common emulators. '
          'Verify the requirements of your installed version.',
          'Normalmente no requiere BIOS. '
          'Verifica los requisitos de la versión instalada.'),
      'optional' => _t(
          'Alguns cores usam BIOS opcional para maior fidelidade. '
          'A instalação é feita no emulador externo.',
          'Some cores use optional BIOS for higher fidelity. '
          'Configure the external emulator directly.',
          'Algunos cores usan BIOS opcional. '
          'Configúrala directamente en el emulador externo.'),
      _ => _t(
          'A necessidade de BIOS depende do emulador e do core escolhido. '
          'Consulte a documentação do emulador instalado; o Jolven não '
          'pode verificar seus arquivos privados.',
          'BIOS requirements depend on your emulator and core. '
          'Check its documentation; Jolven cannot inspect its private files.',
          'La necesidad de BIOS depende del emulador y core. '
          'Consulta su documentación; Jolven no lee sus archivos privados.'),
    };
  }

  Future<void> _inspect() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final uri = await _bridge.pickUserFile();
      if (uri == null) return;
      final result = await _bridge.inspectUserFile(uri);
      if (mounted) setState(() => _inspection = result);
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(error.toString())),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final profile = _systems[_selected]!;
    return Scaffold(
      appBar: AppBar(title: const Text('BIOS / Firmware')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(_t(
            'Guia de compatibilidade — informativo, sem distribuição de BIOS.',
            'Compatibility guide — informational, no BIOS distribution.',
            'Guía de compatibilidad — informativa, sin distribuir BIOS.',
          )),
          const SizedBox(height: 20),
          DropdownButtonFormField<String>(
            isExpanded: true,
            initialValue: _selected,
            decoration: InputDecoration(
              labelText: _t('Console', 'Console', 'Consola')),
            items: [
              for (final entry in _systems.entries)
                DropdownMenuItem(value: entry.key,
                  child: Text(entry.value.first)),
            ],
            onChanged: (value) {
              if (value != null) setState(() => _selected = value);
            },
          ),
          const SizedBox(height: 20),
          Card(child: Padding(
            padding: const EdgeInsets.all(16),
            child: Text(_description(profile.last)),
          )),
          const SizedBox(height: 24),
          Text(_t(
            'Verificar SHA-256 de um arquivo fornecido por você',
            'Inspect SHA-256 of a file you selected',
            'Consultar SHA-256 de un archivo seleccionado',
          ), style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          Text(_t(
            'O checksum identifica o conteúdo. Ele NÃO confirma que a BIOS '
            'é válida, compatível ou instalada em outro aplicativo.',
            'The checksum identifies content. It does NOT prove that a BIOS '
            'is valid, compatible or installed in an external app.',
            'El checksum identifica el contenido. NO confirma que una BIOS '
            'sea válida o esté instalada en otro programa.',
          )),
          const SizedBox(height: 14),
          OutlinedButton.icon(
            onPressed: _busy ? null : _inspect,
            icon: const Icon(Icons.fingerprint),
            label: Text(_t('Selecionar arquivo', 'Select file', 'Elegir archivo')),
          ),
          if (_busy) const LinearProgressIndicator(),
          if (_inspection != null)
            SelectableText('SHA-256: ${_inspection!['sha256'] ?? '?'}'
                '\n${_inspection!['sizeBytes'] ?? '?'} bytes'),
        ],
      ),
    );
  }
}
