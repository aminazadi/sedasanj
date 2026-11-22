import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:jalase_negar/app/shell_screen.dart';
import 'package:jalase_negar/app/theme.dart';
import 'package:jalase_negar/core/models/model_catalog.dart';
import 'package:jalase_negar/features/meetings/application/meeting_providers.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';
import 'package:jalase_negar/features/meetings/presentation/meetings_screen.dart';
import 'package:jalase_negar/features/models/application/models_controller.dart';
import 'package:jalase_negar/features/people/application/people_providers.dart';
import 'package:jalase_negar/features/upload/upload_controller.dart';

// The search box and status filter live in the app shell's header (not on
// the meetings screen itself), so these tests drive ShellScreen as a whole.

Meeting _meeting(String id, String title, MeetingStatus status) => Meeting(
  id: id,
  title: title,
  createdAt: DateTime(2026, 11, 4),
  duration: const Duration(seconds: 30),
  audioPath: '/$id.wav',
  sampleRate: 16000,
  channels: 1,
  status: status,
);

void main() {
  final a = _meeting('a', 'جلسهٔ الف', MeetingStatus.complete);
  final b = _meeting('b', 'جلسهٔ ب', MeetingStatus.failed);

  Future<void> pump(WidgetTester tester) async {
    tester.view.physicalSize = const Size(400, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final router = GoRouter(
      routes: [
        ShellRoute(
          builder: (context, state, child) => ShellScreen(child: child),
          routes: [
            GoRoute(
              path: '/',
              builder: (context, state) => const MeetingsScreen(),
            ),
          ],
        ),
      ],
    );
    addTearDown(router.dispose);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          meetingsProvider.overrideWith((ref) async => [a, b]),
          meetingPreviewProvider('a').overrideWith((ref) async => ''),
          meetingPreviewProvider('b').overrideWith((ref) async => ''),
          transcriptMatchesProvider('بودجه').overrideWith((ref) async => {'b'}),
          uploadQueueProvider.overrideWith(_Idle.new),
          speakerAnalysisProvider.overrideWith(_IdleAnalysis.new),
          speakerSyncProvider.overrideWith(_IdleSpeakerSync.new),
          modelsControllerProvider.overrideWith(_ReadyModels.new),
        ],
        child: MaterialApp.router(
          theme: buildAppTheme(),
          builder: (context, child) =>
              Directionality(textDirection: TextDirection.rtl, child: child!),
          routerConfig: router,
        ),
      ),
    );
    // Not pumpAndSettle: ShellScreen's record button pulses forever.
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
  }

  testWidgets('search finds a meeting by its transcript text', (tester) async {
    await pump(tester);
    expect(find.text('جلسهٔ الف'), findsOneWidget);
    await tester.tap(find.byTooltip('جست‌وجو'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    await tester.enterText(find.byType(TextField), 'بودجه');
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.text('جلسهٔ الف'), findsNothing);
    expect(find.text('جلسهٔ ب'), findsOneWidget);

    // Closing search drops the query and returns to the normal header.
    await tester.tap(find.byTooltip('بستن جست‌وجو'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.byType(TextField), findsNothing);
    expect(find.text('جلسهٔ الف'), findsOneWidget);
  });

  testWidgets('filters live in a popup menu in the header', (tester) async {
    await pump(tester);
    expect(find.text('ناموفق'), findsNothing);
    await tester.tap(find.byTooltip('فیلتر جلسه‌ها'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    await tester.tap(find.text('ناموفق'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.text('جلسهٔ الف'), findsNothing);
    expect(find.text('جلسهٔ ب'), findsOneWidget);
  });
}

class _Idle extends UploadController {
  @override
  UploadState build() => const UploadState();
}

class _IdleAnalysis extends SpeakerAnalysisController {
  @override
  SpeakerAnalysisState build() => const SpeakerAnalysisState();
}

class _IdleSpeakerSync extends SpeakerSyncController {
  @override
  SpeakerSyncState build() => const SpeakerSyncState();
}

class _ReadyModels extends ModelsController {
  @override
  ModelsState build() => ModelsState(
    loading: false,
    items: [
      for (final spec in ModelCatalog.all)
        ModelItemState(spec: spec, installed: true, selected: true),
    ],
  );
}
