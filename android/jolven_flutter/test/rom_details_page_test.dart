import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jolven_flutter/src/models.dart';
import 'package:jolven_flutter/src/rom_details_page.dart';

const ppsspp = EmulatorInfo(
  id: 'ppsspp', name: 'PPSSPP',
  packageName: 'org.ppsspp.ppsspp',
  installed: true, romLaunch: 'view_documented',
);

void main() {
  testWidgets('details show game, console and explicit play without bundled emulator',
      (tester) async {
    const rom = RomItem(
      uri: 'content://rom/1', name: 'Homebrew.iso',
      platformId: 'psp', favorite: true, sizeBytes: 2 * 1024 * 1024,
      sha256: '1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef',
    );
    RomDetailsAction? action;
    await tester.pumpWidget(MaterialApp(
      locale: const Locale('pt'),
      supportedLocales: const [Locale('pt'), Locale('en'), Locale('es')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      home: RomDetailsPage(
        rom: rom, emulators: const [ppsspp],
        consoleDefaults: const {'psp': 'org.ppsspp.ppsspp'},
        onAction: (value) => action = value,
      ),
    ));
    expect(find.text('Detalhes do jogo'), findsOneWidget);
    expect(find.text('Homebrew'), findsOneWidget);
    expect(find.text('PSP'), findsOneWidget);
    await tester.tap(find.text('Jogar'));
    expect(action, RomDetailsAction.play);
    await tester.scrollUntilVisible(find.text('2.0 MiB'), 160);
    expect(find.text('2.0 MiB'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('Intent documentada, não testada no aparelho'), 160);
    expect(find.text('PPSSPP'), findsWidgets);
  });

  testWidgets('unknown console is explained, removal needs caller action',
      (tester) async {
    const rom = RomItem(uri: 'content://archive', name: 'unknown.zip');
    RomDetailsAction? action;
    await tester.pumpWidget(MaterialApp(
      locale: const Locale('en'),
      supportedLocales: const [Locale('pt'), Locale('en'), Locale('es')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      home: RomDetailsPage(
        rom: rom, emulators: const [],
        consoleDefaults: const {},
        onAction: (value) => action = value,
      ),
    ));
    expect(find.text('Console not identified'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.textContaining('No suitable emulator detected'), 160);
    expect(find.textContaining('No suitable emulator detected'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('Remove from library'), 160);
    await tester.tap(find.text('Remove from library'));
    expect(action, RomDetailsAction.remove);
    // No deletion happens in the details page; parent confirms and performs it.
  });
}
