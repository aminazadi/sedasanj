import 'dart:io';
import 'dart:typed_data';

import 'package:sherpa_onnx/sherpa_onnx.dart' as sherpa;

import 'asr_common.dart';
import 'sound_events.dart';

/// CED audio tagger (sherpa-onnx) behind the detector's [SoundTagger]
/// interface.
///
/// CED is a small AudioSet model (527 classes, Apache-2.0 weights from
/// Xiaomi's CED project, converted by sherpa-onnx). Each call classifies one
/// short clip; the detector slides it over the recording.
class SherpaSoundTagger implements SoundTagger {
  SherpaSoundTagger._(this._tagger, this._topK, this._minSamples);

  final sherpa.AudioTagging _tagger;
  final int _topK;
  final int _minSamples;

  /// Loads the model, or returns null when a file is missing or the native
  /// library rejects it. Never throws: sound events are an extra, and a
  /// recording must start without them rather than not at all.
  ///
  /// [topK] classes are reported per clip. The benchmark gave identical
  /// results for 12, 30 and 80; 30 leaves room for a quiet laugh hidden under
  /// «Speech», «Male speech» and similar classes.
  static SherpaSoundTagger? tryCreate({
    required String modelPath,
    required String labelsPath,
    int numThreads = 1,
    int topK = 30,
  }) {
    try {
      if (!File(modelPath).existsSync() || !File(labelsPath).existsSync()) {
        return null;
      }
      final tagger = sherpa.AudioTagging(
        config: sherpa.AudioTaggingConfig(
          model: sherpa.AudioTaggingModelConfig(
            ced: modelPath,
            numThreads: numThreads,
            debug: false,
          ),
          labels: labelsPath,
        ),
      );
      // A clip shorter than the model's smallest patch grid would make the
      // native library fail, so it is padded with silence up to one second.
      return SherpaSoundTagger._(tagger, topK, kAsrSampleRate);
    } catch (_) {
      return null;
    }
  }

  @override
  List<SoundScore> tag(Float32List samples) {
    var input = samples;
    if (input.length < _minSamples) {
      input = Float32List(_minSamples)..setRange(0, samples.length, samples);
    }
    final stream = _tagger.createStream();
    try {
      stream.acceptWaveform(samples: input, sampleRate: kAsrSampleRate);
      final events = _tagger.compute(stream: stream, topK: _topK);
      return [for (final e in events) SoundScore(e.name, e.prob)];
    } finally {
      stream.free();
    }
  }

  void free() => _tagger.free();
}
