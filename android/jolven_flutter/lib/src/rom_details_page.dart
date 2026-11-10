import 'dart:io';

import 'package:flutter/material.dart';

import 'emulator_compatibility.dart';
import 'models.dart';
import 'platform_catalog.dart';

/// A frontend-only overview; never claims that an external emulator launched.
enum RomDetailsAction {
  play,
  platform,
  preferred,
  consoleDefault,
  favorite,
  cover,
  label,
  clearCover,
  clearLabel,
  fingerprint,
  remove,
}

class RomDetailsPage extends StatelessWidget {
  const RomDetailsPage({
    required this.rom,
    required this.emulators,
    required this.consoleDefaults,
    required this.onAction,
    super.key,
  });

  final RomItem rom;
  final List<EmulatorInfo> emulators;
  final Map<String, String> consoleDefaults;
  final ValueChanged<RomDetailsAction> onAction;

  String _t(BuildContext context, String pt, String en, String es) {
    final lang = Localizations.localeOf(context).languageCode;
    return lang == 'en' ? en : lang == 'es' ? es : pt;
  }

  String _size(int? bytes) {
    if (bytes == null) return '—';
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) {
      return '${(bytes / 1024).toStringAsFixed(1)} KiB';
    }
    if (bytes < 1024 * 1024 * 1024) {
      return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MiB';
    }
    return '${(bytes / (1024 * 1024 * 1024)).toStringAsFixed(2)} GiB';
  }

  Widget _artwork(String? path, {required IconData fallback, double height = 220}) {
    if (path == null || path.isEmpty) {
      return Container(
        width: 168, height: height,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: Colors.deepPurple.withValues(alpha: 0.10),
          borderRadius: BorderRadius.circular(16),
        ),
        child: Icon(fallback, size: 70),
      );
    }
    return ClipRRect(
      borderRadius: BorderRadius.circular(16),
      child: Image.file(
        File(path),
        width: 168, height: height, fit: BoxFit.contain,
        errorBuilder: (_, _, _) => SizedBox(
          width: 168, height: height,
          child: const Center(child: Icon(Icons.broken_image_outlined, size: 54)),
        ),
      ),
    );
  }

  Widget _detail(String label, String value) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 5),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 126, child: Text(label,
            style: const TextStyle(fontWeight: FontWeight.w600))),
          Expanded(child: SelectableText(value)),
        ]),
      );

  Widget _action(BuildContext context, IconData icon, String title,
      RomDetailsAction action) =>
      OutlinedButton.icon(
        onPressed: () => onAction(action),
        icon: Icon(icon),
        label: Text(title),
      );

  @override
  Widget build(BuildContext context) {
    final system = romPlatformId(rom);
    final ranked = rankEmulators(
      rom, emulators, consoleDefaults: consoleDefaults,
    );
    final compatible = ranked.where(
      (e) => emulatorFit(rom, e) != EmulatorFit.differentSystem,
    ).toList();
    final preferred = ranked.where((e) =>
      e.packageName == rom.emulatorPackage).firstOrNull;
    final consoleDefault = ranked.where((e) =>
      e.packageName == consoleDefaults[system]).firstOrNull;
    final name = rom.name.replaceFirst(RegExp(r'\.[^.]+$'), '');

    return Scaffold(
      appBar: AppBar(
        title: Text(_t(context, 'Detalhes do jogo', 'Game details', 'Detalles del juego')),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
        children: [
          Center(child: Wrap(
            spacing: 16, runSpacing: 12,
            alignment: WrapAlignment.center,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              _artwork(rom.coverPath, fallback: Icons.videogame_asset_outlined),
              if (rom.labelPath != null)
                _artwork(rom.labelPath, fallback: Icons.gamepad, height: 160),
            ],
          )),
          const SizedBox(height: 16),
          Text(name, textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.headlineSmall),
          Text(
            system == null ? _t(context, 'Console não identificado',
              'Console not identified', 'Consola no identificada')
              : platformLabel(system),
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.titleMedium,
          ),
          if (rom.favorite)
            Center(child: Chip(
              avatar: const Icon(Icons.favorite, size: 18),
              label: Text(_t(context, 'Favorito', 'Favorite', 'Favorito')),
            )),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: () => onAction(RomDetailsAction.play),
            icon: const Icon(Icons.play_arrow),
            label: Text(_t(context, 'Jogar', 'Play', 'Jugar')),
          ),
          const SizedBox(height: 20),
          Text(
            _t(context, 'Informações do arquivo', 'File information',
              'Información del archivo'),
            style: Theme.of(context).textTheme.titleLarge,
          ),
          _detail(_t(context, 'Arquivo', 'File', 'Archivo'), rom.name),
          _detail(_t(context, 'Tamanho', 'Size', 'Tamaño'), _size(rom.sizeBytes)),
          _detail('SHA-256', rom.sha256 ??
              _t(context, 'Não calculado', 'Not calculated', 'No calculado')),
          _detail(_t(context, 'Emulador do jogo', 'Game emulator',
              'Emulador del juego'), preferred?.name ??
              _t(context, 'Não escolhido', 'Not selected', 'Sin seleccionar')),
          _detail(_t(context, 'Padrão do console', 'Console default',
              'Predeterminado de consola'), consoleDefault?.name ??
              _t(context, 'Não escolhido', 'Not selected', 'Sin seleccionar')),
          const SizedBox(height: 14),
          Text(_t(context, 'Emuladores detectados', 'Detected emulators',
              'Emuladores detectados'),
              style: Theme.of(context).textTheme.titleLarge),
          if (compatible.isEmpty)
            Text(_t(context,
                'Nenhum emulador adequado foi detectado. Instale um emulador '
                'compatível separadamente e escolha o console correto.',
                'No suitable emulator detected. Install a compatible app '
                'separately and select the correct console.',
                'No se detectó un emulador adecuado. Instala uno compatible '
                'por separado y selecciona la consola correcta.')),
          for (final emulator in compatible)
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.sports_esports_outlined),
              title: Text(emulator.name),
              subtitle: Text(switch (emulatorFit(rom, emulator)) {
                EmulatorFit.documentedIntent => _t(context,
                    'Intent documentada, não testada no aparelho',
                    'Documented intent, not device-tested',
                    'Intent documentada, no probada en dispositivo'),
                EmulatorFit.experimentalIntent => _t(context,
                    'Abertura experimental', 'Experimental launch',
                    'Inicio experimental'),
                EmulatorFit.retroArchPathsUnverified => _t(context,
                    'Caminhos externos configurados, não verificados',
                    'External paths configured, not verified',
                    'Rutas externas configuradas, no verificadas'),
                EmulatorFit.manualOnly => _t(context,
                    'Abertura manual no aplicativo externo',
                    'Manual launch in external app',
                    'Inicio manual en aplicación externa'),
                EmulatorFit.unknownSystem => _t(context,
                    'Compatibilidade desconhecida',
                    'Unknown compatibility', 'Compatibilidad desconocida'),
                EmulatorFit.differentSystem => _t(context,
                    'Outro console', 'Different console', 'Otra consola'),
              }),
            ),
          const SizedBox(height: 12),
          Text(
            _t(context, 'Gerenciar', 'Manage', 'Administrar'),
            style: Theme.of(context).textTheme.titleLarge,
          ),
          Wrap(spacing: 8, runSpacing: 8, children: [
            _action(context, Icons.memory, _t(context,
              'Definir console', 'Set console', 'Definir consola'),
              RomDetailsAction.platform),
            _action(context, Icons.settings, _t(context,
              'Emulador do jogo', 'Game emulator', 'Emulador del juego'),
              RomDetailsAction.preferred),
            _action(context, Icons.sports_esports, _t(context,
              'Padrão do console', 'Console default', 'Predeterminado de consola'),
              RomDetailsAction.consoleDefault),
            _action(context, rom.favorite ? Icons.favorite_border : Icons.favorite,
              rom.favorite
                ? _t(context, 'Desfavoritar', 'Remove favorite', 'Quitar favorito')
                : _t(context, 'Favoritar', 'Favorite', 'Favorito'),
              RomDetailsAction.favorite),
            _action(context, Icons.image_outlined, _t(context,
              'Escolher capa', 'Set cover', 'Elegir portada'),
              RomDetailsAction.cover),
            _action(context, Icons.label_outline, _t(context,
              'Escolher etiqueta', 'Set label', 'Elegir etiqueta'),
              RomDetailsAction.label),
            if (rom.coverPath != null)
              _action(context, Icons.hide_image, _t(context,
                'Remover capa', 'Remove cover', 'Quitar portada'),
                RomDetailsAction.clearCover),
            if (rom.labelPath != null)
              _action(context, Icons.label_off, _t(context,
                'Remover etiqueta', 'Remove label', 'Quitar etiqueta'),
                RomDetailsAction.clearLabel),
            _action(context, Icons.fingerprint, _t(context,
              'Calcular SHA-256', 'Calculate SHA-256', 'Calcular SHA-256'),
              RomDetailsAction.fingerprint),
          ]),
          const SizedBox(height: 24),
          TextButton.icon(
            onPressed: () => onAction(RomDetailsAction.remove),
            icon: const Icon(Icons.remove_circle_outline),
            label: Text(_t(context, 'Remover da biblioteca',
                'Remove from library', 'Quitar de la biblioteca')),
          ),
          Text(
            _t(context,
              'Remover a entrada não exclui sua ROM original. O Jolven não '
              'inclui emuladores, cores nem BIOS.',
              'Removing a catalog entry does not delete the original ROM. '
              'Jolven does not bundle emulators, cores or BIOS.',
              'Quitar la entrada no borra la ROM original. Jolven no '
              'incluye emuladores, núcleos ni BIOS.'),
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}
