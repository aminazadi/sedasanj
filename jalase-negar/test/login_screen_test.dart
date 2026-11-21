import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/app/theme.dart';
import 'package:jalase_negar/features/auth/presentation/login_screen.dart';

void main() {
  Future<void> pump(WidgetTester tester) => tester.pumpWidget(
    ProviderScope(
      child: MaterialApp(
        theme: buildAppTheme(),
        locale: const Locale('fa'),
        supportedLocales: const [Locale('fa')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        home: const LoginScreen(),
      ),
    ),
  );

  testWidgets('shows the welcome art, heading and a usable phone field', (
    tester,
  ) async {
    await pump(tester);
    await tester.pump();

    expect(find.byType(Image), findsOneWidget);
    expect(find.text('ورود یا ثبت‌نام'), findsOneWidget);
    expect(find.text('شمارهٔ موبایل خود را وارد کنید.'), findsOneWidget);
    expect(find.widgetWithText(TextField, '09123456789'), findsOneWidget);
    expect(find.text('شمارهٔ موبایل'), findsNothing);
    expect(find.byIcon(Icons.phone_iphone_outlined), findsNothing);
    expect(find.widgetWithText(FilledButton, 'ارسال کد'), findsOneWidget);
    expect(find.text('شرایط استفاده'), findsOneWidget);
    expect(find.text('حریم خصوصی'), findsOneWidget);
    expect(find.byType(BackButton), findsOneWidget);
    expect(tester.takeException(), isNull);

    await tester.enterText(
      find.widgetWithText(TextField, '09123456789'),
      '09123456789',
    );
    await tester.pump();
    // The static hint text is still in the tree (just faded out), so the
    // typed value is matched among at least one widget, not exactly one.
    expect(find.text('09123456789'), findsWidgets);
  });

  testWidgets('uses the same back-arrow icon on every platform', (
    tester,
  ) async {
    // iOS/macOS get a bulkier adaptive chevron by default; the theme pins
    // one consistent arrow everywhere instead.
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    try {
      await pump(tester);
      await tester.pump();

      expect(find.byIcon(Icons.arrow_back), findsOneWidget);
      expect(find.byIcon(Icons.arrow_back_ios_new), findsNothing);
    } finally {
      debugDefaultTargetPlatformOverride = null;
    }
  });
}
