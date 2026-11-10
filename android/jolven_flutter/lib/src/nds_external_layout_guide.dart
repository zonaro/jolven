import 'package:flutter/material.dart';

/// A visual guide to configuring Nintendo DS display layouts **in the external
/// emulator**. Preview does not modify Dolphin/RetroArch/Drastic settings.
class NdsExternalLayoutGuide extends StatefulWidget {
  const NdsExternalLayoutGuide({super.key});

  @override
  State<NdsExternalLayoutGuide> createState() => _NdsExternalLayoutGuideState();
}

enum NdsPreviewOrientation { stacked, sideBySide }

class _NdsExternalLayoutGuideState extends State<NdsExternalLayoutGuide> {
  NdsPreviewOrientation _orientation = NdsPreviewOrientation.stacked;

  @override
  Widget build(BuildContext context) {
    final language = Localizations.localeOf(context).languageCode;

    String t(String pt, String en, String es) => switch (language) {
      'en' => en,
      'es' => es,
      _ => pt,
    };
    final tall = _orientation == NdsPreviewOrientation.stacked;

    return Scaffold(
      appBar: AppBar(title: Text(t('Telas do Nintendo DS',
          'Nintendo DS screens', 'Pantallas de Nintendo DS'))),
      body: LayoutBuilder(builder: (context, constraints) => ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Center(child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 780),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(t(
                'Prévia ilustrativa: altere a posição das duas telas dentro das opções do emulador instalado, não pelo Jolven.',
                'Illustrative preview only: change screen positions inside the installed emulator settings, not through Jolven.',
                'Vista ilustrativa: ajusta las pantallas dentro de los ajustes del emulador, no desde Jolven.',
              )),
              const SizedBox(height: 14),
              SegmentedButton<NdsPreviewOrientation>(
                segments: [
                  ButtonSegment(
                    value: NdsPreviewOrientation.stacked,
                    label: Text(t('Empilhadas', 'Stacked', 'Apiladas')),
                    icon: const Icon(Icons.view_agenda_outlined),
                  ),
                  ButtonSegment(
                    value: NdsPreviewOrientation.sideBySide,
                    label: Text(t('Lado a lado', 'Side by side', 'Una al lado de otra')),
                    icon: const Icon(Icons.view_column_outlined),
                  ),
                ],
                selected: {_orientation},
                onSelectionChanged: (values) => setState(() => _orientation = values.first),
              ),
              const SizedBox(height: 14),
              AspectRatio(
                aspectRatio: tall ? 0.9 : 1.65,
                child: Container(
                  constraints: const BoxConstraints(maxHeight: 430),
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: Theme.of(context).colorScheme.surfaceContainerHighest,
                    borderRadius: BorderRadius.circular(18),
                  ),
                  child: Flex(
                    direction: tall ? Axis.vertical : Axis.horizontal,
                    children: [
                      Expanded(child: _ScreenPreview(
                        label: t('Tela superior', 'Top screen', 'Pantalla superior'),
                        icon: Icons.image_outlined,
                      )),
                      const SizedBox(width: 8, height: 8),
                      Expanded(child: _ScreenPreview(
                        label: t('Tela de toque', 'Touch screen', 'Pantalla táctil'),
                        icon: Icons.touch_app_outlined,
                      )),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 20),
              Text(t('O que configurar no emulador',
                    'What to configure in your emulator',
                    'Qué configurar en el emulador'),
                style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 8),
              for (final item in [
                t('Orientação e ordem das telas',
                  'Screen orientation and order',
                  'Orientación y orden de pantallas'),
                t('Proporção e escala de cada tela',
                  'Size and aspect ratio per screen',
                  'Tamaño y proporción de cada pantalla'),
                t('Entrada touch na tela inferior',
                  'Touch input on the bottom screen',
                  'Entrada táctil en la pantalla inferior'),
                t('Gamepad, botões e hotkeys no próprio emulador',
                  'Controller mapping and hotkeys in the emulator',
                  'Asignación del mando y atajos dentro del emulador'),
              ])
                ListTile(
                  leading: const Icon(Icons.check_circle_outline),
                  title: Text(item),
                ),
              Text(t(
                'O Jolven não injeta controles, altera o layout de outro app nem acessa arquivos internos do emulador.',
                'Jolven does not inject controls, modify another app layout, or access private emulator files.',
                'Jolven no inyecta controles, cambia el diseño de otra app ni lee archivos privados.',
              ), style: Theme.of(context).textTheme.bodySmall),
            ]),
          )),
        ],
      )),
    );
  }
}

class _ScreenPreview extends StatelessWidget {
  const _ScreenPreview({required this.label, required this.icon});
  final String label;
  final IconData icon;

  @override
  Widget build(BuildContext context) => Container(
    decoration: BoxDecoration(
      color: Theme.of(context).colorScheme.surface,
      border: Border.all(color: Theme.of(context).colorScheme.outline),
      borderRadius: BorderRadius.circular(12),
    ),
    child: Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Icon(icon, size: 36),
        const SizedBox(height: 8),
        Text(label),
      ],
    ),
  );
}
