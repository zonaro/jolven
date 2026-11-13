import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';

/// Read-only RetroAchievements Web API response. Never unlocks achievements.
class AchievementProgress {
  const AchievementProgress({
    required this.gameTitle,
    required this.consoleName,
    required this.total,
    required this.earned,
    required this.hardcore,
  });

  final String gameTitle;
  final String consoleName;
  final int total;
  final int earned;
  final int hardcore;

  factory AchievementProgress.parse(Map<dynamic, dynamic> json) {
    int number(dynamic value) => value is int
        ? value
        : int.tryParse(value.toString()) ?? 0;

    final total = number(json['NumAchievements']);
    final earned = number(json['NumAwardedToUser']);
    final hardcore = number(json['NumAwardedToUserHardcore']);

    if (json['Title'] is! String || total < 0 ||
        earned < 0 || hardcore < 0) {
      throw const FormatException('Malformed achievement progress');
    }
    return AchievementProgress(
      gameTitle: json['Title'] as String,
      consoleName: json['ConsoleName']?.toString() ?? '',
      total: total,
      earned: earned,
      hardcore: hardcore,
    );
  }
}

/// Uses only the official RetroAchievements API over TLS and does not persist
/// the Web API key. The key is sent in the 'y' query param required by RA.
class AchievementProgressClient {
  const AchievementProgressClient();

  Future<AchievementProgress> load({
    required String username,
    required String apiKey,
    required int gameId,
  }) async {
    if (username.trim().isEmpty || apiKey.trim().isEmpty || gameId <= 0) {
      throw const FormatException('Missing parameters');
    }

    final uri = Uri.https(
      'retroachievements.org',
      '/API/API_GetGameInfoAndUserProgress.php',
      {'u': username.trim(), 'g': gameId.toString(), 'y': apiKey.trim()},
    );
    final client = HttpClient()
      ..connectionTimeout = const Duration(seconds: 12);
    try {
      final request = await client.getUrl(uri);
      request.followRedirects = false;
      request.headers.set(HttpHeaders.acceptHeader, 'application/json');
      final response = await request.close().timeout(const Duration(seconds: 20));
      if (response.statusCode != HttpStatus.ok) {
        throw const HttpException('Remote service error');
      }

      final bytes = <int>[];
      await for (final chunk in response.timeout(const Duration(seconds: 20))) {
        if (bytes.length + chunk.length > 3 * 1024 * 1024) {
          throw const FormatException('Response too large');
        }
        bytes.addAll(chunk);
      }
      final json = jsonDecode(utf8.decode(bytes));
      if (json is! Map) throw const FormatException('No result');
      return AchievementProgress.parse(json);
    } finally {
      client.close(force: true);
    }
  }
}

class RetroAchievementsPage extends StatefulWidget {
  const RetroAchievementsPage({super.key});

  @override
  State<RetroAchievementsPage> createState() => _RetroAchievementsPageState();
}

class _RetroAchievementsPageState extends State<RetroAchievementsPage> {
  final _username = TextEditingController();
  final _apiKey = TextEditingController();
  final _gameId = TextEditingController();
  final _client = const AchievementProgressClient();

  bool _loading = false;
  AchievementProgress? _progress;
  String? _error;

  @override
  void dispose() {
    _username.dispose();
    _apiKey.clear();
    _apiKey.dispose();
    _gameId.dispose();
    super.dispose();
  }

  Future<void> _request() async {
    if (_loading) return;
    final gameId = int.tryParse(_gameId.text.trim());
    if (_username.text.trim().isEmpty || _apiKey.text.trim().isEmpty ||
        gameId == null || gameId <= 0) {
      setState(() {
        _error = 'invalid';
        _progress = null;
      });
      return;
    }

    setState(() {
      _loading = true;
      _error = null;
      _progress = null;
    });
    try {
      final result = await _client.load(
        username: _username.text.trim(),
        apiKey: _apiKey.text,
        gameId: gameId,
      );
      if (mounted) setState(() => _progress = result);
    } catch (_) {
      // No exception.toString(): it might expose a URL containing the API key.
      if (mounted) setState(() => _error = 'network');
    } finally {
      if (mounted) setState(() => _loading = false);
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

    return Scaffold(
      appBar: AppBar(title: const Text('RetroAchievements')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(t(
            'Consulta opcional: o Jolven lê seu progresso oficial. O desbloqueio de conquistas e o modo hardcore pertencem ao RetroArch ou outro emulador compatível.',
            'Optional read-only lookup of your official progress. Achievement unlocking and hardcore mode belong to RetroArch or another compatible emulator.',
            'Consulta opcional de progreso oficial. Los desbloqueos y el modo hardcore son gestionados por RetroArch u otro emulador compatible.',
          )),
          const SizedBox(height: 8),
          Text(t(
            'Use seu Web API Key do painel do RetroAchievements. A chave só fica nesta tela e não é armazenada. O ID do jogo precisa ser informado manualmente; o Jolven ainda não o associa pelo hash da ROM.',
            'Use your RetroAchievements Web API Key. The key stays only in this screen and is not saved. Enter the game ID manually; ROM hash mapping is not implemented yet.',
            'Usa tu Web API Key. La clave solo permanece en esta pantalla y no se guarda. Introduce el ID del juego manualmente; el vínculo por hash aún no existe.',
          ), style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 16),
          TextField(
            controller: _username,
            maxLength: 72,
            decoration: InputDecoration(labelText:
              t('Usuário / ULID', 'Username / ULID', 'Usuario / ULID')),
          ),
          TextField(
            controller: _apiKey,
            obscureText: true,
            enableSuggestions: false,
            autocorrect: false,
            decoration: InputDecoration(labelText: 'Web API Key'),
          ),
          TextField(
            controller: _gameId,
            keyboardType: TextInputType.number,
            decoration: InputDecoration(labelText:
              t('ID do jogo no RetroAchievements',
                'RetroAchievements game ID',
                'ID del juego en RetroAchievements')),
          ),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: _loading ? null : _request,
            icon: const Icon(Icons.sync),
            label: Text(t('Consultar progresso', 'Check progress',
                'Consultar progreso')),
          ),
          if (_loading) const LinearProgressIndicator(),
          if (_error != null) Padding(
            padding: const EdgeInsets.only(top: 16),
            child: Text(_error == 'invalid'
                ? t('Preencha usuário, chave e ID válido.',
                    'Enter a username, key and valid game ID.',
                    'Introduce usuario, clave e ID válido.')
                : t('Não foi possível consultar. Confira a conexão, a chave e o ID.',
                    'Could not fetch progress. Check connection, key and game ID.',
                    'No se pudo consultar. Revisa conexión, clave e ID.')),
          ),
          if (_progress case final progress?) ...[
            const SizedBox(height: 20),
            Text(progress.gameTitle,
                style: Theme.of(context).textTheme.titleLarge),
            Text(progress.consoleName),
            ListTile(
              title: Text(t('Conquistas obtidas', 'Achievements earned',
                  'Logros conseguidos')),
              trailing: Text('${progress.earned}/${progress.total}'),
            ),
            ListTile(
              title: Text('Hardcore'),
              trailing: Text('${progress.hardcore}/${progress.total}'),
            ),
          ],
        ],
      ),
    );
  }
}
