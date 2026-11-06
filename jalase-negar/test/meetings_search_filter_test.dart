import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/app/theme.dart';
import 'package:jalase_negar/features/meetings/application/meeting_providers.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';
import 'package:jalase_negar/features/meetings/presentation/meetings_screen.dart';
import 'package:jalase_negar/features/upload/upload_controller.dart';

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
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          meetingsProvider.overrideWith((ref) async => [a, b]),
          meetingPreviewProvider('a').overrideWith((ref) async => ''),
          meetingPreviewProvider('b').overrideWith((ref) async => ''),
          transcriptMatchesProvider('بودجه').overrideWith((ref) async => {'b'}),
          uploadQueueProvider.overrideWith(_Idle.new),
        ],
        child: MaterialApp(
          theme: buildAppTheme(),
          builder: (context, child) =>
              Directionality(textDirection: TextDirection.rtl, child: child!),
          home: const Scaffold(body: MeetingsScreen()),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('search finds a meeting by its transcript text', (tester) async {
    await pump(tester);
    expect(find.text('جلسهٔ الف'), findsOneWidget);
    await tester.enterText(find.byType(TextField), 'بودجه');
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pumpAndSettle();
    expect(find.text('جلسهٔ الف'), findsNothing);
    expect(find.text('جلسهٔ ب'), findsOneWidget);
  });

  testWidgets('filters live in a dropdown beside the search field', (
    tester,
  ) async {
    await pump(tester);
    expect(find.text('ناموفق'), findsNothing);
    await tester.tap(find.byTooltip('فیلتر جلسه‌ها'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('ناموفق'));
    await tester.pumpAndSettle();
    expect(find.text('جلسهٔ الف'), findsNothing);
    expect(find.text('جلسهٔ ب'), findsOneWidget);
  });
}

class _Idle extends UploadController {
  @override
  UploadState build() => const UploadState();
}
