import 'dart:async';

import 'package:flutter/material.dart';

import 'android_bridge.dart';
import 'models.dart';

class RecordingPage extends StatefulWidget {
  const RecordingPage({super.key});
  @override
  State<RecordingPage> createState() => _RecordingPageState();
}

class _RecordingPageState extends State<RecordingPage> {
  final _bridge = const AndroidBridge();
  RecordingInfo? _info;
  Timer? _timer;
  bool _busy = false;

  String _t(String pt, String en, String es) {
    final lang = Localizations.localeOf(context).languageCode;
    return lang == 'en' ? en : (lang == 'es' ? es : pt);
  }

  @override
  void initState() {
    super.initState();
    _updateStatus();
    _timer = Timer.periodic(const Duration(seconds: 3),
        (timer) => _updateStatus());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _updateStatus() async {
    try {
      final info = await _bridge.recordingStatus();
      if (mounted) setState(() => _info = info);
    } catch (_) {
      // The recorder is optional; keep the page accessible without the bridge.
    }
  }

  void _toast(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message)),
    );
  }

  Future<void> _start() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final outcome = await _bridge.startScreenRecording();
      if (!mounted) return;
      if (outcome.status == 'cancelled') {
        _toast(_t('Permissão cancelada.', 'Consent cancelled.', 'Permiso cancelado.'));
      } else if (outcome.status == 'consent_received') {
        _toast(_t(
          'Permissão recebida. Confirme o início na notificação do Android.',
          'Consent received. Check the Android recording notification.',
          'Permiso recibido. Comprueba la notificación de Android.',
        ));
      }
      await _updateStatus();
    } catch (error) {
      if (mounted) _toast(error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _stop() async {
    try {
      await _bridge.stopScreenRecording();
      await _updateStatus();
    } catch (error) {
      if (mounted) _toast(error.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    final running = _info?.recording == true;
    return Scaffold(
      appBar: AppBar(title: Text(_t('Gravador de tela', 'Screen recorder',
          'Grabador de pantalla'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(_t(
            'Captura de vídeo sem áudio. É necessário consentir no diálogo '
            'do Android a cada gravação. Os vídeos vão para Movies/Jolven.',
            'Video recording without audio. Android consent is required '
            'for every session. Videos are saved in Movies/Jolven.',
            'Grabación de vídeo sin audio. Android requiere permiso '
            'en cada sesión. Los vídeos se guardan en Movies/Jolven.',
          )),
          const SizedBox(height: 20),
          Text(running
              ? _t('Gravando', 'Recording', 'Grabando')
              : _t('Não está gravando', 'Not recording', 'No está grabando'),
              style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 20),
          FilledButton.icon(
            onPressed: _busy || running ? null : _start,
            icon: const Icon(Icons.fiber_manual_record),
            label: Text(_t('Iniciar gravação', 'Start recording',
                'Iniciar grabación')),
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: running ? _stop : null,
            icon: const Icon(Icons.stop),
            label: Text(_t('Encerrar gravação', 'Stop recording',
                'Detener grabación')),
          ),
          TextButton.icon(
            onPressed: _updateStatus,
            icon: const Icon(Icons.refresh),
            label: Text(_t('Atualizar status', 'Refresh status',
                'Actualizar estado')),
          ),
          if (_busy) const LinearProgressIndicator(),
          if (_info?.error?.isNotEmpty == true)
            Text('${_info!.error}', style: TextStyle(
              color: Theme.of(context).colorScheme.error)),
          if (_info?.lastVideoUri?.isNotEmpty == true)
            SelectableText(_t(
              'Última gravação: ', 'Last recording: ', 'Última grabación: ',
            ) + _info!.lastVideoUri!),
        ],
      ),
    );
  }
}
