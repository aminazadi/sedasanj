import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/features/meetings/application/meeting_providers.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';
import 'package:jalase_negar/features/meetings/presentation/audio_waveform_player.dart';
import 'package:jalase_negar/features/meetings/presentation/meeting_detail_screen.dart';
import 'package:jalase_negar/features/meetings/presentation/meetings_screen.dart';
import 'package:jalase_negar/features/upload/upload_controller.dart';

void main() {
  for (final (status, identity) in [
    (
      MeetingStatus.recorded,
      'm|device-quiet-gain-v1|segmenter:silero-vad-live',
    ),
    (MeetingStatus.transcribed, null),
  ]) {
    testWidgets('shows only saved text and playback for ${status.name}', (
      tester,
    ) async {
      await _openDetail(
        tester,
        MeetingDetail(
          meeting: _meeting(status, identity: identity),
          segments: const [
            Segment(channel: 0, startMs: 500, endMs: 600, text: 'پایان'),
            Segment(channel: 0, startMs: 0, endMs: 400, text: 'سلام'),
          ],
        ),
      );

      expect(find.text('سلام\nپایان'), findsOneWidget);
      expect(find.byTooltip('کپی'), findsOneWidget);
      expect(find.byTooltip('اشتراک‌گذاری'), findsOneWidget);
    });
  }

  testWidgets('keeps the player when no transcript was saved', (tester) async {
    await _openDetail(
      tester,
      MeetingDetail(meeting: _meeting(MeetingStatus.recorded), segments: []),
    );

    expect(find.textContaining('متنی ذخیره نشده است'), findsOneWidget);
    for (final tooltip in ['کپی', 'اشتراک‌گذاری']) {
      expect(
        tester
            .widget<IconButton>(
              find.byWidgetPredicate(
                (widget) => widget is IconButton && widget.tooltip == tooltip,
              ),
            )
            .onPressed,
        isNull,
      );
    }
  });

  testWidgets('places the timer beside compact controls below the waveform', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final meeting = _meeting(MeetingStatus.recorded);
    await _openDetail(tester, MeetingDetail(meeting: meeting, segments: []));

    final player = find.byType(AudioWaveformPlayer);
    final waveform = find.descendant(
      of: player,
      matching: find.byWidgetPredicate(
        (widget) =>
            widget is GestureDetector && widget.onHorizontalDragUpdate != null,
      ),
    );
    final timer = find.text('۰۰:۰۰ / ۰۰:۰۰');
    final mute = find.byTooltip('قطع صدا');
    final speed = find.byTooltip('افزایش سرعت پخش');
    final share = find.byTooltip('اشتراک‌گذاری فایل صوتی');
    final play = find.byTooltip('پخش فایل صوتی');

    expect(find.text(meeting.title), findsOneWidget);
    expect(tester.getTopLeft(waveform).dy - tester.getTopLeft(player).dy, 10);
    expect(
      tester.getTopLeft(timer).dy,
      greaterThan(tester.getBottomLeft(waveform).dy),
    );
    expect(tester.getCenter(timer).dy, tester.getCenter(mute).dy);
    expect(tester.getTopLeft(timer).dx, greaterThan(tester.getCenter(mute).dx));
    expect(tester.getCenter(play).dx, greaterThan(tester.getCenter(timer).dx));
    expect(tester.getCenter(mute).dx, greaterThan(tester.getCenter(speed).dx));
    expect(tester.getCenter(speed).dx, greaterThan(tester.getCenter(share).dx));
    for (final control in [mute, speed, share]) {
      final face = find.descendant(
        of: control,
        matching: find.byType(Container),
      );
      expect(tester.getSize(face), const Size(36, 36));
    }
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('failed meetings offer no audio transcription retry', (
    tester,
  ) async {
    final meeting = _meeting(MeetingStatus.failed);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          meetingsProvider.overrideWith((ref) async => [meeting]),
          meetingPreviewProvider(meeting.id).overrideWith((ref) async => ''),
          uploadQueueProvider.overrideWith(_IdleUploadController.new),
        ],
        child: const MaterialApp(home: Scaffold(body: MeetingsScreen())),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('پردازش این جلسه ناموفق بود'), findsOneWidget);
    expect(find.text('تلاش مجدد'), findsNothing);
  });
}

class _IdleUploadController extends UploadController {
  @override
  UploadState build() => const UploadState();
}

Future<void> _openDetail(WidgetTester tester, MeetingDetail detail) async {
  final meeting = detail.meeting;
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        meetingDetailProvider(meeting.id).overrideWith((ref) async => detail),
      ],
      child: MaterialApp(
        home: Directionality(
          textDirection: TextDirection.rtl,
          child: MeetingDetailScreen(meetingId: meeting.id),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();

  expect(find.byType(AudioWaveformPlayer), findsOneWidget);
  expect(find.text('متن جلسه'), findsOneWidget);
  expect(find.text('تبدیل صوت به متن'), findsNothing);
  expect(find.byIcon(Icons.transcribe), findsNothing);
}

Meeting _meeting(MeetingStatus status, {String? identity}) => Meeting(
  id: 'meeting',
  title: 'جلسهٔ تیم',
  createdAt: DateTime(2026, 11, 4),
  duration: const Duration(seconds: 30),
  audioPath: '/meeting.wav',
  sampleRate: 16000,
  channels: 1,
  status: status,
  asrIdentity: identity,
);
