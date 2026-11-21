import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/app/theme.dart';
import 'package:jalase_negar/app/widgets/ss_widgets.dart';

void main() {
  testWidgets('shared app bar renders its title', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: buildAppTheme(),
          home: Scaffold(appBar: SsAppBar(title: const Text('جلسه‌نگار'))),
        ),
      ),
    );
    expect(find.text('جلسه‌نگار'), findsOneWidget);
  });

  testWidgets(
    'a lone action keeps the standard 16px gap from the screen edge, even '
    'when the screen never set actionsPadding itself',
    (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          child: MaterialApp(
            theme: buildAppTheme(),
            home: Scaffold(
              appBar: SsAppBar(
                title: const Text('فرد'),
                actions: [
                  IconButton(
                    tooltip: 'تغییر نام',
                    onPressed: () {},
                    icon: const Icon(Icons.edit_outlined),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
      final width = tester.view.physicalSize.width / tester.view.devicePixelRatio;
      expect(
        tester.getRect(find.byType(IconButton)).right,
        width - 16,
      );
    },
  );
}
