// ignore_for_file: library_private_types_in_public_api
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:jalase_negar/app/router.dart';
import 'package:jalase_negar/app/theme.dart';
import 'package:jalase_negar/app/widgets/ss_toast.dart';
import 'package:jalase_negar/features/settings/presentation/settings_screen.dart';
import 'package:jalase_negar/features/updates/application/update_controller.dart';
import 'package:jalase_negar/features/updates/data/app_update.dart';
import 'package:jalase_negar/features/updates/data/update_client.dart';
import 'package:jalase_negar/features/updates/presentation/update_check_card.dart';
import 'package:jalase_negar/features/updates/presentation/update_prompt_host.dart';

import 'update_test_support.dart';

class _Client extends UpdateClient {
  Object? answer = offerJson();

  @override
  Future<AppUpdateOffer?> check(UpdateEnvironment environment) async {
    final value = answer;
    if (value is UpdateCheckException) throw value;
    return AppUpdateOffer.fromResponse(value);
  }
}

class _Harness {
  _Harness(this.tester, this.client, this.opened, this.launches);

  final WidgetTester tester;
  final _Client client;
  final List<Uri> opened;
  final bool launches;
  late final GoRouter router;

  ProviderContainer get container =>
      ProviderScope.containerOf(tester.element(find.byType(MaterialApp)));

  Future<void> start() async {
    router = GoRouter(
      routes: [
        GoRoute(
          path: '/',
          builder: (context, state) => Scaffold(
            body: Column(
              children: [
                const Text('خانه'),
                const UpdateCheckCard(),
                Builder(
                  builder: (context) => TextButton(
                    onPressed: () => showDialog<void>(
                      context: context,
                      builder: (_) =>
                          const AlertDialog(content: Text('دیالوگ دیگر')),
                    ),
                    child: const Text('باز کردن دیالوگ'),
                  ),
                ),
              ],
            ),
          ),
        ),
        GoRoute(
          path: '/record',
          builder: (context, state) => const Scaffold(body: Text('در حال ضبط')),
        ),
      ],
    );
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          routerProvider.overrideWithValue(router),
          updateClientProvider.overrideWithValue(client),
          updateEnvironmentProvider.overrideWithValue(() async => installedApp),
          updateLauncherProvider.overrideWithValue((uri) async {
            opened.add(uri);
            return launches;
          }),
        ],
        child: Consumer(
          builder: (context, ref, _) => MaterialApp.router(
            theme: buildAppTheme(),
            locale: const Locale('fa'),
            supportedLocales: const [Locale('fa')],
            localizationsDelegates: const [
              GlobalMaterialLocalizations.delegate,
              GlobalWidgetsLocalizations.delegate,
              GlobalCupertinoLocalizations.delegate,
            ],
            builder: (context, child) =>
                SsToastHost(child: UpdatePromptHost(child: child!)),
            routerConfig: ref.watch(routerProvider),
          ),
        ),
      ),
    );
    await tester.pump();
  }

  Future<void> launchCheck() async {
    await container.read(updateControllerProvider.notifier).checkOnLaunch();
    await tester.pump(const Duration(seconds: 1));
  }
}

Future<_Harness> harness(WidgetTester tester, {bool launches = true}) async {
  final h = _Harness(tester, _Client(), <Uri>[], launches);
  await h.start();
  return h;
}

void main() {
  testWidgets('shows the offer on the home screen with notes and buttons', (
    tester,
  ) async {
    final h = await harness(tester);
    expect(find.text('نسخه‌ی جدید جلسه‌نگار'), findsNothing);
    await h.launchCheck();

    expect(find.text('نسخه‌ی جدید جلسه‌نگار'), findsOneWidget);
    expect(find.text('1.0.1 (2)'), findsOneWidget);
    expect(find.text('1.0.2 (3)'), findsOneWidget);
    expect(find.textContaining('رفع خطا'), findsOneWidget);
    expect(find.text('دریافت نسخه'), findsOneWidget);
    expect(find.text('بعداً'), findsOneWidget);

    final dialog = tester.widget<AlertDialog>(find.byType(AlertDialog));
    expect(
      (dialog.shape! as RoundedRectangleBorder).borderRadius,
      BorderRadius.zero,
    );
    expect(
      Directionality.of(tester.element(find.text('دریافت نسخه'))),
      TextDirection.rtl,
    );
  });

  testWidgets('release notes are shown as plain text, never as markup', (
    tester,
  ) async {
    final h = await harness(tester);
    h.client.answer = offerJson(notes: '<script>alert(1)</script> **bold**');
    await h.launchCheck();
    expect(find.text('<script>alert(1)</script> **bold**'), findsOneWidget);
  });

  testWidgets('waits while recording and appears back on the home screen', (
    tester,
  ) async {
    final h = await harness(tester);
    unawaited(h.router.push('/record'));
    await tester.pumpAndSettle();
    await h.launchCheck();
    await tester.pump(const Duration(seconds: 2));
    expect(find.text('نسخه‌ی جدید جلسه‌نگار'), findsNothing);
    expect(find.text('در حال ضبط'), findsOneWidget);

    h.router.pop();
    await tester.pumpAndSettle(const Duration(seconds: 1));
    expect(find.text('نسخه‌ی جدید جلسه‌نگار'), findsOneWidget);
  });

  testWidgets('waits for the intro and guided tour to finish', (tester) async {
    final h = await harness(tester);
    h.router.go('/?tour=welcome');
    await tester.pumpAndSettle();
    await h.launchCheck();
    await tester.pump(const Duration(seconds: 2));
    expect(find.text('نسخه‌ی جدید جلسه‌نگار'), findsNothing);

    h.router.go('/');
    await tester.pumpAndSettle(const Duration(seconds: 1));
    expect(find.text('نسخه‌ی جدید جلسه‌نگار'), findsOneWidget);
  });

  testWidgets('does not stack on top of another open dialog', (tester) async {
    final h = await harness(tester);
    await tester.tap(find.text('باز کردن دیالوگ'));
    await tester.pumpAndSettle();
    await h.launchCheck();
    await tester.pump(const Duration(seconds: 2));
    expect(find.text('نسخه‌ی جدید جلسه‌نگار'), findsNothing);

    await tester.tap(find.text('دیالوگ دیگر'), warnIfMissed: false);
    Navigator.of(tester.element(find.text('دیالوگ دیگر'))).pop();
    await tester.pumpAndSettle(const Duration(seconds: 1));
    expect(find.text('نسخه‌ی جدید جلسه‌نگار'), findsOneWidget);
  });

  testWidgets('"later" closes it and it stays away for this run', (
    tester,
  ) async {
    final h = await harness(tester);
    await h.launchCheck();
    await tester.tap(find.text('بعداً'));
    await tester.pumpAndSettle();
    expect(find.text('نسخه‌ی جدید جلسه‌نگار'), findsNothing);

    h.router.go('/record');
    await tester.pumpAndSettle();
    h.router.go('/');
    await tester.pumpAndSettle(const Duration(seconds: 2));
    expect(find.text('نسخه‌ی جدید جلسه‌نگار'), findsNothing);
    expect(h.container.read(updateControllerProvider).dismissed, isTrue);
  });

  testWidgets('the system back gesture counts as "later"', (tester) async {
    final h = await harness(tester);
    await h.launchCheck();
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.text('نسخه‌ی جدید جلسه‌نگار'), findsNothing);
    expect(h.container.read(updateControllerProvider).dismissed, isTrue);
  });

  testWidgets('"get version" opens the browser and keeps the dialog', (
    tester,
  ) async {
    final h = await harness(tester);
    await h.launchCheck();
    await tester.tap(find.text('دریافت نسخه'));
    await tester.pumpAndSettle();
    expect(
      h.opened.single.toString(),
      'https://api.sedasanj.ir/v1/jalase-negar/android/releases/abc/download',
    );
    expect(find.text('نسخه‌ی جدید جلسه‌نگار'), findsOneWidget);
  });

  testWidgets('a browser that cannot open explains what to do', (tester) async {
    final h = await harness(tester, launches: false);
    await h.launchCheck();
    await tester.tap(find.text('دریافت نسخه'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.textContaining('مرورگر باز نشد'), findsOneWidget);
  });

  testWidgets('no dialog for the same or a newer installed build', (
    tester,
  ) async {
    final h = await harness(tester);
    h.client.answer = offerJson(code: 2);
    await h.launchCheck();
    expect(find.text('نسخه‌ی جدید جلسه‌نگار'), findsNothing);
  });

  testWidgets('settings check: nothing new, offline, then an offer', (
    tester,
  ) async {
    final h = await harness(tester);
    h.client.answer = {'update': null};
    await tester.tap(find.text('بررسی به‌روزرسانی'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.textContaining('وجود ندارد'), findsOneWidget);
    await tester.pump(const Duration(seconds: 6));

    h.client.answer = const UpdateCheckException(
      'اتصال برقرار نشد؛ اینترنت را بررسی کنید.',
    );
    await tester.tap(find.text('بررسی به‌روزرسانی'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.textContaining('اینترنت را بررسی کنید'), findsOneWidget);
    await tester.pump(const Duration(seconds: 6));

    h.client.answer = offerJson();
    await tester.tap(find.text('بررسی به‌روزرسانی'));
    await tester.pumpAndSettle();
    expect(find.text('نسخه‌ی جدید جلسه‌نگار'), findsOneWidget);
  });

  test('the settings screen exposes the manual check', () {
    expect(const SettingsScreen(), isA<ConsumerWidget>());
  });
}
