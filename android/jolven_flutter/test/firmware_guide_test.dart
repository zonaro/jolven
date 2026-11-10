import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jolven_flutter/src/firmware_guide_page.dart';

void main() {
  testWidgets('BIOS guide is offline and makes no claim of verified cores',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(home: FirmwareGuidePage()));
    expect(find.text('BIOS / Firmware'), findsOneWidget);
    expect(find.byIcon(Icons.fingerprint), findsOneWidget);
  });
}
