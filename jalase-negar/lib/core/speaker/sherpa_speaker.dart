import 'dart:io';
import 'dart:typed_data';

import 'package:sherpa_onnx/sherpa_onnx.dart' as sherpa;

import '../asr/asr_common.dart';
import 'overlap_planner.dart';
import 'speaker_labeler.dart';

/// Cosine-distance threshold of the diarizer's own clustering inside one
/// utterance. ⚠ needs lab confirmation (library default).
const double kDiarizationClusterThreshold = 0.5;

/// Speaker embedding with sherpa-onnx (3D-Speaker / WeSpeaker ONNX models).
/// Owns native handles: create and use it in one isolate, then [free] it.
class SherpaVoiceEmbedder implements VoiceEmbedder {
  SherpaVoiceEmbedder._(this._extractor);

  final sherpa.SpeakerEmbeddingExtractor _extractor;

  /// Output size of the model.
  int get dim => _extractor.dim;

  /// Null when [modelPath] is not a loadable model.
  static SherpaVoiceEmbedder? tryCreate(
    String modelPath, {
    int numThreads = 1,
  }) {
    if (modelPath.isEmpty || !File(modelPath).existsSync()) return null;
    try {
      return SherpaVoiceEmbedder._(
        sherpa.SpeakerEmbeddingExtractor(
          config: sherpa.SpeakerEmbeddingExtractorConfig(
            model: modelPath,
            numThreads: numThreads,
            debug: false,
          ),
        ),
      );
    } catch (_) {
      return null;
    }
  }

  @override
  Float32List? embed(Float32List samples) {
    if (samples.isEmpty) return null;
    final stream = _extractor.createStream();
    try {
      stream.acceptWaveform(samples: samples, sampleRate: kAsrSampleRate);
      stream.inputFinished();
      if (!_extractor.isReady(stream)) return null;
      final embedding = _extractor.compute(stream);
      return embedding.isEmpty ? null : embedding;
    } finally {
      stream.free();
    }
  }

  void free() => _extractor.free();
}

/// pyannote segmentation 3.0 plus the embedding model, as sherpa-onnx's
/// offline diarizer. Returns speaker turns, which may overlap in time (the
/// model reports at most two people talking at once).
class SherpaDiarizer implements UtteranceDiarizer {
  SherpaDiarizer._(this._diarization);

  final sherpa.OfflineSpeakerDiarization _diarization;

  static SherpaDiarizer? tryCreate({
    required String segmentationModelPath,
    required String embeddingModelPath,
    int numThreads = 1,
    double clusterThreshold = kDiarizationClusterThreshold,
  }) {
    if (!File(segmentationModelPath).existsSync() ||
        !File(embeddingModelPath).existsSync()) {
      return null;
    }
    try {
      return SherpaDiarizer._(
        sherpa.OfflineSpeakerDiarization(
          sherpa.OfflineSpeakerDiarizationConfig(
            segmentation: sherpa.OfflineSpeakerSegmentationModelConfig(
              pyannote: sherpa.OfflineSpeakerSegmentationPyannoteModelConfig(
                model: segmentationModelPath,
              ),
              numThreads: numThreads,
              debug: false,
            ),
            embedding: sherpa.SpeakerEmbeddingExtractorConfig(
              model: embeddingModelPath,
              numThreads: numThreads,
              debug: false,
            ),
            clustering: sherpa.FastClusteringConfig(
              numClusters: -1,
              threshold: clusterThreshold,
            ),
            minDurationOn: 0.2,
            minDurationOff: 0.5,
          ),
        ),
      );
    } catch (_) {
      return null;
    }
  }

  @override
  List<SpeakerTurn> diarize(Float32List samples) =>
      turnsOf(_diarization.process(samples: samples));

  /// Same as [diarize] with progress, for a whole recording.
  List<SpeakerTurn> diarizeWithProgress(
    Float32List samples,
    void Function(int done, int total) onProgress,
  ) => turnsOf(
    _diarization.processWithCallback(
      samples: samples,
      callback: (done, total) {
        onProgress(done, total);
        return 0;
      },
    ),
  );

  static List<SpeakerTurn> turnsOf(
    List<sherpa.OfflineSpeakerDiarizationSegment> segments,
  ) => [
    for (final s in segments)
      SpeakerTurn(
        startMs: (s.start * 1000).round(),
        endMs: (s.end * 1000).round(),
        speaker: s.speaker,
      ),
  ];

  void free() => _diarization.free();
}
