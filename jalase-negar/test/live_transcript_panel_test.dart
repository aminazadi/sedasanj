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

  testWidgets('shows lines, the listening cue and the draft caption', (
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
    expect(find.textContaining('پیش‌نویس زنده'), findsOneWidget);
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
}
