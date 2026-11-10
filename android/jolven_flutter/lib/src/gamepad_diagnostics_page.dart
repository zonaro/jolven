import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'models.dart';

/// Only observes controller inputs delivered to Jolven while this screen is
/// focused. It cannot observe or remap input in external emulator apps.
class GamepadDiagnosticsPage extends StatelessWidget {
  const GamepadDiagnosticsPage({super.key, required this.gamepads});

  final List<GamepadInfo> gamepads;

  static const EventChannel _events =
      EventChannel('jolven/gamepad_diagnostics');

  @override
  Widget build(BuildContext context) {
    final lang = Localizations.localeOf(context).languageCode;
    final isEn = lang == 'en';
    final isEs = lang == 'es';

    String t(String pt, String en, String es) =>
        isEn ? en : (isEs ? es : pt);

    return Scaffold(
      appBar: AppBar(
        title: Text(t('Diagnóstico de controle',
            'Controller diagnostics', 'Diagnóstico de mando')),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(t(
            'Os eventos abaixo são apenas dos controles enviados ao Jolven enquanto esta tela está aberta. Os emuladores externos gerenciam seus próprios controles.',
            'Events shown here are only inputs delivered to Jolven while this page is open. External emulators manage their own controllers.',
            'Los eventos son solo entradas recibidas por Jolven mientras esta pantalla está abierta. Los emuladores externos gestionan sus mandos.',
          )),
          const SizedBox(height: 20),
          Text(t('Dispositivos detectados', 'Detected devices',
              'Dispositivos detectados'),
              style: Theme.of(context).textTheme.titleMedium),
          if (gamepads.isEmpty)
            ListTile(title: Text(t('Nenhum controle detectado',
                'No controller detected', 'No se detectó mando'))),
          for (final pad in gamepads)
            ListTile(
              leading: const Icon(Icons.sports_esports),
              title: Text(pad.name),
              subtitle: Text('ID ${pad.id}'),
            ),
          const Divider(),
          Text(t('Última entrada', 'Latest input', 'Última entrada'),
            style: Theme.of(context).textTheme.titleMedium),
          StreamBuilder<dynamic>(
            stream: _events.receiveBroadcastStream(),
            builder: (context, snapshot) {
              if (snapshot.hasError) {
                return Text(t('Diagnóstico indisponível.',
                    'Diagnostics unavailable.',
                    'Diagnóstico no disponible.'));
              }
              final value = snapshot.data;
              if (value is! Map) {
                return Text(t('Pressione um botão ou mova um analógico.',
                    'Press a button or move a stick.',
                    'Pulsa un botón o mueve un joystick.'));
              }
              final type = value['type']?.toString() ?? 'unknown';
              final name = value['device']?.toString() ?? '—';
              final key = value['key']?.toString() ?? '';
              final x = value['x']?.toString() ?? '';
              final y = value['y']?.toString() ?? '';
              final action = value['action']?.toString() ?? '';
              return Card(child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(name, style: Theme.of(context).textTheme.titleMedium),
                    Text('Type: $type'),
                    if (key.isNotEmpty) Text('Key: $key · $action'),
                    if (x.isNotEmpty) Text('X: $x · Y: $y'),
                  ],
                ),
              ));
            },
          ),
        ],
      ),
    );
  }
}
