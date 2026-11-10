import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';

import 'android_bridge.dart';
import 'nearby_protocol.dart';

class NearbyReceivePage extends StatefulWidget {
  const NearbyReceivePage({super.key});

  @override
  State<NearbyReceivePage> createState() => _NearbyReceivePageState();
}

class _DigestSink implements Sink<Digest> {
  Digest? digest;

  @override
  void add(Digest data) => digest = data;

  @override
  void close() {}
}

class _NearbyReceivePageState extends State<NearbyReceivePage> {
  final _url = TextEditingController();
  final _token = TextEditingController();
  final _fingerprint = TextEditingController();
  final _bridge = const AndroidBridge();

  NearbyEndpoint? _endpoint;
  List<NearbyOffer> _offers = [];
  final Set<int> _selected = {};
  HttpClient? _activeClient;
  bool _busy = false;
  bool _cancel = false;
  String _message = '';
  int _progress = 0;

  String _t(String pt, String en, String es) {
    final lang = Localizations.localeOf(context).languageCode;
    return lang == 'en' ? en : (lang == 'es' ? es : pt);
  }

  @override
  void dispose() {
    _activeClient?.close(force: true);
    _url.dispose();
    _token.dispose();
    _fingerprint.dispose();
    super.dispose();
  }

  void _status(String message, {int? progress}) {
    if (!mounted) return;
    setState(() {
      _message = message;
      if (progress != null) _progress = progress;
    });
  }

  HttpClient _client(NearbyEndpoint endpoint) {
    final context = SecurityContext(withTrustedRoots: false);
    final client = HttpClient(context: context)
      ..connectionTimeout = const Duration(seconds: 5)
      ..idleTimeout = const Duration(seconds: 5)
      ..autoUncompress = false
      ..maxConnectionsPerHost = 1;
    client.badCertificateCallback = (cert, host, port) =>
        host == endpoint.url.host &&
        port == endpoint.url.port &&
        nearbyCertificateFingerprint(cert) == endpoint.fingerprint;
    return client;
  }

  Future<HttpClientResponse> _get(
    HttpClient client, NearbyEndpoint endpoint, String path,
  ) async {
    final request = await client.getUrl(endpoint.path(path));
    request.followRedirects = false;
    request.headers.set(HttpHeaders.authorizationHeader, 'Bearer ${endpoint.token}');
    final response = await request.close();
    final cert = response.certificate;
    if (cert == null || nearbyCertificateFingerprint(cert) != endpoint.fingerprint) {
      throw HandshakeException('Certificate fingerprint mismatch');
    }
    if (response.statusCode != HttpStatus.ok) {
      throw HttpException('Server rejected request (${response.statusCode})');
    }
    final encoding = response.headers.value(HttpHeaders.contentEncodingHeader);
    if (encoding != null && encoding != 'identity') {
      throw const FormatException('Unexpected Content-Encoding');
    }
    return response;
  }

  Future<void> _connect() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _cancel = false;
      _offers = [];
      _selected.clear();
      _progress = 0;
    });
    HttpClient? client;
    try {
      final endpoint = NearbyEndpoint.parse(
        url: _url.text, token: _token.text, fingerprint: _fingerprint.text,
      );
      client = _client(endpoint);
      _activeClient = client;
      final response = await _get(client, endpoint, '/manifest');
      final bytes = BytesBuilder(copy: false);
      await for (final chunk in response.timeout(const Duration(seconds: 10))) {
        if (_cancel) throw const HttpException('Cancelled');
        bytes.add(chunk);
        if (bytes.length > nearbyMaxManifestBytes) {
          throw const FormatException('Manifest too large');
        }
      }
      final offers = parseNearbyManifest(bytes.takeBytes());
      if (!mounted) return;
      setState(() {
        _endpoint = endpoint;
        _offers = offers;
        _selected.addAll(offers.map((offer) => offer.index));
      });
      _status(_t('Oferta recebida. Selecione os arquivos para salvar.',
          'Offer received. Choose files to save.',
          'Oferta recibida. Selecciona archivos para guardar.'));
    } catch (error) {
      _status(_t('Falha na conexão/verificação: ',
          'Connection/verification failed: ',
          'Fallo de conexión/verificación: ') + error.toString());
    } finally {
      client?.close(force: true);
      _activeClient = null;
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _receive() async {
    if (_busy || _endpoint == null || _selected.isEmpty) return;
    final endpoint = _endpoint!;
    final chosen = _offers.where((offer) => _selected.contains(offer.index)).toList();
    setState(() {
      _busy = true;
      _cancel = false;
      _progress = 0;
    });
    HttpClient? client;
    Directory? staging;
    var saved = 0;
    try {
      staging = await Directory(await _bridge.nearbyCacheDir())
          .createTemp('jolven-nearby-');
      client = _client(endpoint);
      _activeClient = client;
      for (final offer in chosen) {
        if (_cancel) break;
        _status('${offer.name} (${saved + 1}/${chosen.length})', progress: 0);
        final response = await _get(client, endpoint, '/file/${offer.index}');
        if (response.contentLength >= 0 && response.contentLength != offer.size) {
          throw const FormatException('Content-Length mismatch');
        }
        final file = File('${staging.path}/file-${offer.index}.part');
        final output = await file.open(mode: FileMode.write);
        final digestSink = _DigestSink();
        final chunked = sha256.startChunkedConversion(digestSink);
        var received = 0;
        try {
          await for (final chunk in response.timeout(const Duration(seconds: 20))) {
            if (_cancel) throw const HttpException('Cancelled');
            received += chunk.length;
            if (received > offer.size || received > nearbyMaxFileBytes) {
              throw const FormatException('File exceeded declared size');
            }
            await output.writeFrom(chunk);
            chunked.add(chunk);
            if (mounted && offer.size > 0) {
              _status(offer.name, progress: (received * 100 ~/ offer.size));
            }
          }
          chunked.close();
        } finally {
          await output.close();
        }
        if (received != offer.size || digestSink.digest?.toString() != offer.sha256) {
          throw const FormatException('SHA-256 or size mismatch');
        }
        if (_cancel) break;
        final exported = await _bridge.exportNearbyFile(
          path: file.path, name: offer.name, sha256: offer.sha256,
        );
        if (exported) saved++;
      }
      if (_cancel) {
        _status(_t('Transferência cancelada.', 'Transfer cancelled.',
            'Transferencia cancelada.'));
      } else {
        _status(_t('Arquivos salvos: ', 'Files saved: ', 'Archivos guardados: ') +
            saved.toString());
      }
    } catch (error) {
      _status(_t('Transferência interrompida: ', 'Transfer interrupted: ',
          'Transferencia interrumpida: ') + error.toString());
    } finally {
      client?.close(force: true);
      _activeClient = null;
      if (staging != null) {
        try {
          await staging.delete(recursive: true);
        } catch (_) {
          // Android may still be releasing a document writer.
        }
      }
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(_t('Receber do computador',
          'Receive from computer', 'Recibir del ordenador'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(_t(
            'No computador, execute o emissor Nearby. Confira o SHA-256 do '
            'certificado antes de informar o token. A transferência ocorre '
            'somente por HTTPS em uma sessão temporária.',
            'Start the Nearby sender on your computer. Verify the certificate '
            'SHA-256 before entering the token. Transfers use temporary HTTPS.',
            'Inicia Nearby en el ordenador. Verifica SHA-256 del certificado '
            'antes de ingresar el token. La conexión usa HTTPS temporal.',
          )),
          const SizedBox(height: 16),
          TextField(
            controller: _url, enabled: !_busy,
            keyboardType: TextInputType.url,
            decoration: const InputDecoration(
              labelText: 'HTTPS URL', hintText: 'https://192.168.1.20:12345',
            ),
          ),
          TextField(
            controller: _fingerprint, enabled: !_busy,
            autocorrect: false,
            decoration: const InputDecoration(
              labelText: 'TLS SHA-256 fingerprint', hintText: '64 hex digits',
            ),
          ),
          TextField(
            controller: _token, enabled: !_busy,
            obscureText: true, autocorrect: false,
            decoration: InputDecoration(labelText:
              _t('Token da sessão', 'Session token', 'Token de sesión')),
          ),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: _busy ? null : _connect,
            icon: const Icon(Icons.lock_outline),
            label: Text(_t('Verificar oferta', 'Verify offer', 'Verificar oferta')),
          ),
          if (_message.isNotEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: SelectableText(_message),
            ),
          if (_busy) LinearProgressIndicator(value: _progress <= 0 ? null : _progress / 100),
          if (_offers.isNotEmpty) ...[
            const Divider(),
            Text(_t('Arquivos oferecidos', 'Offered files', 'Archivos ofrecidos'),
              style: Theme.of(context).textTheme.titleMedium),
            for (final offer in _offers)
              CheckboxListTile(
                title: Text(offer.name),
                subtitle: Text('${offer.kind} · ${offer.size} bytes'),
                value: _selected.contains(offer.index),
                onChanged: _busy ? null : (selected) {
                  setState(() {
                    if (selected == true) {
                      _selected.add(offer.index);
                    } else {
                      _selected.remove(offer.index);
                    }
                  });
                },
              ),
            FilledButton.icon(
              onPressed: _busy || _selected.isEmpty ? null : _receive,
              icon: const Icon(Icons.save_alt),
              label: Text(_t('Receber e escolher onde salvar',
                  'Receive and choose save destination',
                  'Recibir y elegir dónde guardar')),
            ),
          ],
          if (_busy)
            OutlinedButton(
              onPressed: () {
                _cancel = true;
                _activeClient?.close(force: true);
              },
              child: Text(_t('Cancelar transferência', 'Cancel transfer',
                  'Cancelar transferencia')),
            ),
          const SizedBox(height: 12),
          Text(_t(
            'Arquivos salvos devem ser importados na biblioteca separadamente. '
            'O Jolven não altera dados privados de outros emuladores.',
            'Saved files can be imported into the library separately. '
            'Jolven never modifies other emulators’ private data.',
            'Los archivos guardados se importan a la biblioteca por separado. '
            'Jolven no modifica los datos privados de otros emuladores.',
          ), style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }
}
