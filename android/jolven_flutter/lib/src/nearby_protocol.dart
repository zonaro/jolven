import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';

const nearbyMaxManifestBytes = 256 * 1024;
const nearbyMaxFileBytes = 8 * 1024 * 1024 * 1024;
const nearbyMaxTotalBytes = 16 * 1024 * 1024 * 1024;

class NearbyOffer {
  const NearbyOffer({
    required this.name,
    required this.kind,
    required this.size,
    required this.sha256,
    required this.index,
  });

  final String name;
  final String kind;
  final int size;
  final String sha256;
  final int index;
}

class NearbyEndpoint {
  const NearbyEndpoint({required this.url, required this.token, required this.fingerprint});

  final Uri url;
  final String token;
  final String fingerprint;

  factory NearbyEndpoint.parse({
    required String url,
    required String token,
    required String fingerprint,
  }) {
    final endpoint = Uri.tryParse(url.trim());
    if (endpoint == null || endpoint.scheme != 'https' ||
        endpoint.hasQuery || endpoint.hasFragment ||
        endpoint.userInfo.isNotEmpty ||
        (endpoint.path.isNotEmpty && endpoint.path != '/')) {
      throw const FormatException('Expected https://private-IPv4:port');
    }
    final parsed = InternetAddress.tryParse(endpoint.host);
    if (parsed == null || parsed.type != InternetAddressType.IPv4) {
      throw const FormatException('Only IPv4 address is supported');
    }
    final bytes = parsed.rawAddress;
    final private = bytes[0] == 10 ||
        (bytes[0] == 172 && bytes[1] >= 16 && bytes[1] <= 31) ||
        (bytes[0] == 192 && bytes[1] == 168) ||
        bytes[0] == 127;
    if (!private || !endpoint.hasPort || endpoint.port < 1 ||
        endpoint.port > 65535) {
      throw const FormatException('Only private IPv4 addresses and a port are allowed');
    }
    final normalizedToken = token.trim();
    if (!RegExp(r'^[A-Za-z0-9_-]{40,128}$').hasMatch(normalizedToken)) {
      throw const FormatException('Invalid session token');
    }
    final normalizedFingerprint = fingerprint.toLowerCase().replaceAll(':', '').trim();
    if (!RegExp(r'^[a-f0-9]{64}$').hasMatch(normalizedFingerprint)) {
      throw const FormatException('Expected 64 hex SHA-256 fingerprint digits');
    }
    return NearbyEndpoint(
      url: endpoint,
      token: normalizedToken,
      fingerprint: normalizedFingerprint,
    );
  }

  Uri path(String suffix) => url.replace(path: suffix, query: null, fragment: null);
}

String nearbyCertificateFingerprint(X509Certificate cert) =>
    sha256.convert(cert.der).toString();

List<NearbyOffer> parseNearbyManifest(List<int> bytes) {
  if (bytes.length > nearbyMaxManifestBytes) {
    throw const FormatException('Manifest too large');
  }
  final root = jsonDecode(utf8.decode(bytes, allowMalformed: false));
  if (root is! Map<String, dynamic> ||
      root.keys.toSet().difference({'version', 'files'}).isNotEmpty ||
      root.length != 2 || root['version'] != 1 ||
      root['files'] is! List<dynamic>) {
    throw const FormatException('Invalid transfer manifest');
  }
  final records = root['files'] as List<dynamic>;
  if (records.isEmpty || records.length > 128) {
    throw const FormatException('Invalid manifest file count');
  }
  final result = <NearbyOffer>[];
  final names = <String>{};
  var total = 0;
  for (var index = 0; index < records.length; index++) {
    final record = records[index];
    if (record is! Map<String, dynamic> ||
        record.length != 4 ||
        record.keys.toSet().difference({'name', 'kind', 'size', 'sha256'}).isNotEmpty) {
      throw const FormatException('Invalid manifest entry');
    }
    final name = record['name'];
    final kind = record['kind'];
    final size = record['size'];
    final hash = record['sha256'];
    if (name is! String || name.isEmpty || name.length > 180 ||
        name.startsWith('.') || name.endsWith('.') ||
        name.trim() != name ||
        name.contains(RegExp(r'[/\\:\x00-\x1f]')) ||
        !names.add(name.toLowerCase())) {
      throw const FormatException('Unsafe or duplicate filename');
    }
    if (kind is! String ||
        !{'rom', 'save', 'cover', 'label'}.contains(kind) ||
        size is! int || size < 0 || size > nearbyMaxFileBytes ||
        hash is! String || !RegExp(r'^[a-f0-9]{64}$').hasMatch(hash)) {
      throw const FormatException('Invalid file metadata');
    }
    total += size;
    if (total > nearbyMaxTotalBytes) {
      throw const FormatException('Transfer too large');
    }
    result.add(NearbyOffer(
      name: name, kind: kind, size: size, sha256: hash, index: index,
    ));
  }
  return result;
}
