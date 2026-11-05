import 'dart:isolate';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:sherpa_onnx/sherpa_onnx.dart' as sherpa;

import '../../../core/asr/asr_common.dart';
import '../../../core/audio/wav.dart';
import '../../../core/speaker/overlap_planner.dart';
import '../../../core/speaker/sherpa_speaker.dart';
import '../../../core/speaker/speaker_matcher.dart';
import '../../people/data/person.dart';
import 'precise_labels.dart';

/// Longest recording the precise pass accepts. The whole waveform is held in
/// memory (twice, once more inside the native library), about 8 MB per
/// minute. ⚠ needs lab confirmation on a real mid-range phone.
const Duration kPreciseMaxDuration = Duration(minutes: 40);

/// Plain data for the isolate that runs the analysis.
class PreciseRequest {
  const PreciseRequest({
    required this.wavPath,
    required this.segmentationModelPath,
    required this.embeddingModelPath,
    required this.enrolled,
  });

  final String wavPath;
  final String segmentationModelPath;
  final String embeddingModelPath;
  final List<Map<String, Object?>> enrolled;
}

typedef PreciseRunner = Future<PreciseAnalysis> Function(PreciseRequest request);

/// Runs [analyzePrecise] in a separate isolate, so the screen stays smooth.
Future<PreciseAnalysis> runPreciseInIsolate(PreciseRequest request) =>
    Isolate.run(() => analyzePrecise(request));

/// Layer B: diarizes the whole recording (global clustering keeps labels
/// consistent for the entire meeting), then names each cluster by matching
/// its clean (non-overlapping) speech to the enrolled people.
Future<PreciseAnalysis> analyzePrecise(PreciseRequest request) async {
  sherpa.initBindings();
  final info = await readWavInfo(request.wavPath);
  if (info.duration > kPreciseMaxDuration) {
    throw const FormatException('recording_too_long');
  }
  final pieces = <Float32List>[];
  var total = 0;
  await for (final chunk in readChannelSamples(
    request.wavPath,
    info: info,
    channel: 0,
    targetSampleRate: kAsrSampleRate,
  )) {
    pieces.add(chunk.samples);
    total += chunk.samples.length;
  }
  final audio = Float32List(total);
  var at = 0;
  for (final piece in pieces) {
    audio.setRange(at, at + piece.length, piece);
    at += piece.length;
  }
  pieces.clear();

  final diarizer = SherpaDiarizer.tryCreate(
    segmentationModelPath: request.segmentationModelPath,
    embeddingModelPath: request.embeddingModelPath,
    numThreads: 2,
  );
  final embedder = SherpaVoiceEmbedder.tryCreate(
    request.embeddingModelPath,
    numThreads: 2,
  );
  if (diarizer == null || embedder == null) {
    diarizer?.free();
    embedder?.free();
    throw const FormatException('models_unavailable');
  }
  try {
    final turns = diarizer.diarize(audio);
    final matcher = SpeakerMatcher([
      for (final e in request.enrolled) EnrolledVoice.fromMap(e),
    ]);
    final identities = <int, SpeakerIdentity>{};
    final clusters = {for (final t in turns) t.speaker}.toList()..sort();
    // Name clusters in order of first appearance so "ناشناس N" reads naturally.
    clusters.sort(
      (a, b) => turns
          .firstWhere((t) => t.speaker == a)
          .startMs
          .compareTo(turns.firstWhere((t) => t.speaker == b).startMs),
    );
    for (final cluster in clusters) {
      final clean = _longestClean(audio, turns, cluster);
      final enough = clean.length >= kAsrSampleRate; // 1 s
      final sample = enough ? clean : _all(audio, turns, cluster);
      if (sample.length < kAsrSampleRate ~/ 2) continue;
      final embedding = embedder.embed(sample);
      if (embedding == null) continue;
      identities[cluster] = matcher.identify(embedding, reliable: enough);
    }
    return PreciseAnalysis(turns: turns, identities: identities);
  } finally {
    diarizer.free();
    embedder.free();
  }
}

const int _maxClusterSamples = 20 * kAsrSampleRate;

Float32List _longestClean(
  Float32List audio,
  List<SpeakerTurn> turns,
  int cluster,
) {
  final spans = cleanSpans(turns, cluster)
    ..sort((a, b) => (b.$2 - b.$1).compareTo(a.$2 - a.$1));
  return _gather(audio, spans);
}

Float32List _all(Float32List audio, List<SpeakerTurn> turns, int cluster) =>
    _gather(audio, [
      for (final t in turns)
        if (t.speaker == cluster) (t.startMs, t.endMs),
    ]);

Float32List _gather(Float32List audio, List<(int, int)> spans) {
  final out = <Float32List>[];
  var n = 0;
  for (final (from, to) in spans) {
    if (n >= _maxClusterSamples) break;
    final a = (from * kAsrSampleRate ~/ 1000).clamp(0, audio.length);
    final b = math.min(
      (to * kAsrSampleRate ~/ 1000).clamp(0, audio.length),
      a + (_maxClusterSamples - n),
    );
    if (b <= a) continue;
    out.add(Float32List.sublistView(audio, a, b));
    n += b - a;
  }
  final joined = Float32List(n);
  var at = 0;
  for (final piece in out) {
    joined.setRange(at, at + piece.length, piece);
    at += piece.length;
  }
  return joined;
}
