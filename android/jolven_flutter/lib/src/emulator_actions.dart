import 'package:flutter/material.dart';
import 'android_bridge.dart';
import 'models.dart';

/// A capabilities description, not remote control of the emulator process.
/// 'instructionsOnly' means that Jolven cannot invoke the action itself.
enum ExternalActionAvailability { instructionsOnly, unsupported }

class EmulatorAction {
  const EmulatorAction({
    required this.id,
    required this.title,
    required this.description,
    this.availability = ExternalActionAvailability.instructionsOnly,
  });

  final String id;
  final String title;
  final String description;
  final ExternalActionAvailability availability;
}

class EmulatorActionCatalog {
  const EmulatorActionCatalog._();

  static List<EmulatorAction> forEmulator(
    EmulatorInfo emulator, String languageCode,
  ) {
    final locale = {'pt', 'en', 'es'}.contains(languageCode)
        ? languageCode : 'pt';
    final isRetroArch = emulator.id.startsWith('retroarch');
    final isPpsspp = emulator.id.startsWith('ppsspp');
    final isDolphin = emulator.id == 'dolphin';

    String localized(String pt, String en, String es) => switch (locale) {
      'en' => en,
      'es' => es,
      _ => pt,
    };

    final navigationHint = isRetroArch
        ? localized(
            'Configure Hotkeys e Quick Menu dentro do RetroArch. O Jolven não tem acesso ao menu durante o jogo.',
            'Configure Hotkeys and Quick Menu inside RetroArch. Jolven cannot access the in-game menu.',
            'Configura Hotkeys y Quick Menu dentro de RetroArch. Jolven no accede al menú en el juego.',
          )
        : isPpsspp
            ? localized(
                'Abra Configurações no PPSSPP e use o menu do próprio emulador para pausar ou alterar controles.',
                'Open PPSSPP Settings and use its own menu to pause or change controls.',
                'Abre Ajustes en PPSSPP y usa su propio menú para pausar o cambiar controles.',
              )
            : isDolphin
                ? localized(
                    'Configure controles e opções de jogo no próprio Dolphin. Os comandos podem variar entre versões.',
                    'Configure controls and game options inside Dolphin. Commands vary by version.',
                    'Configura controles y opciones dentro de Dolphin. Los comandos varían según versión.',
                  )
                : localized(
                    'Consulte as configurações do emulador instalado; não há protocolo de controle in-game confirmado.',
                    'See the installed emulator settings; no in-game control protocol is verified.',
                    'Consulta los ajustes del emulador; no hay protocolo de control verificado.',
                  );

    final actions = <EmulatorAction>[
      EmulatorAction(
        id: 'pause',
        title: localized('Pausar e retomar', 'Pause and resume', 'Pausar y continuar'),
        description: navigationHint,
      ),
      EmulatorAction(
        id: 'saves',
        title: localized('Salvar e carregar estado', 'Save and load state', 'Guardar y cargar estado'),
        description: localized(
          'Use os slots do emulador. Estados de cores ou versões diferentes podem ser incompatíveis.',
          'Use the emulator slots. Save states may be incompatible across cores and versions.',
          'Usa los espacios del emulador. Estados de cores o versiones distintas pueden ser incompatibles.',
        ),
      ),
      EmulatorAction(
        id: 'shaders',
        title: localized('Filtros, shaders e velocidade', 'Shaders, filters and speed', 'Shaders, filtros y velocidad'),
        description: localized(
          'Configure no emulador externo. O Jolven não altera shaders, turbo ou velocidade durante outra Activity.',
          'Configure in the external emulator. Jolven does not change shaders or speed inside another app.',
          'Configura en el emulador externo. Jolven no cambia shaders ni velocidad en otra aplicación.',
        ),
      ),
      EmulatorAction(
        id: 'screenshot',
        title: localized('Captura de tela', 'Screenshot', 'Captura de pantalla'),
        description: localized(
          'Use a captura do emulador ou a ferramenta do Android. Algumas telas podem bloquear captura.',
          'Use the emulator or Android screenshot feature. Some content may prevent capture.',
          'Usa la captura del emulador o de Android. Algunos contenidos pueden bloquearla.',
        ),
      ),
      EmulatorAction(
        id: 'hardcore',
        title: localized('Conquistas hardcore', 'Hardcore achievements', 'Logros hardcore'),
        description: localized(
          'Ative no emulador compatível. O Jolven não desativa limitações de hardcore nem confirma desbloqueios.',
          'Enable in a compatible emulator. Jolven cannot bypass hardcore restrictions or confirm unlocks.',
          'Activa en un emulador compatible. Jolven no omite restricciones ni confirma desbloqueos.',
        ),
      ),
    ];
    return actions;
  }
}

class EmulatorActionsPage extends StatelessWidget {
  const EmulatorActionsPage({
    super.key,
    required this.emulator,
    this.bridge = const AndroidBridge(),
  });

  final EmulatorInfo emulator;
  final AndroidBridge bridge;

  @override
  Widget build(BuildContext context) {
    final locale = Localizations.localeOf(context).languageCode;
    final portuguese = locale != 'en' && locale != 'es';
    final title = locale == 'en' ? 'External emulator actions'
        : locale == 'es' ? 'Acciones del emulador externo'
        : 'Ações do emulador externo';
    final status = locale == 'en' ? 'Instructions only — not remote control'
        : locale == 'es' ? 'Solo instrucciones; sin control remoto'
        : 'Somente orientações — sem controle remoto';
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(emulator.name, style: Theme.of(context).textTheme.headlineSmall),
          Text(emulator.packageName),
          if (emulator.versionName != null)
            Text(emulator.versionName!, style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 12),
          Text(status),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: !emulator.installed ? null : () async {
              try {
                final response = await bridge.openEmulator(emulator);
                if (!context.mounted) return;
                if (response.status != 'emulator_opened') {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text(
                      portuguese ? 'Não foi possível abrir o emulador.'
                        : locale == 'en' ? 'Could not open emulator.'
                        : 'No se pudo abrir el emulador.',
                    )),
                  );
                }
              } catch (_) {
                if (!context.mounted) return;
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text(
                    portuguese ? 'Não foi possível abrir o emulador.'
                      : locale == 'en' ? 'Could not open emulator.'
                      : 'No se pudo abrir el emulador.',
                  )),
                );
              }
            },
            icon: const Icon(Icons.open_in_new),
            label: Text(portuguese ? 'Abrir emulador'
                : locale == 'en' ? 'Open emulator' : 'Abrir emulador'),
          ),
          const SizedBox(height: 16),
          for (final action in EmulatorActionCatalog.forEmulator(emulator, locale))
            Card(
              child: ListTile(
                leading: const Icon(Icons.info_outline),
                title: Text(action.title),
                subtitle: Text(action.description),
              ),
            ),
        ],
      ),
    );
  }
}
