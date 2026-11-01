import 'dart:io';
import 'dart:isolate';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:sherpa_onnx/sherpa_onnx.dart' as sherpa;

import '../audio/wav.dart';
import '../models/model_spec.dart';

/// One decoded utterance from a single channel.
class TranscriptSegment {
  const TranscriptSegment({
    required this.channel,
    required this.startMs,
    required this.endMs,
    required this.text,
  });

  final int channel;
  final int startMs;
  final int endMs;
  final String text;
}

class TranscribeRequest {
  const TranscribeRequest({
    required this.wavPath,
    required this.asrModelPath,
    required this.tokensPath,
    required this.vadModelPath,
    this.denoiserModelPath,
    this.architecture = AsrArchitecture.nemoCtc,
    this.encoderPath,
    this.decoderPath,
    this.joinerPath,
  });

  /// Original (possibly multi-channel) PCM16 WAV recording.
  final String wavPath;
  final String asrModelPath;
  final String tokensPath;
  final String vadModelPath;
  final String? denoiserModelPath;
  final AsrArchitecture architecture;
  final String? encoderPath;
  final String? decoderPath;
  final String? joinerPath;
}

class TranscribeProgress {
  const TranscribeProgress(this.fraction);

  final double fraction;
}

/// Transcribes every channel of a WAV recording with Shenava.
///
/// Everything — file reads, VAD segmentation and ONNX decoding — runs inside
/// a dedicated isolate so the UI thread never blocks. Progress and segments
/// stream back over a [ReceivePort].
Stream<Object> transcribe(TranscribeRequest request) {
  final port = ReceivePort();

  Future<void> run() async {
    try {
      await Isolate.spawn(_transcribeEntry, (port.sendPort, request));
    } catch (e) {
      port.sendPort.send(e is Exception ? e : Exception(e.toString()));
      port.sendPort.send(null);
    }
  }

  run();

  return port.takeWhile((message) => message != null).map((message) {
    if (message is Exception) throw message;
    return message as Object;
  });
}

const int _asrSampleRate = 16000;
const double _windowSeconds = 30.0;
const double _targetSpeechRms = 0.08;
const double _maxGain = 8.0;
const int _asrPreRollSamples = (_asrSampleRate * 3) ~/ 4;
const int _asrPostRollSamples = (_asrSampleRate * 3) ~/ 4;
const int _audioHistorySamples = _asrSampleRate * 3;

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

bool _isDuplicateTranscript({
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
    final overlaps = item.$1 < endMs + 1200 && item.$2 > startMs - 1200;
    if (!overlaps) return false;
    final previous = item.$3;
    if (previous == candidate) return true;
    if (candidate.length >= 8 &&
        (previous.contains(candidate) || candidate.contains(previous))) {
      return true;
    }
    final previousTokens = previous
        .split(' ')
        .where((token) => token.isNotEmpty)
        .toSet();
    if (candidateTokens.length < 3 || previousTokens.length < 3) return false;
    final shared = candidateTokens.intersection(previousTokens).length;
    final shorter = math.min(candidateTokens.length, previousTokens.length);
    return shared / shorter >= 0.85;
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
  int preRollSamples = _asrPreRollSamples,
  int postRollSamples = _asrPostRollSamples,
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
  int preRollSamples = _asrPreRollSamples,
}) => addAsrContext(
  speech: speech,
  speechStartSample: speechStartSample,
  speechEndSample: speechStartSample + speech.length,
  availableContext: availableContext,
  availableContextStartSample: availableContextStartSample,
  preRollSamples: preRollSamples,
  postRollSamples: 0,
);

Float32List _appendSamples(Float32List first, Float32List second) {
  if (first.isEmpty) return second;
  if (second.isEmpty) return first;
  final output = Float32List(first.length + second.length);
  output.setRange(0, first.length, first);
  output.setRange(first.length, output.length, second);
  return output;
}

Float32List _tailSamples(Float32List samples, int maxLength) {
  if (samples.length <= maxLength) return samples;
  return Float32List.sublistView(samples, samples.length - maxLength);
}

/// Raises quiet PCM audio before VAD/ASR without amplifying digital silence.
///
/// Sherpa models expect normalized float samples. Phone microphones can
/// legitimately produce speech around RMS .005-.02, which is below the
/// effective operating range of a VAD tuned for normal recordings.
Float32List _normalizeQuietAudio(Float32List input) {
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
  final gain = math.min(_maxGain, _targetSpeechRms / rms);
  if (gain <= 1.05) return input;
  final output = Float32List(input.length);
  for (var i = 0; i < input.length; i++) {
    output[i] = ((input[i] - mean) * gain).clamp(-1.0, 1.0).toDouble();
  }
  return output;
}

Future<void> _transcribeEntry((SendPort, TranscribeRequest) args) async {
  final (sendPort, request) = args;
  sherpa.OfflineRecognizer? recognizer;
  sherpa.VoiceActivityDetector? vad;
  sherpa.OfflineSpeechDenoiser? denoiser;
  try {
    sherpa.initBindings();
    final requiredPaths = <String>[
      request.vadModelPath,
      request.tokensPath,
      if (request.architecture == AsrArchitecture.transducer) ...[
        request.encoderPath ?? '',
        request.decoderPath ?? '',
        request.joinerPath ?? '',
      ] else
        request.asrModelPath,
      if (request.denoiserModelPath != null) request.denoiserModelPath!,
    ];
    for (final path in requiredPaths) {
      if (path.isEmpty || !await File(path).exists()) {
        throw Exception('فایل مدل پیدا نشد: $path');
      }
    }
    if (request.denoiserModelPath != null) {
      denoiser = sherpa.OfflineSpeechDenoiser(
        sherpa.OfflineSpeechDenoiserConfig(
          model: sherpa.OfflineSpeechDenoiserModelConfig(
            gtcrn: sherpa.OfflineSpeechDenoiserGtcrnModelConfig(
              model: request.denoiserModelPath!,
            ),
            numThreads: 1,
            provider: 'cpu',
            debug: false,
          ),
        ),
      );
    }

    final numThreads = math.max(
      1,
      math.min(4, Platform.numberOfProcessors - 1),
    );
    final modelConfig = request.architecture == AsrArchitecture.transducer
        ? sherpa.OfflineModelConfig(
            transducer: sherpa.OfflineTransducerModelConfig(
              encoder: request.encoderPath!,
              decoder: request.decoderPath!,
              joiner: request.joinerPath!,
            ),
            tokens: request.tokensPath,
            modelType: 'nemo_transducer',
            numThreads: numThreads,
            provider: 'cpu',
            debug: false,
          )
        : sherpa.OfflineModelConfig(
            nemoCtc: sherpa.OfflineNemoEncDecCtcModelConfig(
              model: request.asrModelPath,
            ),
            tokens: request.tokensPath,
            numThreads: numThreads,
            provider: 'cpu',
            debug: false,
          );
    recognizer = sherpa.OfflineRecognizer(
      sherpa.OfflineRecognizerConfig(
        model: modelConfig,
        // The official Shenava sherpa exports are validated with greedy
        // decoding. It is also substantially faster on mobile CPUs, allowing
        // transcript chunks to reach the UI sooner.
        decodingMethod: 'greedy_search',
        maxActivePaths: 4,
      ),
    );

    final info = await readWavInfo(request.wavPath);
    final totalFrames = info.frameCount * info.channels;
    var processedFrames = 0;

    for (var channel = 0; channel < info.channels; channel++) {
      final emittedRanges = <(int, int)>[];
      final emittedTexts = <(int, int, String)>[];
      var fedSamples = 0;
      var audioHistory = Float32List(0);
      var currentAudioWindow = Float32List(0);
      var currentAudioWindowStartSample = 0;
      vad = sherpa.VoiceActivityDetector(
        config: sherpa.VadModelConfig(
          sileroVad: sherpa.SileroVadModelConfig(
            model: request.vadModelPath,
            threshold: 0.35,
            minSilenceDuration: 0.9,
            minSpeechDuration: 0.2,
            maxSpeechDuration: 30.0,
          ),
          sampleRate: _asrSampleRate,
          numThreads: 1,
          provider: 'cpu',
          debug: false,
        ),
        bufferSizeInSeconds: _windowSeconds * 2,
      );

      void decodeAndSend({
        required Float32List samples,
        required int startMs,
        int? contentEndMs,
      }) {
        if (samples.isEmpty) return;
        final stream = recognizer!.createStream();
        try {
          stream.acceptWaveform(samples: samples, sampleRate: _asrSampleRate);
          recognizer.decode(stream);
          final text = normalizePersianAsrText(
            recognizer.getResult(stream).text,
          );
          if (text.isEmpty) return;
          final normalized = text
              .replaceAll(RegExp(r'\s+'), ' ')
              .trim()
              .toLowerCase();
          final endMs =
              contentEndMs ??
              startMs + (samples.length * 1000) ~/ _asrSampleRate;
          // VAD and the quiet-audio coverage pass can touch the same
          // utterance. Suppress near-identical overlapping text while keeping
          // legitimate repetitions elsewhere in the meeting.
          final duplicate = _isDuplicateTranscript(
            candidate: normalized,
            startMs: startMs,
            endMs: endMs,
            emitted: emittedTexts,
          );
          if (duplicate) return;
          sendPort.send(
            TranscriptSegment(
              channel: channel,
              startMs: startMs,
              endMs: endMs,
              text: text,
            ),
          );
          emittedRanges.add((startMs, endMs));
          emittedTexts.add((startMs, endMs, normalized));
        } finally {
          stream.free();
        }
      }

      Float32List prepareSamples(Float32List samples) {
        final enhanced = denoiser == null
            ? samples
            : denoiser
                  .run(samples: samples, sampleRate: _asrSampleRate)
                  .samples;
        return _normalizeQuietAudio(enhanced.isEmpty ? samples : enhanced);
      }

      void drain({required bool flush}) {
        if (flush) vad!.flush();
        while (!vad!.isEmpty()) {
          final segment = vad.front();
          vad.pop();
          final speechStartSample = segment.start;
          final speechEndSample = segment.start + segment.samples.length;
          final withContext = addAsrContext(
            speech: segment.samples,
            speechStartSample: speechStartSample,
            speechEndSample: speechEndSample,
            availableContext: currentAudioWindow,
            availableContextStartSample: currentAudioWindowStartSample,
          );
          decodeAndSend(
            samples: withContext.samples,
            startMs: speechStartSample * 1000 ~/ _asrSampleRate,
            contentEndMs: speechEndSample * 1000 ~/ _asrSampleRate,
          );
        }
      }

      await for (final chunk in readChannelSamples(
        request.wavPath,
        info: info,
        channel: channel,
        targetSampleRate: _asrSampleRate,
        chunkFrames: (_windowSeconds * info.sampleRate).round(),
      )) {
        final prepared = prepareSamples(chunk.samples);
        currentAudioWindow = _appendSamples(audioHistory, prepared);
        currentAudioWindowStartSample = fedSamples - audioHistory.length;
        vad.acceptWaveform(prepared);
        drain(flush: false);
        fedSamples += prepared.length;
        audioHistory = _tailSamples(currentAudioWindow, _audioHistorySamples);
        processedFrames += chunk.sourceFrames;
        sendPort.send(TranscribeProgress(processedFrames / totalFrames));
      }
      drain(flush: true);

      // Coverage pass: VAD is used for clean boundaries, but it must not be
      // allowed to silently discard a quiet phrase. Re-scan the complete
      // channel in 10-second windows and decode windows not covered by a VAD
      // segment. This catches speech VAD missed while avoiding duplicate
      // decoding for normally detected speech.
      var fallbackStartMs = 0;
      const fallbackWindowSamples = _asrSampleRate * 10;
      await for (final chunk in readChannelSamples(
        request.wavPath,
        info: info,
        channel: channel,
        targetSampleRate: _asrSampleRate,
        chunkFrames: (_windowSeconds * info.sampleRate).round(),
      )) {
        for (
          var offset = 0;
          offset < chunk.samples.length;
          offset += fallbackWindowSamples
        ) {
          final end = math.min(
            chunk.samples.length,
            offset + fallbackWindowSamples,
          );
          final windowStartMs =
              fallbackStartMs + offset * 1000 ~/ _asrSampleRate;
          final windowEndMs = fallbackStartMs + end * 1000 ~/ _asrSampleRate;
          final covered = emittedRanges.any(
            (range) =>
                range.$1 < windowEndMs - 1000 &&
                range.$2 > windowStartMs + 1000,
          );
          if (covered) continue;
          final window = Float32List.sublistView(chunk.samples, offset, end);
          var sumSquares = 0.0;
          for (final sample in window) {
            sumSquares += sample * sample;
          }
          final rms = window.isEmpty
              ? 0.0
              : math.sqrt(sumSquares / window.length);
          // Very low RMS is usually room noise. Decoding it produced
          // hallucinated words and duplicate fragments between utterances.
          if (rms >= 0.003) {
            decodeAndSend(
              samples: prepareSamples(window),
              startMs: windowStartMs,
            );
          }
        }
        fallbackStartMs += chunk.sourceFrames * 1000 ~/ info.sampleRate;
      }
      vad.free();
      vad = null;
    }
    sendPort.send(const TranscribeProgress(1));
  } catch (e) {
    sendPort.send(Exception(e.toString()));
  } finally {
    vad?.free();
    recognizer?.free();
    denoiser?.free();
    sendPort.send(null);
  }
}
