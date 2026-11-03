import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
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
import 'package:jalase_negar/features/recording/presentation/recording_start_sound.dart';

const _transcript = Key('transcript');
const _elapsed = Duration(seconds: 13);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

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

  testWidgets('wind and three cues finish before the recording layout opens', (
    tester,
  ) async {
    final (recorder, sound) = await _openScreen(tester);
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
    expect(find.text('۳'), findsNothing);
    expect(find.byKey(_transcript), findsNothing);
    expect(sound.playCount, 0);
    await tester.pump(const Duration(milliseconds: 450));
    expect(particles, findsOneWidget);
    await tester.pump(const Duration(milliseconds: 500));
    expect(particles, findsNothing);
    expect(find.text('۳'), findsOneWidget);
    expect(sound.playCount, 1);
    expect(find.byIcon(Icons.mic), findsNothing);

    for (final (digit, playCount) in [('۲', 2), ('۱', 3)]) {
      await tester.pump(const Duration(seconds: 1));
      expect(find.text(digit), findsOneWidget);
      expect(sound.playCount, playCount);
      expect(recorder.startCount, 0);
      expect(find.byKey(_transcript), findsNothing);
    }
    await tester.pump(const Duration(milliseconds: 999));
    expect(find.text('۱'), findsOneWidget);
    expect(recorder.startCount, 0);
    final closeGate = sound.closeGate = Completer<void>();
    await tester.pump(const Duration(milliseconds: 1));
    expect(find.text('۱'), findsNothing);
    expect(recorder.startCount, 0);
    closeGate.complete();
    await tester.pump();
    await tester.pump();
    expect(recorder.startCount, 1);
    expect(sound.closed, isTrue);

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

  testWidgets('reduced motion skips wind and keeps the countdown', (
    tester,
  ) async {
    final (recorder, sound) = await _openScreen(tester, reducedMotion: true);
    await tester.tap(find.byIcon(Icons.mic));
    await tester.pump();
    await tester.pump();

    expect(find.byType(SvgPicture), findsNothing);
    expect(
      find.descendant(
        of: find.byType(MeetingIllustration),
        matching: find.byType(CustomPaint),
      ),
      findsNothing,
    );
    expect(find.text('۳'), findsOneWidget);
    expect(sound.playCount, 1);
    expect(recorder.startCount, 0);
    expect(find.byKey(_transcript), findsNothing);
  });

  testWidgets('the header uses matching icon buttons and keeps the mic menu', (
    tester,
  ) async {
    await _openScreen(tester, reducedMotion: true);
    final mic = find.byIcon(Icons.mic_none);
    final live = find.byIcon(Icons.subtitles_outlined);
    expect(tester.getSize(mic), tester.getSize(live));
    expect(tester.getCenter(mic).dy, tester.getCenter(live).dy);
    expect(find.text('میکروفون پیش‌فرض'), findsNothing);

    await tester.tap(mic);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('میکروفون پیش‌فرض'), findsOneWidget);
    expect(find.text('به‌روزرسانی لیست'), findsOneWidget);
  });

  testWidgets('losing app focus cancels countdown before capture', (
    tester,
  ) async {
    final (recorder, sound) = await _openScreen(tester, reducedMotion: true);
    await tester.tap(find.byIcon(Icons.mic));
    await tester.pump();
    await tester.pump();
    expect(find.text('۳'), findsOneWidget);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    await tester.pump(const Duration(seconds: 4));
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    expect(sound.closed, isTrue);
    expect(sound.playCount, 1);
    expect(recorder.startCount, 0);
    expect(find.byIcon(Icons.mic), findsOneWidget);
  });

  test(
    'countdown audio failure reports a code and releases the player',
    () async {
      final messenger =
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      const channel = MethodChannel('com.ryanheise.just_audio.methods');
      messenger.setMockMethodCallHandler(channel, (call) async {
        if (call.method == 'init') throw PlatformException(code: 'unavailable');
        return <String, dynamic>{};
      });
      addTearDown(() => messenger.setMockMethodCallHandler(channel, null));

      final messages = <String?>[];
      final previousDebugPrint = debugPrint;
      debugPrint = (message, {wrapWidth}) => messages.add(message);
      addTearDown(() => debugPrint = previousDebugPrint);

      final sound = RecordingStartSound();
      await sound.play();
      await sound.play();
      await sound.close();
      expect(
        messages.where((message) => message?.startsWith('JN-REC-0002') ?? false),
        hasLength(1),
      );
    },
  );
}

Future<(_Recorder, _StartSound)> _openScreen(
  WidgetTester tester, {
  bool reducedMotion = false,
}) async {
  final recorder = _Recorder();
  final sound = _StartSound();
  tester.view.physicalSize = const Size(360, 640);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        recorderControllerProvider.overrideWith(() => recorder),
        recordingStartSoundProvider.overrideWithValue(() => sound),
      ],
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
  return (recorder, sound);
}

class _Recorder extends RecorderController {
  int startCount = 0;

  void update({bool interrupted = false}) {
    state = RecorderState(
      status: RecorderStatus.recording,
      elapsed: _elapsed,
      interrupted: interrupted,
    );
  }

  @override
  Future<void> start() async {
    startCount++;
    update();
  }

  @override
  Future<void> pause() async =>
      state = state.copyWith(status: RecorderStatus.paused);

  @override
  Future<void> resume() async => update();
}

class _StartSound implements RecordingStartSound {
  int playCount = 0;
  bool closed = false;
  Completer<void>? closeGate;

  @override
  Future<void> play() async => playCount++;

  @override
  Future<void> close() async {
    await closeGate?.future;
    closed = true;
  }
}
