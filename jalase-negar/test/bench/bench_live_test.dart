import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'bench_support.dart';

/// Offline benchmark of the live pipeline. It only runs when the environment
/// names the models and the clips, so the normal test run skips it.
///
/// ```bash
/// BENCH_MODELS=~/.cache/jalase-bench/models \
/// BENCH_AUDIO=../sedasanj/test_data/asr_golden/audio \
/// BENCH_OUT=../sedasanj/test_data/asr_golden/hypotheses \
/// BENCH_VARIANT=app-baseline \
/// flutter test test/bench/bench_live_test.dart
/// ```
///
/// Optional: `BENCH_PARAMS` (JSON, see [BenchParams]), `BENCH_CLIPS`
/// (comma-separated ids), `BENCH_REPEAT` (timing repeats, default 1).
///
/// Writes `<BENCH_OUT>/<variant>.json` (clip id -> text, the format
/// `asr_eval.py` reads), `<variant>.timing.json` and one readable
/// `draft-<clip>.txt` per clip when `BENCH_DRAFT=1`.
void main() {
  final env = Platform.environment;
  final modelsDir = env['BENCH_MODELS'];
  final audioDir = env['BENCH_AUDIO'];
  final outDir = env['BENCH_OUT'];
  final skip = modelsDir == null || audioDir == null || outDir == null
      ? 'Set BENCH_MODELS, BENCH_AUDIO and BENCH_OUT to run the benchmark.'
      : null;

  test(
    'live pipeline benchmark',
    () {
      final models = BenchModels(modelsDir!.replaceFirst('~', env['HOME']!));
      models.requireCore();
      initHostBindings();

      final variant = env['BENCH_VARIANT'] ?? 'app-baseline';
      final params = BenchParams.fromJson(
        jsonDecode(env['BENCH_PARAMS'] ?? '{}') as Map<String, Object?>,
      );
      final only = env['BENCH_CLIPS']?.split(',').toSet();
      final repeat = int.tryParse(env['BENCH_REPEAT'] ?? '') ?? 1;

      final clips =
          Directory(audioDir!)
              .listSync()
              .whereType<File>()
              .where((f) => f.path.endsWith('.wav'))
              .toList()
            ..sort((a, b) => a.path.compareTo(b.path));
      expect(clips, isNotEmpty, reason: 'No .wav files in $audioDir');

      final recognizer = createBenchRecognizer(models, params.threads);
      final speakers = params.labeler
          ? BenchSpeakerModels.load(models, threads: params.speakerThreads)
          : null;
      final hypotheses = <String, String>{};
      final timing = <Map<String, Object?>>[];
      try {
        for (final file in clips) {
          final id = file.uri.pathSegments.last.replaceAll('.wav', '');
          if (only != null && !only.contains(id)) continue;
          final pcm = readPcm16Mono(file.path);
          ClipResult? best;
          for (var run = 0; run < repeat; run++) {
            final result = runClip(
              clipId: id,
              pcm: pcm,
              models: models,
              params: params,
              recognizer: recognizer,
              labeler: speakers?.labeler(),
            );
            if (best == null || result.wallSeconds < best.wallSeconds) {
              best = result;
            }
          }
          final result = best!;
          hypotheses[id] = result.text;
          timing.add(result.toJson());
          // ignore: avoid_print
          print(
            '$variant $id: ${result.utterances.length} utterances, '
            'rtf ${result.rtf.toStringAsFixed(3)}, '
            'word age mean ${(result.meanAgeMs / 1000).toStringAsFixed(1)} s '
            'p95 ${(result.ageQuantileMs(0.95) / 1000).toStringAsFixed(1)} s '
            '(decode ${result.decodeSeconds.toStringAsFixed(2)} s, '
            'label ${result.labelSeconds.toStringAsFixed(2)} s '
            '[segment ${result.diarizeSeconds.toStringAsFixed(2)}, '
            'embed ${result.embedSeconds.toStringAsFixed(2)}], '
            'other ${result.otherSeconds.toStringAsFixed(2)} s of '
            '${result.audioSeconds.toStringAsFixed(1)} s audio)',
          );
          if (env['BENCH_DRAFT'] == '1') {
            Directory(outDir!).createSync(recursive: true);
            File('$outDir/draft-$id.txt').writeAsStringSync(
              '${result.utterances.map((u) => '[${formatClock(u.startMs)}] ${u.text}').join('\n')}\n',
            );
          }
        }
      } finally {
        recognizer.free();
        speakers?.free();
      }

      final encoder = const JsonEncoder.withIndent('  ');
      Directory(outDir!).createSync(recursive: true);
      File(
        '$outDir/$variant.json',
      ).writeAsStringSync(encoder.convert(hypotheses));
      File('$outDir/$variant.timing.json').writeAsStringSync(
        encoder.convert({
          'variant': variant,
          'params': params.toJson(),
          'clips': timing,
        }),
      );
    },
    skip: skip,
    timeout: Timeout.none,
  );
}
