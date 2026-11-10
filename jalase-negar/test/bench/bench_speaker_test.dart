import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/asr/asr_common.dart';
import 'package:jalase_negar/core/speaker/overlap_planner.dart';
import 'package:jalase_negar/core/speaker/sherpa_speaker.dart';
import 'package:jalase_negar/core/speaker/speaker_math.dart';
import 'package:jalase_negar/core/speaker/speaker_matcher.dart';
import 'package:jalase_negar/features/people/data/person.dart';

import 'bench_support.dart';

/// Offline benchmark of speaker diarization and naming on a labelled set of
/// meetings. It only runs when the environment names the models, the set and
/// an output folder, so the normal test run skips it.
///
/// ```bash
/// BENCH_MODELS=~/.cache/jalase-bench/models \
/// BENCH_SPEAKER_SET=../sedasanj/test_data/speaker_eval \
/// BENCH_OUT=../sedasanj/test_data/speaker_eval/hypotheses \
/// BENCH_VARIANT=app-baseline \
/// flutter test test/bench/bench_speaker_test.dart
/// ```
///
/// The set folder holds `manifest.json` (format in
/// `sedasanj/scripts/speaker_eval.py`), 16 kHz mono PCM16 WAV files for the
/// meetings and for one enrolment clip per person.
///
/// Optional: `BENCH_PARAMS` (JSON, see [SpeakerBenchParams]), `BENCH_MEETINGS`
/// (comma-separated ids).
///
/// Writes `<BENCH_OUT>/<variant>.json`, the file `speaker_eval.py` scores.
///
/// This follows the precise pass of the app (`analyzePrecise` in
/// `lib/features/meetings/data/precise_processor.dart`): diarize the whole
/// recording, then name every voice cluster from its longest clean speech. If
/// that function changes, change [_nameClusters] with it. The live path (one
/// utterance at a time) is not covered. Times are relative costs on the host
/// machine, not phone speeds.
class SpeakerBenchParams {
  const SpeakerBenchParams({
    this.clusterThreshold = kDiarizationClusterThreshold,
    this.thresholds = const MatchThresholds(),
    this.threads = 2,
    this.segmentation,
    this.embedding,
    this.maxClusterSeconds = 20,
    this.minCleanMs = 1000,
    this.minAnyMs = 500,
  });

  factory SpeakerBenchParams.fromJson(Map<String, Object?> json) {
    double number(String key, double fallback) =>
        (json[key] as num?)?.toDouble() ?? fallback;
    const d = MatchThresholds();
    return SpeakerBenchParams(
      clusterThreshold: number(
        'cluster_threshold',
        kDiarizationClusterThreshold,
      ),
      thresholds: MatchThresholds(
        accept: number('accept', d.accept),
        margin: number('margin', d.margin),
        unknownJoin: number('unknown_join', d.unknownJoin),
        lowConfidenceCap:
            (json['low_confidence_cap'] as num?)?.toInt() ?? d.lowConfidenceCap,
        attendeeBonus: number('attendee_bonus', d.attendeeBonus),
      ),
      threads: (json['threads'] as num?)?.toInt() ?? 2,
      segmentation: json['segmentation'] as String?,
      embedding: json['embedding'] as String?,
      maxClusterSeconds: (json['max_cluster_s'] as num?)?.toInt() ?? 20,
      minCleanMs: (json['min_clean_ms'] as num?)?.toInt() ?? 1000,
      minAnyMs: (json['min_any_ms'] as num?)?.toInt() ?? 500,
    );
  }

  final double clusterThreshold;
  final MatchThresholds thresholds;
  final int threads;

  /// Model files relative to `BENCH_MODELS`; the app's own pair by default.
  final String? segmentation;
  final String? embedding;
  final int maxClusterSeconds;
  final int minCleanMs;
  final int minAnyMs;

  Map<String, Object?> toJson() => {
    'cluster_threshold': clusterThreshold,
    'accept': thresholds.accept,
    'margin': thresholds.margin,
    'unknown_join': thresholds.unknownJoin,
    'low_confidence_cap': thresholds.lowConfidenceCap,
    'attendee_bonus': thresholds.attendeeBonus,
    'threads': threads,
    'segmentation': segmentation ?? 'speaker/segmentation.int8.onnx',
    'embedding': embedding ?? 'speaker/speaker_embedding.onnx',
    'max_cluster_s': maxClusterSeconds,
    'min_clean_ms': minCleanMs,
    'min_any_ms': minAnyMs,
  };
}

Float32List _toFloat(Uint8List pcm16) {
  final data = ByteData.sublistView(pcm16);
  final out = Float32List(pcm16.length ~/ 2);
  for (var i = 0; i < out.length; i++) {
    out[i] = data.getInt16(i * 2, Endian.little) / 32768.0;
  }
  return out;
}

Float32List _gather(Float32List audio, List<(int, int)> spans, int maxSamples) {
  final pieces = <Float32List>[];
  var n = 0;
  for (final (from, to) in spans) {
    if (n >= maxSamples) break;
    final a = (from * kAsrSampleRate ~/ 1000).clamp(0, audio.length);
    final b = math.min(
      (to * kAsrSampleRate ~/ 1000).clamp(0, audio.length),
      a + (maxSamples - n),
    );
    if (b <= a) continue;
    pieces.add(Float32List.sublistView(audio, a, b));
    n += b - a;
  }
  final joined = Float32List(n);
  var at = 0;
  for (final piece in pieces) {
    joined.setRange(at, at + piece.length, piece);
    at += piece.length;
  }
  return joined;
}

class _ClusterReport {
  const _ClusterReport({
    required this.cluster,
    required this.cleanMs,
    required this.reliable,
    required this.identity,
    required this.scores,
  });

  final int cluster;
  final int cleanMs;
  final bool reliable;
  final SpeakerIdentity? identity;

  /// Cosine to every enrolled person, so a threshold can be judged without
  /// running the diarizer again.
  final Map<String, double> scores;

  Map<String, Object?> toJson() => {
    'cluster': cluster,
    'clean_ms': cleanMs,
    'reliable': reliable,
    'name': identity?.name,
    'person': identity?.personId,
    'confidence': identity?.confidence,
    'scores': scores,
  };
}

/// Names clusters the way `analyzePrecise` does (first appearance order, clean
/// speech first, all turns as the fallback).
List<_ClusterReport> _nameClusters({
  required Float32List audio,
  required List<SpeakerTurn> turns,
  required SherpaVoiceEmbedder embedder,
  required SpeakerMatcher matcher,
  required List<EnrolledVoice> enrolled,
  required SpeakerBenchParams params,
  required Stopwatch embedWatch,
}) {
  final maxSamples = params.maxClusterSeconds * kAsrSampleRate;
  final clusters = {for (final t in turns) t.speaker}.toList()
    ..sort(
      (a, b) => turns
          .firstWhere((t) => t.speaker == a)
          .startMs
          .compareTo(turns.firstWhere((t) => t.speaker == b).startMs),
    );
  final reports = <_ClusterReport>[];
  for (final cluster in clusters) {
    final spans = cleanSpans(turns, cluster)
      ..sort((a, b) => (b.$2 - b.$1).compareTo(a.$2 - a.$1));
    final clean = _gather(audio, spans, maxSamples);
    final cleanMs = clean.length * 1000 ~/ kAsrSampleRate;
    final enough = cleanMs >= params.minCleanMs;
    final sample = enough
        ? clean
        : _gather(audio, [
            for (final t in turns)
              if (t.speaker == cluster) (t.startMs, t.endMs),
          ], maxSamples);
    if (sample.length * 1000 ~/ kAsrSampleRate < params.minAnyMs) {
      reports.add(
        _ClusterReport(
          cluster: cluster,
          cleanMs: cleanMs,
          reliable: false,
          identity: null,
          scores: const {},
        ),
      );
      continue;
    }
    embedWatch.start();
    final embedding = embedder.embed(sample);
    embedWatch.stop();
    if (embedding == null) {
      reports.add(
        _ClusterReport(
          cluster: cluster,
          cleanMs: cleanMs,
          reliable: enough,
          identity: null,
          scores: const {},
        ),
      );
      continue;
    }
    reports.add(
      _ClusterReport(
        cluster: cluster,
        cleanMs: cleanMs,
        reliable: enough,
        identity: matcher.identify(embedding, reliable: enough),
        scores: {
          for (final voice in enrolled)
            voice.name: cosine(embedding, voice.centroid),
        },
      ),
    );
  }
  return reports;
}

void main() {
  final env = Platform.environment;
  final modelsDir = env['BENCH_MODELS'];
  final setDir = env['BENCH_SPEAKER_SET'];
  final outDir = env['BENCH_OUT'];
  final skip = modelsDir == null || setDir == null || outDir == null
      ? 'Set BENCH_MODELS, BENCH_SPEAKER_SET and BENCH_OUT to run the benchmark.'
      : null;

  test(
    'speaker diarization and naming benchmark',
    () {
      final home = env['HOME']!;
      final modelsRoot = modelsDir!.replaceFirst('~', home);
      final models = BenchModels(modelsRoot);
      final params = SpeakerBenchParams.fromJson(
        jsonDecode(env['BENCH_PARAMS'] ?? '{}') as Map<String, Object?>,
      );
      final segmentation = params.segmentation == null
          ? models.segmentation
          : '$modelsRoot/${params.segmentation}';
      final embedding = params.embedding == null
          ? models.embedding
          : '$modelsRoot/${params.embedding}';
      for (final path in [segmentation, embedding]) {
        if (!File(path).existsSync()) {
          throw StateError('Speaker model missing: $path');
        }
      }
      initHostBindings();

      final variant = env['BENCH_VARIANT'] ?? 'app-baseline';
      final only = env['BENCH_MEETINGS']?.split(',').toSet();
      final root = Directory(setDir!.replaceFirst('~', home));
      final manifest =
          jsonDecode(File('${root.path}/manifest.json').readAsStringSync())
              as Map<String, Object?>;

      final embedder = SherpaVoiceEmbedder.tryCreate(
        embedding,
        numThreads: params.threads,
      );
      final diarizer = SherpaDiarizer.tryCreate(
        segmentationModelPath: segmentation,
        embeddingModelPath: embedding,
        numThreads: params.threads,
        clusterThreshold: params.clusterThreshold,
      );
      if (embedder == null || diarizer == null) {
        throw StateError('The speaker models could not be loaded.');
      }

      final result = <String, Object?>{};
      try {
        // One voiceprint per enrolled person, from the enrolment clip.
        final enrolledClips =
            (manifest['enrolled'] as Map<String, Object?>?) ?? const {};
        final enrolled = <EnrolledVoice>[];
        final enrolWatch = Stopwatch();
        for (final entry in enrolledClips.entries) {
          final audio = _toFloat(readPcm16Mono('${root.path}/${entry.value}'));
          final capped = audio.length > 30 * kAsrSampleRate
              ? Float32List.sublistView(audio, 0, 30 * kAsrSampleRate)
              : audio;
          enrolWatch.start();
          final vector = embedder.embed(capped);
          enrolWatch.stop();
          if (vector == null) {
            throw StateError('Could not embed enrolment clip of ${entry.key}.');
          }
          enrolled.add(
            EnrolledVoice(
              personId: entry.key,
              name: entry.key,
              centroid: centroid([vector]),
              samples: 1,
            ),
          );
        }

        for (final raw in (manifest['meetings']! as List<Object?>)) {
          final meeting = raw! as Map<String, Object?>;
          final id = meeting['id']! as String;
          if (only != null && !only.contains(id)) continue;
          final attendees = {
            ...((meeting['attendees'] as List<Object?>?) ?? const [])
                .cast<String>(),
          };
          final audio = _toFloat(
            readPcm16Mono('${root.path}/${meeting['audio']}'),
          );
          final diarizeWatch = Stopwatch()..start();
          final turns = diarizer.diarize(audio);
          diarizeWatch.stop();

          final matcher = SpeakerMatcher([
            for (final voice in enrolled)
              attendees.isEmpty
                  ? voice
                  : voice.asPreferred(attendees.contains(voice.name)),
          ], thresholds: params.thresholds);
          final embedWatch = Stopwatch();
          final reports = _nameClusters(
            audio: audio,
            turns: turns,
            embedder: embedder,
            matcher: matcher,
            enrolled: enrolled,
            params: params,
            embedWatch: embedWatch,
          );
          final byCluster = {for (final r in reports) r.cluster: r};
          final audioSeconds = audio.length / kAsrSampleRate;
          result[id] = {
            'segments': [
              for (final t in turns)
                {
                  'start': t.startMs / 1000,
                  'end': t.endMs / 1000,
                  'speaker':
                      byCluster[t.speaker]?.identity?.name ??
                      'cluster ${t.speaker}',
                  'person': byCluster[t.speaker]?.identity?.personId,
                },
            ],
            'clusters': [for (final r in reports) r.toJson()],
            'timing': {
              'audio_s': audioSeconds,
              'diarize_s': diarizeWatch.elapsedMicroseconds / 1e6,
              'embed_s': embedWatch.elapsedMicroseconds / 1e6,
              'diarize_rtf':
                  diarizeWatch.elapsedMicroseconds / 1e6 / audioSeconds,
              'clusters': reports.length,
            },
          };
          // ignore: avoid_print
          print(
            '$variant $id: ${turns.length} turns, ${reports.length} voices, '
            'diarize ${(diarizeWatch.elapsedMicroseconds / 1e6).toStringAsFixed(2)} s '
            'for ${audioSeconds.toStringAsFixed(1)} s audio',
          );
        }
        // ignore: avoid_print
        print(
          'enrolment embeddings: ${enrolled.length} in '
          '${(enrolWatch.elapsedMicroseconds / 1e6).toStringAsFixed(2)} s',
        );
      } finally {
        embedder.free();
        diarizer.free();
      }

      Directory(outDir!).createSync(recursive: true);
      final target = File('$outDir/$variant.json');
      final temp = File('${target.path}.tmp');
      temp.writeAsStringSync(
        const JsonEncoder.withIndent('  ').convert({
          'variant': variant,
          'params': params.toJson(),
          'meetings': result,
        }),
      );
      temp.renameSync(target.path);
      expect(result, isNotEmpty, reason: 'No meeting was run.');
    },
    skip: skip,
    timeout: Timeout.none,
  );
}
