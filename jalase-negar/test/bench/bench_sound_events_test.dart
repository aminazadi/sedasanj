import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/asr/asr_common.dart';
import 'package:jalase_negar/core/asr/sherpa_sound_tagger.dart';
import 'package:jalase_negar/core/asr/sound_events.dart';

import 'bench_support.dart';

/// Runs the real CED tagger and the detector over WAV clips (16 kHz mono
/// PCM16) and prints what it finds, window by window. Skipped unless
/// `BENCH_CED` (folder with `model.int8.onnx` and `class_labels_indices.csv`)
/// and `BENCH_SOUND_AUDIO` (folder of WAV clips) are set.
///
/// ```bash
/// BENCH_CED=~/.cache/jalase-bench/models/ced-tiny \
/// BENCH_SOUND_AUDIO=../sedasanj/test_data/asr_golden/audio \
/// flutter test test/bench/bench_sound_events_test.dart
/// ```
void main() {
  final env = Platform.environment;
  final ced = env['BENCH_CED'];
  final audio = env['BENCH_SOUND_AUDIO'];
  final skip = ced == null || audio == null
      ? 'Set BENCH_CED and BENCH_SOUND_AUDIO to run.'
      : null;

  test('real CED tagger on clips', () {
    initHostBindings();
    final home = env['HOME']!;
    final dir = ced!.replaceFirst('~', home);
    final tagger = SherpaSoundTagger.tryCreate(
      modelPath: '$dir/model.int8.onnx',
      labelsPath: '$dir/class_labels_indices.csv',
    );
    expect(tagger, isNotNull, reason: 'model or labels failed to load');

    // Window lengths the detector might use must not make the model fail.
    for (final seconds in [1, 2, 3, 5, 10]) {
      final noise = Float32List(seconds * kAsrSampleRate);
      for (var i = 0; i < noise.length; i++) {
        noise[i] = 0.02 * ((i * 7919) % 200 - 100) / 100;
      }
      final scores = tagger!.tag(noise);
      stdout.writeln(
        'window ${seconds}s ok, top: ${scores.take(3).map((s) => '${s.name} ${s.probability.toStringAsFixed(2)}').join(', ')}',
      );
      expect(scores, isNotEmpty);
    }

    final files =
        Directory(audio!.replaceFirst('~', home))
            .listSync()
            .whereType<File>()
            .where((f) => f.path.endsWith('.wav'))
            .toList()
          ..sort((a, b) => a.path.compareTo(b.path));
    for (final file in files) {
      final pcm = readPcm16Mono(file.path);
      final view = ByteData.sublistView(pcm);
      final samples = Float32List(pcm.length ~/ 2);
      for (var i = 0; i < samples.length; i++) {
        samples[i] = view.getInt16(i * 2, Endian.little) / 32768.0;
      }
      final detector = SoundEventDetector(tagger: tagger!);
      final events = <DetectedSoundEvent>[];
      final watch = Stopwatch()..start();
      const chunk = 3200;
      for (var i = 0; i < samples.length; i += chunk) {
        events.addAll(
          detector.accept(
            Float32List.sublistView(
              samples,
              i,
              i + chunk > samples.length ? samples.length : i + chunk,
            ),
          ),
        );
      }
      events.addAll(detector.flush());
      final seconds = samples.length / kAsrSampleRate;
      stdout.writeln(
        '${file.uri.pathSegments.last}: ${seconds.toStringAsFixed(0)} s audio, '
        'detector ${watch.elapsedMilliseconds} ms '
        '(${(watch.elapsedMilliseconds / 1000 / seconds).toStringAsFixed(3)} x real time), '
        '${events.length} events',
      );
      for (final e in events) {
        stdout.writeln(
          '  ${formatClock(e.startMs)}-${formatClock(e.endMs)} ${e.text} ${e.score.toStringAsFixed(2)}',
        );
      }
    }
    tagger!.free();
  }, skip: skip);
}
