import 'dart:typed_data';

import 'package:sherpa_onnx/sherpa_onnx.dart' as sherpa;

import 'asr_common.dart';
import 'live_pipeline.dart';

/// Silero VAD (sherpa-onnx) behind the pipeline's [LiveVad] interface.
///
/// Every threshold is a parameter so the live engine and the offline
/// benchmark build the detector the same way, and a benchmark can sweep the
/// values without touching the engine.
class SherpaLiveVad implements LiveVad {
  SherpaLiveVad({
    required String modelPath,
    required double threshold,
    required double minSilenceSeconds,
    required double minSpeechSeconds,
    required int windowSize,
    required double maxSpeechSeconds,
  }) : _vad = sherpa.VoiceActivityDetector(
         config: sherpa.VadModelConfig(
           sileroVad: sherpa.SileroVadModelConfig(
             model: modelPath,
             threshold: threshold,
             minSilenceDuration: minSilenceSeconds,
             minSpeechDuration: minSpeechSeconds,
             windowSize: windowSize,
             maxSpeechDuration: maxSpeechSeconds,
           ),
           sampleRate: kAsrSampleRate,
           numThreads: 1,
           provider: 'cpu',
           debug: false,
         ),
         bufferSizeInSeconds: kAsrWindowSeconds * 2,
       );

  final sherpa.VoiceActivityDetector _vad;

  @override
  void accept(Float32List samples) => _vad.acceptWaveform(samples);

  @override
  bool get speechDetected => _vad.isDetected();

  @override
  VadSpan? pop() {
    if (_vad.isEmpty()) return null;
    final segment = _vad.front();
    _vad.pop();
    return VadSpan(startSample: segment.start, samples: segment.samples);
  }

  @override
  void flush() => _vad.flush();

  @override
  void dispose() => _vad.free();
}

/// The offline recognizer behind the pipeline's [LiveDecoder] interface: one
/// stream per prepared utterance.
class SherpaLiveDecoder implements LiveDecoder {
  SherpaLiveDecoder(this._recognizer);

  final sherpa.OfflineRecognizer _recognizer;

  @override
  String decode(Float32List samples) {
    final stream = _recognizer.createStream();
    try {
      stream.acceptWaveform(samples: samples, sampleRate: kAsrSampleRate);
      _recognizer.decode(stream);
      return _recognizer.getResult(stream).text;
    } finally {
      stream.free();
    }
  }
}
