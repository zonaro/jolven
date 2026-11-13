import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jolven_flutter/src/nds_external_layout_guide.dart';

void main() {
  testWidgets('Nintendo DS layout preview toggles without native emulator APIs',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: NdsExternalLayoutGuide(),
    ));
    await tester.pumpAndSettle();

    final selector = find.byType(SegmentedButton<NdsPreviewOrientation>);
    expect(find.byType(NdsExternalLayoutGuide), findsOneWidget);
    expect(selector, findsOneWidget);
    expect(tester.widget<SegmentedButton<NdsPreviewOrientation>>(selector)
        .selected, contains(NdsPreviewOrientation.stacked));

    await tester.tap(find.byIcon(Icons.view_column_outlined));
    await tester.pumpAndSettle();

    expect(tester.widget<SegmentedButton<NdsPreviewOrientation>>(selector)
        .selected, contains(NdsPreviewOrientation.sideBySide));
  });
}
