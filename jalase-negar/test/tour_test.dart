import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/app/router.dart';
import 'package:jalase_negar/app/theme.dart';
import 'package:jalase_negar/core/db/app_database.dart';
import 'package:jalase_negar/core/providers.dart';
import 'package:jalase_negar/features/meetings/application/meeting_providers.dart';
import 'package:jalase_negar/features/models/application/models_controller.dart';
import 'package:jalase_negar/features/onboarding/tour_overlay.dart';
import 'package:jalase_negar/features/onboarding/tour_step.dart';
import 'package:jalase_negar/features/recording/application/recorder_controller.dart';
import 'package:jalase_negar/features/upload/upload_controller.dart';
import 'package:sqflite/sqflite.dart';

void main() {
  testWidgets('first run visits live screens and completion survives restart', (
    tester,
  ) async {
    final db = _SettingsDatabase();
    await _launch(tester, db);
    _expectStep(TourStep.welcome);
    await _tap(tester, 'شروع راهنما');
    _expectStep(TourStep.models);

    // Tapping a highlighted control advances the tour.
    await tester.tapAt(tester.getCenter(find.text('مدل‌های هوش مصنوعی')));
    await _frame(tester);
    _expectStep(TourStep.recording);

    await tester.tapAt(tester.getCenter(find.byIcon(Icons.mic).first));
    await _frame(tester);
    _expectStep(TourStep.live);
    await tester.binding.handlePopRoute();
    await _frame(tester);
    _expectStep(TourStep.recording);

    for (final step in TourStep.values.skip(TourStep.live.index)) {
      await _tap(tester, 'مرحلهٔ بعد');
      _expectStep(step);
    }
    expect(db.settings, isEmpty);
    await _tap(tester, 'پایان راهنما');
    expect(find.byType(TourOverlay), findsNothing);
    expect(db.settings.values, ['1']);

    await tester.pumpWidget(const SizedBox());
    await _launch(tester, db);
    expect(find.byType(TourOverlay), findsNothing);
  });

  testWidgets('skipping is remembered and settings can replay the tour', (
    tester,
  ) async {
    final db = _SettingsDatabase();
    await _launch(tester, db);
    await _tap(tester, 'رد کردن راهنما');
    expect(find.byType(TourOverlay), findsNothing);
    expect(db.settings.values, ['1']);

    await _tap(tester, 'تنظیمات');
    final replay = find.text('راهنمای تعاملی');
    await tester.scrollUntilVisible(replay, 90);
    await _tap(tester, 'راهنمای تعاملی');
    _expectStep(TourStep.welcome);
    await _tap(tester, 'رد کردن راهنما');
    expect(find.text('وضعیت اتصال'), findsOneWidget);
    await tester.scrollUntilVisible(replay, 90);
    expect(replay, findsOneWidget);

    await tester.pumpWidget(const SizedBox());
    await _launch(tester, db);
    expect(find.byType(TourOverlay), findsNothing);
  });

  testWidgets('a failed write can be retried or bypassed for this launch', (
    tester,
  ) async {
    final db = _SettingsDatabase()..failWrites = true;
    await _launch(tester, db);
    await _tap(tester, 'رد کردن راهنما');
    expect(find.textContaining('JN-TOUR-0001'), findsOneWidget);
    await _tap(tester, 'ادامه بدون ذخیره');
    expect(find.byType(TourOverlay), findsNothing);
    expect(db.settings, isEmpty);

    await tester.pumpWidget(const SizedBox());
    await _launch(tester, db);
    _expectStep(TourStep.welcome);
    await _tap(tester, 'رد کردن راهنما');
    db.failWrites = false;
    await _tap(tester, 'رد کردن راهنما');
    expect(find.byType(TourOverlay), findsNothing);
    expect(db.settings.values, ['1']);
  });
}

void _expectStep(TourStep step) {
  expect(find.text(step.title), findsOneWidget);
  expect(find.byType(TourOverlay), findsOneWidget);
}

Future<void> _frame(WidgetTester tester) async {
  await tester.pump();
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 800));
  await tester.pump();
}

Future<void> _tap(WidgetTester tester, String label) async {
  final button = find.text(label);
  await tester.ensureVisible(button);
  await tester.pump();
  await tester.tap(button);
  await _frame(tester);
}

Future<void> _launch(WidgetTester tester, _SettingsDatabase db) async {
  tester.view.physicalSize = const Size(390, 844);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        appDatabaseProvider.overrideWith((ref) async => db),
        meetingsProvider.overrideWith((ref) async => []),
        modelsControllerProvider.overrideWith(_IdleModels.new),
        recorderControllerProvider.overrideWith(_IdleRecorder.new),
        uploadQueueProvider.overrideWith(_IdleUpload.new),
      ],
      child: Consumer(
        builder: (context, ref, child) => MaterialApp.router(
          routerConfig: ref.watch(routerProvider),
          theme: buildAppTheme(),
          locale: const Locale('fa'),
          supportedLocales: const [Locale('fa')],
          localizationsDelegates: GlobalMaterialLocalizations.delegates,
        ),
      ),
    ),
  );
  await _frame(tester);
}

class _SettingsDatabase implements AppDatabase {
  final settings = <String, String>{};
  bool failWrites = false;

  @override
  Database get db => throw UnsupportedError('SQL is not needed in this test');

  @override
  Future<String?> getSetting(String key) async =>
      key == 'intro_slides_seen' ? '1' : settings[key];

  @override
  Future<void> setSetting(String key, String value) async {
    if (failWrites) throw StateError('Settings storage is unavailable');
    settings[key] = value;
  }
}

class _IdleModels extends ModelsController {
  @override
  ModelsState build() => const ModelsState(loading: false);
}

class _IdleRecorder extends RecorderController {
  @override
  Future<void> start() async => throw StateError('The tour must not record');
}

class _IdleUpload extends UploadController {
  @override
  UploadState build() => const UploadState();
}
