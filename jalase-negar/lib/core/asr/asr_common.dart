import 'dart:math' as math;
import 'dart:typed_data';

/// ASR helpers shared by the post-recording transcriber and the live engine.

const int kAsrSampleRate = 16000;
const double kAsrWindowSeconds = 30.0;
const double kTargetSpeechRms = 0.08;
const double kMaxQuietGain = 8.0;
const int kAsrPreRollSamples = (kAsrSampleRate * 3) ~/ 4;
const int kAsrPostRollSamples = (kAsrSampleRate * 3) ~/ 4;
const int kAsrHistorySamples = kAsrSampleRate * 3;
const int kAsrDuplicateWindowMs = 1200;
const int kAsrDuplicateMinChars = 8;
const double kAsrDuplicateTokenRatio = 0.85;
const int kAsrRecentKeep = 8;

/// Segmentation name of the draft written while recording: Silero VAD fed
/// live, gain applied per utterance, no coverage pass and no denoiser.
const String kLiveSegmentation = 'silero-vad-live';

/// Applies conservative, meaning-preserving cleanup to raw Persian ASR text.
///
/// ASR vocabularies can emit Arabic Yeh/Kaf and combining marks even when the
/// rest of the app uses Persian Unicode. Keeping this normalization here makes
/// duplicate detection, live rendering, search and later LLM correction agree
/// on the same text without inventing punctuation or words.
String normalizePersianAsrText(String input) {
  return input
      .replaceAll('ي', 'ی')
      .replaceAll('ى', 'ی')
      .replaceAll('ك', 'ک')
      .replaceAll('ۀ', 'هٔ')
      .replaceAll('\u0640', '')
      .replaceAll(RegExp(r'[\u064B-\u065F\u0670]'), '')
      .replaceAll(RegExp(r'[ \t]+'), ' ')
      .replaceAll(RegExp(r' *\n *'), '\n')
      .replaceAll(RegExp(r'\n{3,}'), '\n\n')
      .trim();
}

bool isDuplicateTranscript({
  required String candidate,
  required int startMs,
  required int endMs,
  required List<(int, int, String)> emitted,
}) {
  final candidateTokens = candidate
      .split(' ')
      .where((token) => token.isNotEmpty)
      .toSet();
  return emitted.any((item) {
    final overlaps =
        item.$1 < endMs + kAsrDuplicateWindowMs &&
        item.$2 > startMs - kAsrDuplicateWindowMs;
    if (!overlaps) return false;
    final previous = item.$3;
    if (previous == candidate) return true;
    // Only a candidate that adds nothing is a duplicate. A longer one that
    // merely contains the earlier line carries new words and must be kept.
    if (candidate.length >= kAsrDuplicateMinChars &&
        previous.contains(candidate)) {
      return true;
    }
    final previousTokens = previous
        .split(' ')
        .where((token) => token.isNotEmpty)
        .toSet();
    if (candidateTokens.length < 3 || previousTokens.length < 3) return false;
    // Share of the CANDIDATE's own words already said; a candidate with many
    // new words is never dropped just because it repeats an old line.
    final shared = candidateTokens.intersection(previousTokens).length;
    return shared / candidateTokens.length >= kAsrDuplicateTokenRatio;
  });
}

/// Adds bounded two-sided context around a VAD segment without changing its
/// timeline.
///
/// Silero emits a segment only after its speech probability crosses the
/// threshold. That can clip the first phoneme of an utterance, especially the
/// first utterance in a file. Shenava's CTC export is full-context/offline, so
/// a short look-ahead also prevents the first chunk from being decoded with
/// too little right context. The recognizer gets bounded context while
/// timestamps remain tied to the actual VAD segment.
({Float32List samples, int startSample}) addAsrContext({
  required Float32List speech,
  required int speechStartSample,
  required int speechEndSample,
  required Float32List availableContext,
  required int availableContextStartSample,
  int preRollSamples = kAsrPreRollSamples,
  int postRollSamples = kAsrPostRollSamples,
}) {
  if (speech.isEmpty || (preRollSamples <= 0 && postRollSamples <= 0)) {
    return (samples: speech, startSample: speechStartSample);
  }

  final requestedStart = speechStartSample - preRollSamples;
  final contextEnd = availableContextStartSample + availableContext.length;
  final prefixStart = math.max(requestedStart, availableContextStartSample);
  final prefixEnd = math.min(speechStartSample, contextEnd);
  final prefixLength = math.max(0, prefixEnd - prefixStart);
  final missingLength = math.max(0, preRollSamples - prefixLength);
  final suffixStart = math.max(speechEndSample, availableContextStartSample);
  final suffixEnd = math.min(speechEndSample + postRollSamples, contextEnd);
  final suffixLength = math.max(0, suffixEnd - suffixStart);
  final output = Float32List(
    missingLength + prefixLength + speech.length + suffixLength,
  );

  // Missing context occurs only at the beginning of a file or when the
  // bounded history no longer reaches far enough back. Silence is safer than
  // shifting real speech or changing the recognized timeline.
  var outputOffset = missingLength;
  if (prefixLength > 0) {
    final sourceOffset = prefixStart - availableContextStartSample;
    output.setRange(
      outputOffset,
      outputOffset + prefixLength,
      availableContext,
      sourceOffset,
    );
    outputOffset += prefixLength;
  }
  output.setRange(outputOffset, outputOffset + speech.length, speech);
  outputOffset += speech.length;
  if (suffixLength > 0) {
    final sourceOffset = suffixStart - availableContextStartSample;
    output.setRange(
      outputOffset,
      outputOffset + suffixLength,
      availableContext,
      sourceOffset,
    );
  }
  return (samples: output, startSample: math.max(0, requestedStart));
}

/// Backwards-compatible helper for callers that only need look-back context.
({Float32List samples, int startSample}) addAsrPreRoll({
  required Float32List speech,
  required int speechStartSample,
  required Float32List availableContext,
  required int availableContextStartSample,
  int preRollSamples = kAsrPreRollSamples,
}) => addAsrContext(
  speech: speech,
  speechStartSample: speechStartSample,
  speechEndSample: speechStartSample + speech.length,
  availableContext: availableContext,
  availableContextStartSample: availableContextStartSample,
  preRollSamples: preRollSamples,
  postRollSamples: 0,
);

Float32List appendSamples(Float32List first, Float32List second) {
  if (first.isEmpty) return second;
  if (second.isEmpty) return first;
  final output = Float32List(first.length + second.length);
  output.setRange(0, first.length, first);
  output.setRange(first.length, output.length, second);
  return output;
}

Float32List tailSamples(Float32List samples, int maxLength) {
  if (samples.length <= maxLength) return samples;
  return Float32List.sublistView(samples, samples.length - maxLength);
}

/// Raises quiet PCM audio before VAD/ASR without amplifying digital silence.
///
/// Sherpa models expect normalized float samples. Phone microphones can
/// legitimately produce speech around RMS .005-.02, which is below the
/// effective operating range of a VAD tuned for normal recordings.
Float32List normalizeQuietAudio(Float32List input) {
  if (input.isEmpty) return input;
  // Remove microphone DC offset. It wastes model dynamic range and can make
  // VAD treat a silent channel as continuous low-level speech.
  var mean = 0.0;
  for (final sample in input) {
    mean += sample;
  }
  mean /= input.length;
  var sumSquares = 0.0;
  var peak = 0.0;
  for (final sample in input) {
    final centered = sample - mean;
    sumSquares += centered * centered;
    final abs = centered.abs();
    if (abs > peak) peak = abs;
  }
  final rms = math.sqrt(sumSquares / input.length);
  if (rms < 0.001 || peak == 0) return input;
  final gain = math.min(kMaxQuietGain, kTargetSpeechRms / rms);
  if (gain <= 1.05) return input;
  final output = Float32List(input.length);
  for (var i = 0; i < input.length; i++) {
    output[i] = ((input[i] - mean) * gain).clamp(-1.0, 1.0).toDouble();
  }
  return output;
}
