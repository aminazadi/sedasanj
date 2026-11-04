import 'package:sherpa_onnx/sherpa_onnx.dart' as sherpa;

import '../models/model_spec.dart';

const String kAsrDecodingMethod = 'greedy_search';
const int kAsrMaxActivePaths = 4;

/// Builds the offline Shenava recognizer used by both the post-recording
/// transcriber and the live engine, so the two decode with the same settings.
sherpa.OfflineRecognizer createOfflineRecognizer({
  required AsrArchitecture architecture,
  required String asrModelPath,
  required String tokensPath,
  String? encoderPath,
  String? decoderPath,
  String? joinerPath,
  required int numThreads,
}) {
  final modelConfig = architecture == AsrArchitecture.transducer
      ? sherpa.OfflineModelConfig(
          transducer: sherpa.OfflineTransducerModelConfig(
            encoder: encoderPath!,
            decoder: decoderPath!,
            joiner: joinerPath!,
          ),
          tokens: tokensPath,
          modelType: 'nemo_transducer',
          numThreads: numThreads,
          provider: 'cpu',
          debug: false,
        )
      : sherpa.OfflineModelConfig(
          nemoCtc: sherpa.OfflineNemoEncDecCtcModelConfig(model: asrModelPath),
          tokens: tokensPath,
          numThreads: numThreads,
          provider: 'cpu',
          debug: false,
        );
  return sherpa.OfflineRecognizer(
    sherpa.OfflineRecognizerConfig(
      model: modelConfig,
      // The official Shenava sherpa exports are validated with greedy
      // decoding. It is also substantially faster on mobile CPUs, allowing
      // transcript chunks to reach the UI sooner.
      decodingMethod: kAsrDecodingMethod,
      maxActivePaths: kAsrMaxActivePaths,
    ),
  );
}
