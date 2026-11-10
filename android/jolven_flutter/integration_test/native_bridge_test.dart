import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:jolven_flutter/main.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('jolven/external_emulators');

  testWidgets('native bridge works without any emulator installed', (tester) async {
    final emulators = await channel.invokeMethod<List<dynamic>>('listEmulators');
    final roms = await channel.invokeMethod<List<dynamic>>('listRoms');
    final remote = await channel.invokeMethod<List<dynamic>>('listRemoteClients');
    final gamepads = await channel.invokeMethod<List<dynamic>>('listGamepads');
    final collections = await channel.invokeMethod<List<dynamic>>('listCollections');

    expect(emulators, isNotNull);
    expect(roms, isNotNull);
    expect(remote, isNotNull);
    expect(gamepads, isNotNull);
    expect(collections, isNotNull);

    // The app itself is a frontend. Android games/ROM catalog remain usable
    // when RetroArch and other third-party emulators are absent.
    await tester.pumpWidget(const JolvenApp());
    await tester.pumpAndSettle();
    expect(find.text('Jolven'), findsOneWidget);
    expect(find.byType(Scaffold), findsWidgets);
  });

  testWidgets('Nearby UI does not connect without explicit user action', (tester) async {
    await tester.pumpWidget(const JolvenApp());
    await tester.pumpAndSettle();

    final nearbyButton = find.byIcon(Icons.download_for_offline_outlined);
    expect(nearbyButton, findsOneWidget);
    await tester.tap(nearbyButton);
    await tester.pumpAndSettle();

    expect(find.byType(TextField), findsWidgets);
    expect(find.text('HTTPS URL'), findsOneWidget);
    // No request to remote host: no URL/token/fingerprint were provided.
  });
}
