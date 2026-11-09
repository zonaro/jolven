import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jolven_flutter/main.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('jolven/external_emulators');

  setUp(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      switch (call.method) {
        case 'listEmulators':
        case 'listAndroidGames':
        case 'listRoms':
          return <Map<String, Object?>>[];
        default:
          throw PlatformException(code: 'UNEXPECTED_CALL', message: call.method);
      }
    });
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  testWidgets('Jolven launches without a bundled emulator', (tester) async {
    await tester.pumpWidget(const JolvenApp());
    await tester.pumpAndSettle();
    expect(find.text('Jolven'), findsOneWidget);
    expect(find.byType(FloatingActionButton), findsOneWidget);
  });
}
