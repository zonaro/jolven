import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import 'android_bridge.dart';

/// A small RetroArch overlay authoring model, not a live touch controller.
class OverlayControl {
  const OverlayControl(this.action, this.x, this.y);
  final String action;
  final double x;
  final double y;

  OverlayControl at(double nx, double ny) => OverlayControl(
    action, nx.clamp(0.04, 0.96), ny.clamp(0.04, 0.96),
  );
}

class RetroOverlayFormat {
  const RetroOverlayFormat._();

  static const width = 800;
  static const height = 450;
  static const allowedActions = {
    'a', 'b', 'x', 'y', 'up', 'down', 'left', 'right', 'start', 'select',
  };

  static String generate(List<OverlayControl> controls) {
    if (controls.isEmpty || controls.length > 16) {
      throw const FormatException('Invalid overlay control count');
    }
    final config = <String>[
      '# Jolven-generated RetroArch overlay; import manually into RetroArch.',
      'overlays = 1',
      'overlay0_overlay = "jolven.png"',
      'overlay0_full_screen = true',
      'overlay0_descs = ${controls.length}',
    ];
    for (var i = 0; i < controls.length; i++) {
      final control = controls[i];
      if (!allowedActions.contains(control.action) ||
          !control.x.isFinite || !control.y.isFinite ||
          control.x < 0 || control.x > 1 ||
          control.y < 0 || control.y > 1) {
        throw const FormatException('Invalid control position or action');
      }
      config.add('overlay0_desc$i = "${control.action},'
          '${(control.x * width).round()},${(control.y * height).round()},'
          'radial,35,35"');
    }
    return '${config.join('\n')}\n';
  }
}

class OverlayEditorPage extends StatefulWidget {
  const OverlayEditorPage({super.key});

  @override
  State<OverlayEditorPage> createState() => _OverlayEditorPageState();
}

class _OverlayEditorPageState extends State<OverlayEditorPage> {
  final _bridge = const AndroidBridge();
  final _controls = <OverlayControl>[
    const OverlayControl('up', 0.14, 0.58),
    const OverlayControl('down', 0.14, 0.83),
    const OverlayControl('left', 0.07, 0.71),
    const OverlayControl('right', 0.21, 0.71),
    const OverlayControl('a', 0.86, 0.70),
    const OverlayControl('b', 0.77, 0.80),
    const OverlayControl('x', 0.77, 0.58),
    const OverlayControl('y', 0.68, 0.69),
    const OverlayControl('start', 0.56, 0.83),
    const OverlayControl('select', 0.44, 0.83),
  ];
  int _selected = 0;
  bool _saving = false;
  String? _lastStatus;

  void _pick(Offset point, Size size) {
    var best = 2500.0;
    var nearest = _selected;
    for (var i = 0; i < _controls.length; i++) {
      final x = _controls[i].x * size.width;
      final y = _controls[i].y * size.height;
      final distance = (x - point.dx) * (x - point.dx) +
          (y - point.dy) * (y - point.dy);
      if (distance < best) {
        best = distance;
        nearest = i;
      }
    }
    setState(() => _selected = nearest);
  }

  void _move(Offset point, Size size) {
    setState(() {
      _controls[_selected] = _controls[_selected].at(
        point.dx / size.width, point.dy / size.height,
      );
    });
  }

  Future<void> _export() async {
    if (_saving) return;
    setState(() {
      _saving = true;
      _lastStatus = null;
    });
    try {
      final config = RetroOverlayFormat.generate(_controls);
      final recorder = ui.PictureRecorder();
      final canvas = Canvas(recorder);
      _OverlayPainter(_controls, selectedIndex: -1)
          .paint(canvas, const Size(800, 450));
      final picture = recorder.endRecording();
      final image = await picture.toImage(
        RetroOverlayFormat.width, RetroOverlayFormat.height,
      );
      final imageData = await image.toByteData(format: ui.ImageByteFormat.png);
      image.dispose();
      picture.dispose();
      if (imageData == null) throw StateError('PNG encoding failed');
      final Uint8List pngBytes = imageData.buffer.asUint8List();
      final saved = await _bridge.exportOverlayZip(config, pngBytes);
      if (mounted) {
        setState(() => _lastStatus = saved ? 'ok' : 'cancel');
      }
    } catch (_) {
      if (mounted) setState(() => _lastStatus = 'error');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final language = Localizations.localeOf(context).languageCode;
    String t(String pt, String en, String es) => switch (language) {
      'en' => en,
      'es' => es,
      _ => pt,
    };

    final current = _controls[_selected];
    return Scaffold(
      appBar: AppBar(title: Text(t(
        'Editor de overlay RetroArch',
        'RetroArch overlay editor',
        'Editor de overlay RetroArch',
      ))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(t(
            'Mova os botões no desenho. Exporta .cfg + .png em ZIP; você deve extrair e ativar o overlay no RetroArch externo. Isto é uma prévia, não um controle de jogo.',
            'Drag buttons on the preview. Exports .cfg + .png as ZIP; extract and enable the overlay in external RetroArch. This preview does not control a game.',
            'Arrastra los botones en la vista. Exporta .cfg + .png en ZIP; extrae y activa el overlay en RetroArch externo. No controla el juego.',
          )),
          const SizedBox(height: 16),
          AspectRatio(
            aspectRatio: 16 / 9,
            child: LayoutBuilder(builder: (context, constraints) =>
              GestureDetector(
                onPanStart: (details) => _pick(details.localPosition, constraints.biggest),
                onPanUpdate: (details) => _move(details.localPosition, constraints.biggest),
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    color: const Color(0xFF12121A),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: CustomPaint(
                    painter: _OverlayPainter(_controls, selectedIndex: _selected),
                    size: constraints.biggest,
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(height: 12),
          DropdownButton<int>(
            isExpanded: true,
            value: _selected,
            items: [
              for (var i = 0; i < _controls.length; i++)
                DropdownMenuItem(
                  value: i, child: Text(_controls[i].action.toUpperCase()),
                ),
            ],
            onChanged: (index) {
              if (index != null) setState(() => _selected = index);
            },
          ),
          Text('X: ${current.x.toStringAsFixed(2)}'),
          Slider(
            value: current.x, min: 0.04, max: 0.96,
            onChanged: (x) => setState(
              () => _controls[_selected] = current.at(x, current.y)),
          ),
          Text('Y: ${current.y.toStringAsFixed(2)}'),
          Slider(
            value: current.y, min: 0.04, max: 0.96,
            onChanged: (y) => setState(
              () => _controls[_selected] = current.at(current.x, y)),
          ),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: _saving ? null : _export,
            icon: const Icon(Icons.save_alt),
            label: Text(t('Exportar pacote ZIP', 'Export ZIP package',
                'Exportar paquete ZIP')),
          ),
          if (_saving) const LinearProgressIndicator(),
          if (_lastStatus != null)
            Text(_lastStatus == 'ok'
              ? t('Pacote salvo. Importe no RetroArch instalado.',
                  'Package saved. Import into installed RetroArch.',
                  'Paquete guardado. Impórtalo en RetroArch.')
              : _lastStatus == 'cancel'
              ? t('Exportação cancelada.', 'Export cancelled.',
                  'Exportación cancelada.')
              : t('Não foi possível exportar o pacote.',
                  'Could not export package.',
                  'No se pudo exportar el paquete.')),
        ],
      ),
    );
  }
}

class _OverlayPainter extends CustomPainter {
  const _OverlayPainter(this.controls, {required this.selectedIndex});
  final List<OverlayControl> controls;
  final int selectedIndex;

  @override
  void paint(Canvas canvas, Size size) {
    final background = Paint()..color = const Color(0x221A122A);
    canvas.drawRect(Offset.zero & size, background);

    for (var i = 0; i < controls.length; i++) {
      final item = controls[i];
      final position = Offset(item.x * size.width, item.y * size.height);
      final selected = selectedIndex == i;
      final paint = Paint()
        ..color = selected ? const Color(0xCCAF83FF)
            : const Color(0x889C75ED);
      canvas.drawCircle(position, 35 * size.width / 800, paint);
      final outline = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2
        ..color = Colors.white70;
      canvas.drawCircle(position, 35 * size.width / 800, outline);
      final paragraph = TextPainter(
        text: TextSpan(
          text: item.action.toUpperCase(),
          style: TextStyle(
            color: Colors.white,
            fontSize: 14 * size.width / 800,
            fontWeight: FontWeight.bold,
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      paragraph.paint(canvas, position -
          Offset(paragraph.width / 2, paragraph.height / 2));
      paragraph.dispose();
    }
  }

  @override
  bool shouldRepaint(covariant _OverlayPainter old) => true;
}
