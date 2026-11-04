import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/asr/asr_common.dart';
import 'package:jalase_negar/core/asr/recognizer_factory.dart';
import 'package:jalase_negar/core/asr/vad_segment_engine.dart';

void main() {
  test('live ASR defaults match the server Silero contract', () {
    final contract = jsonDecode(
      File(
        '../aiservice/asr_service/services/vad_segment_contract.json',
      ).readAsStringSync(),
    );
    expect(contract, {
      'sample_rate': kAsrSampleRate,
      'pre_roll_samples': kAsrPreRollSamples,
      'post_roll_samples': kAsrPostRollSamples,
      'target_rms': kTargetSpeechRms,
      'max_gain': kMaxQuietGain,
      'threshold': kSileroThreshold,
      'min_silence_seconds': kSileroMinSilenceSeconds,
      'min_speech_seconds': kSileroMinSpeechSeconds,
      'max_speech_seconds': kAsrWindowSeconds,
      'window_size': kSileroWindowSize,
      'duplicate_window_ms': kAsrDuplicateWindowMs,
      'duplicate_min_chars': kAsrDuplicateMinChars,
      'duplicate_token_ratio': kAsrDuplicateTokenRatio,
      'recent_keep': kAsrRecentKeep,
      'decoding_method': kAsrDecodingMethod,
      'max_active_paths': kAsrMaxActivePaths,
    });
  });
}
