import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:jolven_flutter/src/nearby_protocol.dart';

const token = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-';
const pin = '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef';

void main() {
  test('endpoint validates private IPv4 and explicit certificate fingerprint', () {
    final endpoint = NearbyEndpoint.parse(
      url: 'https://192.168.1.20:12345', token: token, fingerprint: pin,
    );
    expect(endpoint.url.host, '192.168.1.20');
    expect(endpoint.fingerprint, pin);
    expect(endpoint.path('/manifest').toString(),
        'https://192.168.1.20:12345/manifest');
  });

  test('rejects public DNS, public IP, non-TLS and missing pin', () {
    for (final url in [
      'http://192.168.1.20:12345',
      'https://8.8.8.8:12345',
      'https://example.com:12345',
      'https://192.168.1.20:12345/evil',
      'https://192.168.1.20:12345?token=secret',
    ]) {
      expect(
        () => NearbyEndpoint.parse(url: url, token: token, fingerprint: pin),
        throwsFormatException,
        reason: url,
      );
    }
    expect(
      () => NearbyEndpoint.parse(
        url: 'https://127.0.0.1:12345', token: token, fingerprint: 'bad'),
      throwsFormatException,
    );
  });

  test('strictly parses versioned manifest without path traversal', () {
    final manifest = {
      'version': 1,
      'files': [
        {'name': 'homebrew.gba', 'kind': 'rom', 'size': 4,
         'sha256': List.filled(64, 'a').join()}
      ]
    };
    final offers = parseNearbyManifest(utf8.encode(jsonEncode(manifest)));
    expect(offers.single.name, 'homebrew.gba');
    expect(offers.single.index, 0);
    for (final name in ['../bad', '/etc/passwd', 'x\\y', '.hidden', 'a:b']) {
      manifest['files'] = [
        {'name': name, 'kind': 'rom', 'size': 4, 'sha256': List.filled(64, 'a').join()}
      ];
      expect(() => parseNearbyManifest(utf8.encode(jsonEncode(manifest))),
          throwsFormatException, reason: name);
    }
  });

  test('rejects duplicate names, unknown fields and huge sizes', () {
    final record = {'name': 'game.gba', 'kind': 'rom', 'size': 1,
      'sha256': List.filled(64, 'a').join()};
    final cases = [
      {'version': 2, 'files': [record]},
      {'version': 1, 'files': [record, {...record, 'name': 'GAME.GBA'}]},
      {'version': 1, 'files': [{...record, 'size': nearbyMaxFileBytes + 1}]},
      {'version': 1, 'files': [{...record, 'stranger': 'no'}]},
    ];
    for (final value in cases) {
      expect(() => parseNearbyManifest(utf8.encode(jsonEncode(value))),
          throwsFormatException);
    }
  });
}
