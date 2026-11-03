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
}
