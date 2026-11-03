import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/app/theme.dart';
import 'package:jalase_negar/app/widgets/ss_widgets.dart';
import 'package:jalase_negar/core/utils/format.dart';
import 'package:jalase_negar/features/recording/application/live_audio_waveform.dart';
import 'package:jalase_negar/features/recording/application/recorder_controller.dart';
import 'package:jalase_negar/features/recording/presentation/live_waveform.dart';
import 'package:jalase_negar/features/recording/presentation/meeting_illustration.dart';
import 'package:jalase_negar/features/recording/presentation/recording_screen.dart';

const _transcript = Key('transcript');
const _elapsed = Duration(seconds: 13);

void main() {
  test('waveform measures PCM windows across packet boundaries', () {
    final wave = LiveAudioWaveform(sampleRate: kRecordSampleRate);
    addTearDown(wave.dispose);
    const samples = kRecordSampleRate ~/ 50;
    const count = LiveAudioWaveform.barCount;
    final pcm = ByteData(samples * 4);
    for (var i = 0; i < samples; i++) {
      pcm.setInt16(i * 2, i.isEven ? -4096 : 4096, Endian.little);
    }

    var updates = 0;
    wave.addListener(() => updates++);
    final bytes = pcm.buffer.asUint8List();
    wave.addPcm(Uint8List.sublistView(bytes, 0, 17));
    expect(updates, 0);

    wave.addPcm(Uint8List.sublistView(bytes, 17));
    expect(updates, 1);
    expect(wave.amplitudeAt(count - 2), closeTo(0.625, 0.0001));
    expect(wave.amplitudeAt(count - 1), 0);
    wave.clear();
    expect(wave.amplitudeAt(count - 2), 0);
  });

  testWidgets('start disperses the art and places the monitor below the text', (
    tester,
  ) async {
    final recorder = await _openScreen(tester);
    final illustration = find.byType(MeetingIllustration);
    final particles = find.descendant(
      of: illustration,
      matching: find.byType(CustomPaint),
    );
    expect(find.byType(SvgPicture), findsOneWidget);
    expect(find.byKey(_transcript), findsNothing);

    await tester.tap(find.byIcon(Icons.mic));
    await tester.pump();
    expect(find.byType(SvgPicture), findsNothing);
    expect(particles, findsOneWidget);
    await tester.pump(const Duration(milliseconds: 450));
    expect(particles, findsOneWidget);
    await tester.pump(const Duration(milliseconds: 500));
    expect(particles, findsNothing);

    final timer = find.text(formatDuration(_elapsed));
    final wave = find.byType(LiveWaveform);
    final transcriptBounds = tester.getRect(find.byKey(_transcript));
    final timerBounds = tester.getRect(timer);
    final waveBounds = tester.getRect(wave);
    expect(
      transcriptBounds.top,
      greaterThan(tester.getBottomLeft(find.byType(SsAppBar)).dy),
    );
    expect(transcriptBounds.bottom, lessThanOrEqualTo(waveBounds.top));
    expect(waveBounds.right, lessThan(timerBounds.left));
    expect(
      waveBounds.bottom,
      lessThan(tester.getTopLeft(find.byIcon(Icons.stop)).dy),
    );
    expect(tester.widget<Text>(timer).style?.fontSize, 14);

    recorder.update(interrupted: true);
    await tester.pump();
    expect(tester.widget<LiveWaveform>(wave).active, isFalse);
    expect(find.byKey(_transcript), findsOneWidget);
    recorder.update();
    await tester.pump();
    expect(tester.widget<LiveWaveform>(wave).active, isTrue);

    await tester.tap(find.byIcon(Icons.pause));
    await tester.pump();
    expect(tester.widget<LiveWaveform>(wave).active, isFalse);
    await tester.tap(find.byIcon(Icons.play_arrow));
    await tester.pump();
    expect(tester.widget<LiveWaveform>(wave).active, isTrue);
    expect(find.byType(SvgPicture), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('reduced motion hides the artwork immediately', (tester) async {
    await _openScreen(tester, reducedMotion: true);
    await tester.tap(find.byIcon(Icons.mic));
    await tester.pump();

    expect(find.byType(SvgPicture), findsNothing);
    expect(
      find.descendant(
        of: find.byType(MeetingIllustration),
        matching: find.byType(CustomPaint),
      ),
      findsNothing,
    );
    expect(find.byKey(_transcript), findsOneWidget);
  });
}

Future<_Recorder> _openScreen(
  WidgetTester tester, {
  bool reducedMotion = false,
}) async {
  final recorder = _Recorder();
  tester.view.physicalSize = const Size(360, 640);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  await tester.pumpWidget(
    ProviderScope(
      overrides: [recorderControllerProvider.overrideWith(() => recorder)],
      child: MaterialApp(
        theme: buildAppTheme(),
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(
            context,
          ).copyWith(disableAnimations: reducedMotion),
          child: Directionality(
            textDirection: TextDirection.rtl,
            child: child!,
          ),
        ),
        home: const RecordingScreen(
          liveTranscript: SizedBox.expand(key: _transcript),
        ),
      ),
    ),
  );
  await tester.pump();
  return recorder;
}

class _Recorder extends RecorderController {
  void update({bool interrupted = false}) {
    state = RecorderState(
      status: RecorderStatus.recording,
      elapsed: _elapsed,
      interrupted: interrupted,
    );
  }

  @override
  Future<void> start() async => update();

  @override
  Future<void> pause() async =>
      state = state.copyWith(status: RecorderStatus.paused);

  @override
  Future<void> resume() async => update();
}
