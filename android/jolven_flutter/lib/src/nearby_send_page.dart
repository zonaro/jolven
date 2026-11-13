import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';

import 'android_bridge.dart';
import 'nearby_protocol.dart';

/// The user selects exactly one SAF file and starts a pinned HTTPS upload.
/// Remote desktop must explicitly accept before any file bytes are transmitted.
class NearbySendPage extends StatefulWidget {
  const NearbySendPage({super.key});

  @override
  State<NearbySendPage> createState() => _NearbySendPageState();
}

class _NearbySendPageState extends State<NearbySendPage> {
  final _url = TextEditingController();
  final _token = TextEditingController();
  final _fingerprint = TextEditingController();
  final _bridge = const AndroidBridge();

  String _kind = 'rom';
  Map<String, dynamic>? _staged;
  HttpClient? _client;
  bool _busy = false;
  int _progress = 0;
  String _message = '';

  String _t(String pt, String en, String es) {
    final language = Localizations.localeOf(context).languageCode;
    return language == 'en' ? en : language == 'es' ? es : pt;
  }

  @override
  void dispose() {
    _client?.close(force: true);
    final stage = _staged?['path'] as String?;
    if (stage != null) {
      _bridge.cleanupNearbyStage(stage).ignore();
    }
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

  Future<void> _selectFile() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final uri = await _bridge.pickUserFile();
      if (uri == null) return;
      final next = await _bridge.stageNearbyFile(uri, _kind);
      final previous = _staged?['path'] as String?;
      if (previous != null) await _bridge.cleanupNearbyStage(previous);
      if (!mounted) {
        await _bridge.cleanupNearbyStage(next['path'] as String);
        return;
      }
      setState(() => _staged = next);
      _status(_t('Arquivo preparado: ', 'File prepared: ',
          'Archivo preparado: ') + (next['name'] as String));
    } catch (error) {
      _status(_t('Não foi possível ler o arquivo: ', 'Could not read file: ',
          'No se pudo leer el archivo: ') + error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  HttpClient _secureClient(NearbyEndpoint endpoint) {
    // No trusted public CA roots: every connection must call the callback,
    // which checks the actual leaf certificate fingerprint before HTTP data.
    final client = HttpClient(context: SecurityContext(withTrustedRoots: false))
      ..connectionTimeout = const Duration(seconds: 5)
      ..autoUncompress = false
      ..maxConnectionsPerHost = 1
      ..idleTimeout = const Duration(seconds: 5);
    client.badCertificateCallback = (cert, host, port) =>
        host == endpoint.url.host &&
        port == endpoint.url.port &&
        nearbyCertificateFingerprint(cert) == endpoint.fingerprint;
    return client;
  }

  Future<HttpClientRequest> _request(
      HttpClient client, NearbyEndpoint endpoint, String resource) async {
    final request = await client.postUrl(endpoint.path(resource));
    request.followRedirects = false;
    request.headers.set(HttpHeaders.authorizationHeader,
        'Bearer ${endpoint.token}');
    request.headers.set(HttpHeaders.contentTypeHeader, 'application/octet-stream');
    return request;
  }

  Future<void> _checkResponse(
    HttpClientResponse response, NearbyEndpoint endpoint, String marker,
  ) async {
    final cert = response.certificate;
    if (cert == null || nearbyCertificateFingerprint(cert) != endpoint.fingerprint) {
      throw HandshakeException('TLS certificate fingerprint mismatch');
    }
    if (response.statusCode != HttpStatus.ok) {
      throw HttpException('Desktop refused request: ${response.statusCode}');
    }
    final value = await utf8.decoder
        .bind(response.timeout(const Duration(seconds: 10)))
        .join();
    if (value != marker) throw const FormatException('Unexpected Nearby response');
  }

  Future<void> _sendFile() async {
    if (_busy || _staged == null) return;
    final source = _staged!;
    setState(() {
      _busy = true;
      _progress = 0;
    });
    HttpClient? client;
    try {
      final endpoint = NearbyEndpoint.parse(
        url: _url.text, token: _token.text, fingerprint: _fingerprint.text,
      );
      final name = source['name'] as String;
      final kind = source['kind'] as String;
      final path = source['path'] as String;
      final size = source['size'] as int;
      final checksum = source['sha256'] as String;
      final file = File(path);
      if (!await file.exists() || await file.length() != size) {
        throw const FormatException('Temporary file changed');
      }
      final offer = utf8.encode(jsonEncode({
        'version': 1,
        'files': [
          {'name': name, 'kind': kind, 'size': size, 'sha256': checksum}
        ],
      }));
      // Validate our own outbound manifest as a defensive contract check.
      parseNearbyManifest(offer);
      client = _secureClient(endpoint);
      _client = client;

      _status(_t('Aguardando aprovação no computador…',
          'Waiting for confirmation on the computer…',
          'Esperando confirmación en el ordenador…'));
      final request = await _request(client, endpoint, '/offer');
      request.contentLength = offer.length;
      request.add(offer);
      final accepted = await request.close().timeout(const Duration(minutes: 2));
      await _checkResponse(accepted, endpoint, 'ACCEPTED');

      _status(_t('Enviando arquivo…', 'Sending file…', 'Enviando archivo…'));
      final upload = await _request(client, endpoint, '/file/0');
      upload.contentLength = size;
      var uploaded = 0;
      await upload.addStream(file.openRead().map((chunk) {
        uploaded += chunk.length;
        if (mounted && size > 0) {
          _status(name, progress: uploaded * 100 ~/ size);
        }
        return chunk;
      }));
      final verified = await upload.close();
      await _checkResponse(verified, endpoint, 'VERIFIED');

      _status(_t('Confirmando integridade…', 'Finalizing integrity…',
          'Confirmando integridad…'));
      final commit = await _request(client, endpoint, '/commit');
      commit.contentLength = 0;
      final committed = await commit.close();
      await _checkResponse(committed, endpoint, 'COMMITTED');
      _status(_t('Arquivo recebido e confirmado pelo computador.',
          'Desktop confirmed successful receipt.',
          'El ordenador confirmó la recepción.'));
      await _bridge.cleanupNearbyStage(path);
      if (mounted) setState(() => _staged = null);
    } catch (error) {
      _status(_t('Envio não concluído: ', 'Upload not completed: ',
          'Envío no completado: ') + error.toString());
    } finally {
      client?.close(force: true);
      _client = null;
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(_t('Enviar para o computador',
          'Send to computer', 'Enviar al ordenador'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(_t(
            'Inicie o receptor Nearby no PC. Confira o fingerprint TLS '
            'e informe o token. O computador precisa aprovar sua oferta antes '
            'do envio, e não sobrescreverá arquivos existentes.',
            'Start the Nearby receiver on your PC. Verify its TLS fingerprint '
            'and enter the token. The computer must approve your offer, '
            'and existing files will never be overwritten.',
            'Inicia el receptor Nearby en el PC. Verifica su fingerprint TLS '
            'e introduce el token. El ordenador debe aprobar la oferta '
            'y no sobrescribe archivos existentes.',
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
            decoration: const InputDecoration(
              labelText: 'TLS SHA-256 fingerprint',
              hintText: '64 hex digits',
            ),
          ),
          TextField(
            controller: _token, enabled: !_busy, obscureText: true,
            decoration: InputDecoration(labelText: _t(
              'Token da sessão', 'Session token', 'Token de sesión')),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _kind,
            decoration: InputDecoration(labelText: _t(
              'Tipo de arquivo', 'File type', 'Tipo de archivo')),
            items: const [
              DropdownMenuItem(value: 'rom', child: Text('ROM')),
              DropdownMenuItem(value: 'save', child: Text('Save')),
              DropdownMenuItem(value: 'cover', child: Text('Cover')),
              DropdownMenuItem(value: 'label', child: Text('Label')),
            ],
            onChanged: _busy ? null : (value) {
              if (value != null) setState(() => _kind = value);
            },
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: _busy ? null : _selectFile,
            icon: const Icon(Icons.file_open),
            label: Text(_t('Selecionar arquivo por SAF',
              'Choose SAF file', 'Seleccionar archivo SAF')),
          ),
          if (_staged != null)
            ListTile(
              leading: const Icon(Icons.insert_drive_file_outlined),
              title: Text(_staged!['name'] as String),
              subtitle: Text('${_staged!['size']} bytes'),
            ),
          if (_message.isNotEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: SelectableText(_message),
            ),
          if (_busy) LinearProgressIndicator(value: _progress == 0 ? null : _progress / 100),
          FilledButton.icon(
            onPressed: _busy || _staged == null ? null : _sendFile,
            icon: const Icon(Icons.upload_file),
            label: Text(_t('Solicitar envio seguro', 'Request secure upload',
                'Solicitar envío seguro')),
          ),
          if (_busy)
            OutlinedButton(
              onPressed: () => _client?.close(force: true),
              child: Text(_t('Cancelar', 'Cancel', 'Cancelar')),
            ),
          const SizedBox(height: 12),
          Text(_t(
            'Limite inicial: 512 MiB por arquivo. Original preservado; sem '
            'acesso a saves privados de outros emuladores.',
            'Initial limit: 512 MiB per file. Original kept intact; no '
            'access to private emulator save data.',
            'Límite inicial: 512 MiB por archivo. Se conserva el original '
            'y no se accede a datos privados de otros emuladores.',
          ), style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }
}
