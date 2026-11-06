import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:jalase_negar/core/asr/asr_common.dart';
import 'package:jalase_negar/core/asr/live_asr_engine.dart';
import 'package:jalase_negar/core/asr/live_pipeline.dart';
import 'package:jalase_negar/core/asr/recognizer_factory.dart';
import 'package:jalase_negar/core/asr/sherpa_live_adapters.dart';
import 'package:jalase_negar/core/asr/vad_segment_engine.dart';
import 'package:jalase_negar/core/models/model_spec.dart';
import 'package:jalase_negar/core/speaker/overlap_planner.dart';
import 'package:jalase_negar/core/speaker/sherpa_speaker.dart';
import 'package:jalase_negar/core/speaker/speaker_labeler.dart';
import 'package:jalase_negar/core/speaker/speaker_matcher.dart';
import 'package:jalase_negar/features/people/data/person.dart';
import 'package:sherpa_onnx/sherpa_onnx.dart' as sherpa;

/// Offline benchmark for the live pipeline: the same [LivePipeline], Silero
/// VAD and recognizer wiring the app uses, fed the way the app feeds it
/// (200 ms PCM16 batches), with the time of every stage recorded.
///
/// Numbers from this run are relative costs on the host machine. They say
/// nothing about the speed of a phone.

/// Tunable values of one benchmark run. Defaults are the app's current ones.
class BenchParams {
  const BenchParams({
    this.threshold = kSileroThreshold,
    this.minSilence = kSileroMinSilenceSeconds,
    this.minSpeech = kSileroMinSpeechSeconds,
    this.maxSpeech = kAsrWindowSeconds,
    this.threads = 2,
    this.labeler = false,
    this.speakerThreads = 1,
  });

  factory BenchParams.fromJson(Map<String, Object?> json) {
    double number(String key, double fallback) =>
        (json[key] as num?)?.toDouble() ?? fallback;
    return BenchParams(
      threshold: number('threshold', kSileroThreshold),
      minSilence: number('min_silence', kSileroMinSilenceSeconds),
      minSpeech: number('min_speech', kSileroMinSpeechSeconds),
      maxSpeech: number('max_speech', kAsrWindowSeconds),
      threads: (json['threads'] as num?)?.toInt() ?? 2,
      labeler: json['labeler'] == true,
      speakerThreads: (json['speaker_threads'] as num?)?.toInt() ?? 1,
    );
  }

  final double threshold;
  final double minSilence;
  final double minSpeech;
  final double maxSpeech;
  final int threads;

  /// Run speaker identification too (as the app does when people are enrolled).
  final bool labeler;
  final int speakerThreads;

  Map<String, Object?> toJson() => {
    'threshold': threshold,
    'min_silence': minSilence,
    'min_speech': minSpeech,
    'max_speech': maxSpeech,
    'threads': threads,
    'labeler': labeler,
    'speaker_threads': speakerThreads,
  };
}

/// Where the models are: the layout of `~/.cache/jalase-bench/models`.
class BenchModels {
  const BenchModels(this.root);

  final String root;

  String get tokens => '$root/koochik/tokens.txt';
  String get encoder => '$root/koochik/encoder.int8.onnx';
  String get decoder => '$root/koochik/decoder.int8.onnx';
  String get joiner => '$root/koochik/joiner.int8.onnx';
  String get vad => '$root/silero/silero_vad.onnx';
  String get denoiser => '$root/gtcrn/gtcrn_simple.onnx';
  String get segmentation => '$root/speaker/segmentation.int8.onnx';
  String get embedding => '$root/speaker/speaker_embedding.onnx';

  void requireCore() {
    for (final path in [tokens, encoder, decoder, joiner, vad]) {
      if (!File(path).existsSync()) {
        throw StateError('Benchmark model missing: $path');
      }
    }
  }
}

/// Loads the sherpa-onnx native library on the host. Flutter's own loader
/// (`DynamicLibrary.process`) only works inside an app, so the path of the
/// macOS package is read from the resolved package config.
void initHostBindings() {
  final config =
      jsonDecode(File('.dart_tool/package_config.json').readAsStringSync())
          as Map<String, Object?>;
  for (final package in config['packages']! as List<Object?>) {
    final entry = package! as Map<String, Object?>;
    if (entry['name'] == 'sherpa_onnx_macos') {
      final root = Uri.parse(entry['rootUri']! as String).toFilePath();
      sherpa.initBindings('${root.replaceAll(RegExp(r'/$'), '')}/macos');
      return;
    }
  }
  throw StateError('sherpa_onnx_macos is not in the package config.');
}

/// PCM16 mono samples of a WAV file, as raw little-endian bytes.
Uint8List readPcm16Mono(String path) {
  final bytes = File(path).readAsBytesSync();
  final data = ByteData.sublistView(bytes);
  if (bytes.length < 12 ||
      String.fromCharCodes(bytes.sublist(0, 4)) != 'RIFF') {
    throw FormatException('Not a WAV file: $path');
  }
  var offset = 12;
  int? channels;
  int? rate;
  int? bits;
  while (offset + 8 <= bytes.length) {
    final id = String.fromCharCodes(bytes.sublist(offset, offset + 4));
    final size = data.getUint32(offset + 4, Endian.little);
    final body = offset + 8;
    if (id == 'fmt ') {
      channels = data.getUint16(body + 2, Endian.little);
      rate = data.getUint32(body + 4, Endian.little);
      bits = data.getUint16(body + 14, Endian.little);
    } else if (id == 'data') {
      if (channels != 1 || rate != kAsrSampleRate || bits != 16) {
        throw FormatException(
          'Expected 16 kHz mono PCM16, got $channels ch / $rate Hz / $bits bit: $path',
        );
      }
      return Uint8List.sublistView(
        bytes,
        body,
        math.min(body + size, bytes.length),
      );
    }
    offset = body + size + (size.isOdd ? 1 : 0);
  }
  throw FormatException('No data chunk in $path');
}

class DecodeCall {
  const DecodeCall(this.audioMs, this.micros);

  final int audioMs;
  final int micros;
}

/// Wraps a decoder and records how long each call took.
class TimedDecoder implements LiveDecoder {
  TimedDecoder(this._inner);

  final LiveDecoder _inner;
  final List<DecodeCall> calls = [];

  @override
  String decode(Float32List samples) {
    final watch = Stopwatch()..start();
    final text = _inner.decode(samples);
    watch.stop();
    calls.add(
      DecodeCall(
        samples.length * 1000 ~/ kAsrSampleRate,
        watch.elapsedMicroseconds,
      ),
    );
    return text;
  }
}

/// Records how long each segmentation call took.
class TimedDiarizer implements UtteranceDiarizer {
  TimedDiarizer(this._inner);

  final UtteranceDiarizer _inner;
  int micros = 0;

  @override
  List<SpeakerTurn> diarize(Float32List samples) {
    final watch = Stopwatch()..start();
    try {
      return _inner.diarize(samples);
    } finally {
      micros += watch.elapsedMicroseconds;
    }
  }
}

/// Records how long each embedding call took.
class TimedEmbedder implements VoiceEmbedder {
  TimedEmbedder(this._inner);

  final VoiceEmbedder _inner;
  int micros = 0;

  @override
  Float32List? embed(Float32List samples) {
    final watch = Stopwatch()..start();
    try {
      return _inner.embed(samples);
    } finally {
      micros += watch.elapsedMicroseconds;
    }
  }
}

/// Wraps a labeler and records how long each call took, in total and split
/// into segmentation and embedding.
class BenchLabeler implements UtteranceLabeler {
  BenchLabeler(this._inner, this.diarizer, this.embedder);

  final UtteranceLabeler _inner;
  final TimedDiarizer diarizer;
  final TimedEmbedder embedder;
  final List<int> micros = [];

  @override
  List<LabeledPart> label(Float32List speech, {required int startMs}) {
    final watch = Stopwatch()..start();
    try {
      return _inner.label(speech, startMs: startMs);
    } finally {
      watch.stop();
      micros.add(watch.elapsedMicroseconds);
    }
  }
}

/// The native speaker models, created once per benchmark run.
class BenchSpeakerModels {
  BenchSpeakerModels._(this.embedder, this.diarizer);

  final SherpaVoiceEmbedder embedder;
  final SherpaDiarizer diarizer;

  factory BenchSpeakerModels.load(BenchModels models, {int threads = 1}) {
    final embedder = SherpaVoiceEmbedder.tryCreate(
      models.embedding,
      numThreads: threads,
    );
    final diarizer = SherpaDiarizer.tryCreate(
      segmentationModelPath: models.segmentation,
      embeddingModelPath: models.embedding,
      numThreads: threads,
    );
    if (embedder == null || diarizer == null) {
      throw StateError('Speaker models missing under ${models.root}/speaker');
    }
    return BenchSpeakerModels._(embedder, diarizer);
  }

  /// A fresh labeler (own "previous speaker" and unknown-voice state) with one
  /// enrolled person, so identification does its normal work. Segmentation and
  /// embedding calls are timed separately.
  BenchLabeler labeler() {
    final centroid = Float32List(embedder.dim);
    for (var i = 0; i < centroid.length; i++) {
      centroid[i] = math.sin(i * 0.37);
    }
    final timedDiarizer = TimedDiarizer(diarizer);
    final timedEmbedder = TimedEmbedder(embedder);
    return BenchLabeler(
      SpeakerLabeler(
        diarizer: timedDiarizer,
        embedder: timedEmbedder,
        matcher: SpeakerMatcher([
          EnrolledVoice(
            personId: 'bench',
            name: 'bench',
            centroid: centroid,
            samples: 3,
          ),
        ]),
      ),
      timedDiarizer,
      timedEmbedder,
    );
  }

  void free() {
    embedder.free();
    diarizer.free();
  }
}

class BenchUtterance {
  const BenchUtterance({
    required this.startMs,
    required this.endMs,
    required this.emitMs,
    required this.decodeMs,
    required this.text,
    this.speaker,
    this.speakerConfidence,
    this.overlap = false,
  });

  final int startMs;
  final int endMs;

  /// Position on the audio timeline when the pipeline handed the text out.
  final int emitMs;

  /// Recognizer plus speaker-labelling time spent in the pipeline call that
  /// produced this text (shared when one call produced several utterances).
  final double decodeMs;
  final String text;

  /// Who the pipeline named (null without a labeler); kept so two runs can be
  /// checked for identical labels.
  final String? speaker;
  final int? speakerConfidence;
  final bool overlap;

  /// Audio time the text waited after the speaker stopped (the VAD's silence
  /// window plus batch granularity); decode time comes on top.
  int get waitMs => emitMs - endMs;

  /// How long each word had been waiting when the text appeared: the audio
  /// time since it was spoken plus the decode time. Words are assumed evenly
  /// spread over the utterance.
  List<double> get wordAgesMs {
    final words = text.split(RegExp(r'\s+')).where((w) => w.isNotEmpty).length;
    if (words == 0) return const [];
    final length = endMs - startMs;
    return [
      for (var i = 0; i < words; i++)
        emitMs + decodeMs - (startMs + (i + 0.5) * length / words),
    ];
  }
}

class ClipResult {
  const ClipResult({
    required this.clipId,
    required this.audioSeconds,
    required this.wallSeconds,
    required this.decodeSeconds,
    required this.labelSeconds,
    required this.diarizeSeconds,
    required this.embedSeconds,
    required this.utterances,
    required this.decodes,
  });

  final String clipId;
  final double audioSeconds;
  final double wallSeconds;
  final double decodeSeconds;
  final double labelSeconds;

  /// Parts of [labelSeconds] spent in segmentation and in embedding.
  final double diarizeSeconds;
  final double embedSeconds;
  final List<BenchUtterance> utterances;
  final List<DecodeCall> decodes;

  double get rtf => wallSeconds / audioSeconds;

  /// Time spent outside the recognizer: VAD, context cutting, bookkeeping.
  double get otherSeconds => wallSeconds - decodeSeconds - labelSeconds;

  String get text => utterances.map((u) => u.text).join(' ');

  /// Delay between speaking a word and seeing it, over every word.
  List<double> get wordAgesMs =>
      [for (final u in utterances) ...u.wordAgesMs]..sort();

  double get meanAgeMs {
    final ages = wordAgesMs;
    return ages.isEmpty ? 0 : ages.reduce((a, b) => a + b) / ages.length;
  }

  double ageQuantileMs(double q) {
    final ages = wordAgesMs;
    return ages.isEmpty ? 0 : ages[((ages.length - 1) * q).round()];
  }

  Map<String, Object?> toJson() => {
    'clip': clipId,
    'audio_s': audioSeconds,
    'wall_s': wallSeconds,
    'rtf': rtf,
    'decode_s': decodeSeconds,
    'label_s': labelSeconds,
    'label_diarize_s': diarizeSeconds,
    'label_embed_s': embedSeconds,
    'other_s': otherSeconds,
    'utterance_count': utterances.length,
    'word_count': wordAgesMs.length,
    'age_mean_ms': meanAgeMs,
    'age_p95_ms': ageQuantileMs(0.95),
    'age_max_ms': ageQuantileMs(1),
    'decodes': [
      for (final c in decodes) {'audio_ms': c.audioMs, 'us': c.micros},
    ],
    'utterances': [
      for (final u in utterances)
        {
          'start_ms': u.startMs,
          'end_ms': u.endMs,
          'emit_ms': u.emitMs,
          'wait_ms': u.waitMs,
          'decode_ms': u.decodeMs,
          'text': u.text,
          'speaker': u.speaker,
          'speaker_confidence': u.speakerConfidence,
          'overlap': u.overlap,
        },
    ],
  };
}

/// Runs one clip through a fresh pipeline built from [params].
ClipResult runClip({
  required String clipId,
  required Uint8List pcm,
  required BenchModels models,
  required BenchParams params,
  required sherpa.OfflineRecognizer recognizer,
  BenchLabeler? labeler,
}) {
  final decoder = TimedDecoder(SherpaLiveDecoder(recognizer));
  final timedLabeler = labeler;
  final pipeline = LivePipeline(
    vadFactory: () => SherpaLiveVad(
      modelPath: models.vad,
      threshold: params.threshold,
      minSilenceSeconds: params.minSilence,
      minSpeechSeconds: params.minSpeech,
      windowSize: kSileroWindowSize,
      maxSpeechSeconds: params.maxSpeech,
    ),
    decoder: decoder,
    labeler: timedLabeler,
  );
  final utterances = <BenchUtterance>[];
  var callsSeen = 0;
  var labelsSeen = 0;
  void collect(List<LiveEvent> events) {
    final emitMs = pipeline.fedSamples * 1000 ~/ kAsrSampleRate;
    final fresh = decoder.calls.sublist(callsSeen);
    callsSeen = decoder.calls.length;
    final freshLabels =
        timedLabeler?.micros.sublist(labelsSeen) ?? const <int>[];
    labelsSeen = timedLabeler?.micros.length ?? 0;
    final spentMs =
        (fresh.fold<int>(0, (sum, c) => sum + c.micros) +
            freshLabels.fold<int>(0, (sum, m) => sum + m)) /
        1000;
    final made = events.whereType<LiveUtterance>().toList();
    for (final event in made) {
      utterances.add(
        BenchUtterance(
          startMs: event.startMs,
          endMs: event.endMs,
          emitMs: emitMs,
          decodeMs: spentMs / made.length,
          text: event.text,
          speaker: event.speaker?.name,
          speakerConfidence: event.speakerConfidence,
          overlap: event.overlap,
        ),
      );
    }
  }

  const batchBytes = 6400; // 200 ms, as the app's engine batches.
  final watch = Stopwatch()..start();
  for (var at = 0; at < pcm.length; at += batchBytes) {
    final end = math.min(pcm.length, at + batchBytes);
    collect(pipeline.feed(Uint8List.sublistView(pcm, at, end)));
  }
  collect(pipeline.finish());
  watch.stop();
  pipeline.dispose();

  return ClipResult(
    clipId: clipId,
    audioSeconds: pcm.length / 2 / kAsrSampleRate,
    wallSeconds: watch.elapsedMicroseconds / 1e6,
    decodeSeconds: decoder.calls.fold<int>(0, (sum, c) => sum + c.micros) / 1e6,
    labelSeconds:
        (timedLabeler?.micros.fold<int>(0, (sum, m) => sum + m) ?? 0) / 1e6,
    diarizeSeconds: (timedLabeler?.diarizer.micros ?? 0) / 1e6,
    embedSeconds: (timedLabeler?.embedder.micros ?? 0) / 1e6,
    utterances: utterances,
    decodes: decoder.calls,
  );
}

sherpa.OfflineRecognizer createBenchRecognizer(
  BenchModels models,
  int threads,
) => createOfflineRecognizer(
  architecture: AsrArchitecture.transducer,
  asrModelPath: '',
  tokensPath: models.tokens,
  encoderPath: models.encoder,
  decoderPath: models.decoder,
  joinerPath: models.joiner,
  numThreads: threads,
);

String formatClock(int ms) {
  final seconds = ms ~/ 1000;
  final m = (seconds ~/ 60).toString().padLeft(2, '0');
  final s = (seconds % 60).toString().padLeft(2, '0');
  return '$m:$s';
}
