import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jolven_flutter/src/nds_external_layout_guide.dart';

void main() {
  testWidgets('Nintendo DS guide changes preview without controlling external apps',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      locale: Locale('pt'),
      supportedLocales: [Locale('pt'), Locale('en'), Locale('es')],
      home: NdsExternalLayoutGuide(),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Telas do Nintendo DS'), findsOneWidget);
    expect(find.text('Tela superior'), findsOneWidget);
    expect(find.text('Tela de toque'), findsOneWidget);
    await tester.tap(find.text('Lado a lado'));
    await tester.pumpAndSettle();
    expect(find.text('Tela superior'), findsOneWidget);
  });
}
