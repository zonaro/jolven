import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/services.dart';
import 'package:jolven_flutter/src/gamepad_diagnostics_page.dart';
import 'package:jolven_flutter/src/models.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = EventChannel('jolven/gamepad_diagnostics');

  setUp(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
          MethodChannel(channel.name),
          (call) async => null,
        );
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(MethodChannel(channel.name), null);
  });

  testWidgets('diagnostics state is limited to controllers visible in Jolven',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(home: GamepadDiagnosticsPage(
      gamepads: [GamepadInfo(id: '5', name: 'USB Gamepad')],
    )));
    await tester.pump();
    expect(find.text('USB Gamepad'), findsOneWidget);
    expect(find.textContaining('ID 5'), findsOneWidget);
    expect(find.textContaining('Pressione um botão'), findsOneWidget);
  });
}
