import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/app/theme.dart';
import 'package:jalase_negar/app/widgets/ss_widgets.dart';

void main() {
  testWidgets('shared header renders title and description', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: buildAppTheme(),
          home: const Scaffold(
            body: SsPageHeader(title: 'جلسه‌نگار', description: 'توضیح'),
          ),
        ),
      ),
    );
    expect(find.text('جلسه‌نگار'), findsOneWidget);
    expect(find.text('توضیح'), findsOneWidget);
  });
}
