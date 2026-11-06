import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/features/recording/application/live_transcript_session.dart';
import 'package:jalase_negar/features/recording/presentation/live_transcript_panel.dart';

Widget host(ValueNotifier<LiveTranscriptState> state) => MaterialApp(
  locale: const Locale('fa'),
  home: Directionality(
    textDirection: TextDirection.rtl,
    child: Scaffold(
      body: SizedBox(height: 320, child: LiveTranscriptPanel(state: state)),
    ),
  ),
);

void main() {
  testWidgets('says the model is loading while preparing', (tester) async {
    final state = ValueNotifier(
      const LiveTranscriptState(phase: LivePhase.preparing),
    );
    await tester.pumpWidget(host(state));
    expect(find.text('متن زنده'), findsOneWidget);
    expect(find.text('در حال آماده‌سازی…'), findsOneWidget);
    expect(
      find.textContaining('ضبط از همین حالا انجام می‌شود'),
      findsOneWidget,
    );
  });

  testWidgets('invites speech when live and empty', (tester) async {
    final state = ValueNotifier(
      const LiveTranscriptState(phase: LivePhase.listening),
    );
    await tester.pumpWidget(host(state));
    expect(find.text('زنده'), findsOneWidget);
    expect(find.textContaining('شروع به صحبت کنید'), findsOneWidget);
  });

  testWidgets('shows the live lines and cue without a retranscription hint', (
    tester,
  ) async {
    final state = ValueNotifier(
      const LiveTranscriptState(
        phase: LivePhase.listening,
        lines: ['سلام به همه', 'بریم سراغ دستور جلسه'],
        speaking: true,
      ),
    );
    await tester.pumpWidget(host(state));
    expect(find.text('سلام به همه'), findsOneWidget);
    expect(find.text('بریم سراغ دستور جلسه'), findsOneWidget);
    expect(find.text('در حال شنیدن…'), findsOneWidget);
    expect(find.textContaining('رونویسی کامل'), findsNothing);
  });

  testWidgets('follows new lines as they arrive', (tester) async {
    final state = ValueNotifier(
      LiveTranscriptState(
        phase: LivePhase.listening,
        lines: [for (var i = 0; i < 40; i++) 'جمله شماره $i'],
      ),
    );
    await tester.pumpWidget(host(state));
    await tester.pumpAndSettle();
    state.value = state.value.copyWith(
      lines: [...state.value.lines, 'آخرین جمله'],
    );
    await tester.pumpAndSettle();
    expect(find.text('آخرین جمله'), findsOneWidget);
  });

  testWidgets('shows the failure note and keeps it readable', (tester) async {
    final state = ValueNotifier(
      const LiveTranscriptState(
        phase: LivePhase.failed,
        note: 'مدل بارگذاری نشد',
      ),
    );
    await tester.pumpWidget(host(state));
    expect(find.text('متوقف شد'), findsOneWidget);
    expect(find.text('مدل بارگذاری نشد'), findsOneWidget);
  });

  testWidgets('shows the lag note under existing lines', (tester) async {
    final state = ValueNotifier(
      const LiveTranscriptState(
        phase: LivePhase.lagging,
        lines: ['سلام'],
        note: 'متن زنده کمی عقب است؛ ضبط بدون مشکل ادامه دارد.',
      ),
    );
    await tester.pumpWidget(host(state));
    expect(find.text('کمی عقب است'), findsOneWidget);
    expect(find.textContaining('ضبط بدون مشکل ادامه دارد'), findsOneWidget);
  });

  testWidgets('types a new line out character by character', (tester) async {
    final state = ValueNotifier(
      const LiveTranscriptState(phase: LivePhase.listening, lines: ['سلام']),
    );
    await tester.pumpWidget(host(state));
    state.value = state.value.copyWith(
      lines: [...state.value.lines, 'این یک جمله‌ی نسبتاً بلند برای تایپ است'],
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 30));
    await tester.pump(const Duration(milliseconds: 120));
    expect(find.text('سلام'), findsOneWidget);
    expect(find.text('این یک جمله‌ی نسبتاً بلند برای تایپ است'), findsNothing);
    expect(find.textContaining('این یک'), findsOneWidget);
    await tester.pump(const Duration(seconds: 2));
    expect(
      find.text('این یک جمله‌ی نسبتاً بلند برای تایپ است'),
      findsOneWidget,
    );
  });

  testWidgets('types faster when many lines are queued', (tester) async {
    final state = ValueNotifier(
      const LiveTranscriptState(phase: LivePhase.listening, lines: ['اول']),
    );
    await tester.pumpWidget(host(state));
    final burst = [
      for (var i = 0; i < 10; i++) 'جمله‌ی شماره $i است و ادامه دارد',
    ];
    state.value = state.value.copyWith(lines: [...state.value.lines, ...burst]);
    await tester.pump();
    await tester.pump(const Duration(seconds: 3));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text(burst.last), findsOneWidget);
  });
}
