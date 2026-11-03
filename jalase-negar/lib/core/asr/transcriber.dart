import 'dart:io';
import 'dart:isolate';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:sherpa_onnx/sherpa_onnx.dart' as sherpa;

import '../audio/wav.dart';
import '../models/model_spec.dart';
import 'asr_common.dart';
import 'energy_vad.dart';
import 'recognizer_factory.dart';

export 'asr_common.dart'
    show addAsrContext, addAsrPreRoll, normalizePersianAsrText;

/// One decoded utterance from a single channel.
class TranscriptSegment {
  const TranscriptSegment({
    required this.channel,
    required this.startMs,
    required this.endMs,
    required this.text,
    this.timestampSource = 'silero_vad',
  });

  final int channel;
  final int startMs;
  final int endMs;
  final String text;

  /// `silero_vad` for VAD speech spans, `vad_window` for the quiet-audio
  /// coverage windows and the server-parity regions (contract values).
  final String timestampSource;
}

/// How speech is cut into pieces before decoding.
enum AsrSegmenter {
  /// Silero VAD with look-around context and a coverage pass. The default.
  silero,

  /// The server's energy VAD (`energyVadRegions`), decoding each region
  /// without any extra audio preparation. For comparing a clip with the
  /// server's transcript region by region; the whole channel is held in memory,
  /// so it is limited to [kServerParityMaxSeconds].
  serverEnergy,
}

const int kServerParityMaxSeconds = 30 * 60;

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
    this.segmenter = AsrSegmenter.silero,
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
  final AsrSegmenter segmenter;
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
    recognizer = createOfflineRecognizer(
      architecture: request.architecture,
      asrModelPath: request.asrModelPath,
      tokensPath: request.tokensPath,
      encoderPath: request.encoderPath,
      decoderPath: request.decoderPath,
      joinerPath: request.joinerPath,
      numThreads: numThreads,
    );

    final info = await readWavInfo(request.wavPath);
    final totalFrames = info.frameCount * info.channels;
    var processedFrames = 0;

    for (var channel = 0; channel < info.channels; channel++) {
      if (request.segmenter == AsrSegmenter.serverEnergy) {
        await _transcribeServerRegions(
          request: request,
          info: info,
          channel: channel,
          recognizer: recognizer,
          sendPort: sendPort,
        );
        processedFrames += info.frameCount;
        sendPort.send(TranscribeProgress(processedFrames / totalFrames));
        continue;
      }
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
          sampleRate: kAsrSampleRate,
          numThreads: 1,
          provider: 'cpu',
          debug: false,
        ),
        bufferSizeInSeconds: kAsrWindowSeconds * 2,
      );

      void decodeAndSend({
        required Float32List samples,
        required int startMs,
        int? contentEndMs,
        String timestampSource = 'silero_vad',
      }) {
        if (samples.isEmpty) return;
        final stream = recognizer!.createStream();
        try {
          stream.acceptWaveform(samples: samples, sampleRate: kAsrSampleRate);
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
              startMs + (samples.length * 1000) ~/ kAsrSampleRate;
          // VAD and the quiet-audio coverage pass can touch the same
          // utterance. Suppress near-identical overlapping text while keeping
          // legitimate repetitions elsewhere in the meeting.
          final duplicate = isDuplicateTranscript(
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
              timestampSource: timestampSource,
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
                  .run(samples: samples, sampleRate: kAsrSampleRate)
                  .samples;
        return normalizeQuietAudio(enhanced.isEmpty ? samples : enhanced);
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
            startMs: speechStartSample * 1000 ~/ kAsrSampleRate,
            contentEndMs: speechEndSample * 1000 ~/ kAsrSampleRate,
          );
        }
      }

      await for (final chunk in readChannelSamples(
        request.wavPath,
        info: info,
        channel: channel,
        targetSampleRate: kAsrSampleRate,
        chunkFrames: (kAsrWindowSeconds * info.sampleRate).round(),
      )) {
        final prepared = prepareSamples(chunk.samples);
        currentAudioWindow = appendSamples(audioHistory, prepared);
        currentAudioWindowStartSample = fedSamples - audioHistory.length;
        vad.acceptWaveform(prepared);
        drain(flush: false);
        fedSamples += prepared.length;
        audioHistory = tailSamples(currentAudioWindow, kAsrHistorySamples);
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
      const fallbackWindowSamples = kAsrSampleRate * 10;
      await for (final chunk in readChannelSamples(
        request.wavPath,
        info: info,
        channel: channel,
        targetSampleRate: kAsrSampleRate,
        chunkFrames: (kAsrWindowSeconds * info.sampleRate).round(),
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
              fallbackStartMs + offset * 1000 ~/ kAsrSampleRate;
          final windowEndMs = fallbackStartMs + end * 1000 ~/ kAsrSampleRate;
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
              timestampSource: 'vad_window',
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

/// Server-parity pass: the server's energy VAD cuts the channel into regions
/// and each region is decoded as is, so the result can be compared with the
/// server's `ensure_timestamps` transcript clip by clip.
Future<void> _transcribeServerRegions({
  required TranscribeRequest request,
  required WavInfo info,
  required int channel,
  required sherpa.OfflineRecognizer recognizer,
  required SendPort sendPort,
}) async {
  var channelSamples = Float32List(0);
  await for (final chunk in readChannelSamples(
    request.wavPath,
    info: info,
    channel: channel,
    targetSampleRate: kAsrSampleRate,
    chunkFrames: (kAsrWindowSeconds * info.sampleRate).round(),
  )) {
    channelSamples = appendSamples(channelSamples, chunk.samples);
    if (channelSamples.length > kAsrSampleRate * kServerParityMaxSeconds) {
      throw Exception(
        'حالت هم‌ترازی با سرور فقط برای صوت کوتاه‌تر از '
        '${kServerParityMaxSeconds ~/ 60} دقیقه است',
      );
    }
  }
  final regions = energyVadRegions(channelSamples, kAsrSampleRate);
  for (final region in regions) {
    final startSample = (region.start * kAsrSampleRate).floor();
    final endSample = math.min(
      channelSamples.length,
      (region.end * kAsrSampleRate).ceil(),
    );
    if (endSample <= startSample) continue;
    final stream = recognizer.createStream();
    try {
      stream.acceptWaveform(
        samples: Float32List.sublistView(
          channelSamples,
          startSample,
          endSample,
        ),
        sampleRate: kAsrSampleRate,
      );
      recognizer.decode(stream);
      final text = normalizePersianAsrText(recognizer.getResult(stream).text);
      if (text.isEmpty) continue;
      sendPort.send(
        TranscriptSegment(
          channel: channel,
          startMs: (region.start * 1000).round(),
          endMs: (region.end * 1000).round(),
          text: text,
          timestampSource: 'vad_window',
        ),
      );
    } finally {
      stream.free();
    }
  }
}
