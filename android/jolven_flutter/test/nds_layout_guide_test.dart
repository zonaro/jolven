import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jolven_flutter/src/nds_external_layout_guide.dart';

void main() {
  testWidgets('Nintendo DS guide changes preview without controlling external apps',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      locale: Locale('en'),
      supportedLocales: [Locale('en')],
      home: NdsExternalLayoutGuide(),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Nintendo DS screens'), findsOneWidget);
    expect(find.text('Top screen'), findsOneWidget);
    expect(find.text('Touch screen'), findsOneWidget);
    await tester.tap(find.text('Side by side'));
    await tester.pumpAndSettle();
    expect(find.text('Top screen'), findsOneWidget);
  });
}
