import 'dart:async';
import 'dart:io';
import 'dart:isolate';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:sherpa_onnx/sherpa_onnx.dart' as sherpa;

import '../models/model_spec.dart';
import '../speaker/sherpa_speaker.dart';
import '../speaker/speaker_labeler.dart';
import '../speaker/speaker_matcher.dart';
import '../../features/people/data/person.dart';
import 'asr_common.dart';
import 'live_asr_engine.dart';
import 'live_pipeline.dart';
import 'recognizer_factory.dart';

const double kSileroThreshold = 0.35;
const double kSileroMinSilenceSeconds = 0.9;
const double kSileroMinSpeechSeconds = 0.2;
const int kSileroWindowSize = 512;

/// Everything the live isolate needs to load its models. Plain data, so it
/// can cross the isolate boundary.
class VadSegmentConfig {
  const VadSegmentConfig({
    required this.vadModelPath,
    required this.tokensPath,
    required this.architecture,
    this.asrModelPath = '',
    this.encoderPath,
    this.decoderPath,
    this.joinerPath,
    this.numThreads = 2,
    this.minSilenceSeconds = kSileroMinSilenceSeconds,
    this.maxBacklogMs = 60000,
    this.speakerEmbeddingPath = '',
    this.speakerSegmentationPath = '',
    this.enrolled = const [],
  });

  final String vadModelPath;
  final String tokensPath;
  final AsrArchitecture architecture;
  final String asrModelPath;
  final String? encoderPath;
  final String? decoderPath;
  final String? joinerPath;

  /// Two threads leave the rest of the CPU to audio capture and the UI.
  final int numThreads;

  /// Same default as the post-recording transcriber so both cut speech alike.
  final double minSilenceSeconds;
  final int maxBacklogMs;

  /// Speaker identification: the embedding model, the optional overlap-aware
  /// segmentation model, and the people to recognise. Empty means off.
  final String speakerEmbeddingPath;
  final String speakerSegmentationPath;
  final List<Map<String, Object?>> enrolled;

  bool get identifiesSpeakers =>
      speakerEmbeddingPath.isNotEmpty && enrolled.isNotEmpty;
}

/// Live transcription with the same models as the post-recording transcript:
/// Silero VAD cuts the microphone stream into utterances and each finished
/// one is decoded by the offline Shenava recognizer.
///
/// Everything native runs in one long-lived isolate. Audio travels to it as
/// [TransferableTypedData] in ~200 ms batches; the recording path only pays
/// for one small copy and never waits for recognition.
class VadSegmentEngine implements LiveAsrEngine {
  VadSegmentEngine(this._config);

  final VadSegmentConfig _config;
  final _controller = StreamController<LiveEvent>.broadcast();
  final _early = <Object>[];
  final _batch = BytesBuilder();
  final _done = Completer<void>();

  ReceivePort? _inbox;
  SendPort? _toIsolate;
  Isolate? _isolate;
  bool _started = false;
  bool _closed = false;
  bool _stopping = false;

  /// ~200 ms of 16 kHz mono PCM16.
  static const int _batchBytes = 6400;

  @override
  Stream<LiveEvent> get events => _controller.stream;

  @override
  Future<void> start() async {
    if (_started) return;
    _started = true;
    final inbox = ReceivePort();
    _inbox = inbox;
    inbox.listen(_onMessage);
    try {
      _isolate = await Isolate.spawn(
        _liveEntry,
        _Init(inbox.sendPort, _config),
        onError: inbox.sendPort,
      );
    } catch (_) {
      _fail('رونویسی زنده شروع نشد.');
    }
  }

  @override
  void feed(Uint8List pcm16) {
    if (_closed || _stopping || pcm16.isEmpty) return;
    _batch.add(pcm16);
    if (_batch.length >= _batchBytes) _sendBatch();
  }

  @override
  void flush() {
    if (_closed || _stopping) return;
    _sendBatch();
    _send(_Command(_CommandKind.flush, _nowMs()));
  }

  @override
  Future<void> stop({Duration timeout = const Duration(seconds: 15)}) async {
    if (_closed) return;
    if (!_stopping) {
      _sendBatch();
      _stopping = true;
      _send(_Command(_CommandKind.stop, _nowMs()));
    }
    try {
      await _done.future.timeout(timeout);
    } on TimeoutException {
      _emit(const LiveFailure('بخشی از متن زنده تا پایان ضبط آماده نشد.'));
    }
    await dispose();
  }

  @override
  Future<void> dispose() async {
    if (_closed) return;
    _closed = true;
    _isolate?.kill(priority: Isolate.immediate);
    _isolate = null;
    _inbox?.close();
    _inbox = null;
    if (!_done.isCompleted) _done.complete();
    await _controller.close();
  }

  void _sendBatch() {
    if (_batch.isEmpty) return;
    final bytes = _batch.takeBytes();
    _send(_Feed(TransferableTypedData.fromList([bytes]), _nowMs()));
  }

  void _send(Object message) {
    final port = _toIsolate;
    if (port == null) {
      // Only until the isolate answers with its port (a few milliseconds).
      _early.add(message);
    } else {
      port.send(message);
    }
  }

  void _onMessage(Object? message) {
    if (message is SendPort) {
      _toIsolate = message;
      for (final queued in _early) {
        message.send(queued);
      }
      _early.clear();
    } else if (message is LiveEvent) {
      _emit(message);
      if (message is LiveDone || (message is LiveFailure && message.fatal)) {
        if (!_done.isCompleted) _done.complete();
      }
    } else if (message is List) {
      // Uncaught error inside the isolate: [error, stackTrace].
      _fail('رونویسی زنده متوقف شد.');
    }
  }

  void _fail(String message) {
    _emit(LiveFailure(message, fatal: true));
    if (!_done.isCompleted) _done.complete();
  }

  void _emit(LiveEvent event) {
    if (!_controller.isClosed) _controller.add(event);
  }

  static int _nowMs() => DateTime.now().millisecondsSinceEpoch;
}

class _Init {
  const _Init(this.events, this.config);

  final SendPort events;
  final VadSegmentConfig config;
}

class _Feed {
  const _Feed(this.data, this.sentAtMs);

  final TransferableTypedData data;
  final int sentAtMs;
}

enum _CommandKind { flush, stop }

class _Command {
  const _Command(this.kind, this.sentAtMs);

  final _CommandKind kind;
  final int sentAtMs;
}

const int _lagOnMs = 5000;
const int _lagOffMs = 2000;
const int _maxConsecutiveErrors = 5;

void _liveEntry(_Init init) {
  final out = init.events;
  final inbox = ReceivePort();
  out.send(inbox.sendPort);

  sherpa.OfflineRecognizer? recognizer;
  LivePipeline? pipeline;
  SherpaVoiceEmbedder? embedder;
  SherpaDiarizer? diarizer;
  try {
    sherpa.initBindings();
    final config = init.config;
    final required = <String>[
      config.vadModelPath,
      config.tokensPath,
      if (config.architecture == AsrArchitecture.transducer) ...[
        config.encoderPath ?? '',
        config.decoderPath ?? '',
        config.joinerPath ?? '',
      ] else
        config.asrModelPath,
    ];
    for (final path in required) {
      if (path.isEmpty || !File(path).existsSync()) {
        throw Exception('فایل مدل پیدا نشد: $path');
      }
    }
    final created = createOfflineRecognizer(
      architecture: config.architecture,
      asrModelPath: config.asrModelPath,
      tokensPath: config.tokensPath,
      encoderPath: config.encoderPath,
      decoderPath: config.decoderPath,
      joinerPath: config.joinerPath,
      numThreads: math.max(1, config.numThreads),
    );
    recognizer = created;
    SpeakerLabeler? labeler;
    if (config.identifiesSpeakers) {
      // Speaker identification is optional: if its models do not load the
      // transcript simply has no names.
      embedder = SherpaVoiceEmbedder.tryCreate(config.speakerEmbeddingPath);
      if (embedder != null) {
        diarizer = config.speakerSegmentationPath.isEmpty
            ? null
            : SherpaDiarizer.tryCreate(
                segmentationModelPath: config.speakerSegmentationPath,
                embeddingModelPath: config.speakerEmbeddingPath,
              );
        labeler = SpeakerLabeler(
          diarizer: diarizer,
          embedder: embedder,
          matcher: SpeakerMatcher([
            for (final e in config.enrolled) EnrolledVoice.fromMap(e),
          ]),
        );
      }
    }
    pipeline = LivePipeline(
      vadFactory: () => _SherpaVad(config),
      decoder: _SherpaDecoder(created),
      maxBacklogMs: config.maxBacklogMs,
      labeler: labeler,
    );
    out.send(const LiveReady());
  } catch (_) {
    out.send(
      const LiveFailure(
        'مدل رونویسی زنده بارگذاری نشد. مدل شنوا و تشخیص گفتار را در بخش «مدل‌ها» بررسی کنید.',
        fatal: true,
      ),
    );
    recognizer?.free();
    recognizer = null;
    embedder?.free();
    embedder = null;
    diarizer?.free();
    diarizer = null;
    pipeline = null;
  }

  var lagging = false;
  var speaking = false;
  var errors = 0;

  void report(List<LiveEvent> events) {
    for (final event in events) {
      out.send(event);
    }
  }

  void shutdown() {
    recognizer?.free();
    recognizer = null;
    embedder?.free();
    embedder = null;
    diarizer?.free();
    diarizer = null;
    pipeline = null;
    out.send(const LiveDone());
    inbox.close();
  }

  inbox.listen((Object? message) {
    final live = pipeline;
    if (live == null) {
      // Model never loaded: just answer a stop so the caller does not wait.
      if (message is _Command && message.kind == _CommandKind.stop) shutdown();
      return;
    }
    try {
      if (message is _Feed) {
        final backlog = math.max(
          0,
          DateTime.now().millisecondsSinceEpoch - message.sentAtMs,
        );
        report(
          live.feed(
            message.data.materialize().asUint8List(),
            backlogMs: backlog,
          ),
        );
        if (!lagging && backlog > _lagOnMs) {
          lagging = true;
          out.send(const LiveLagState(lagging: true));
        } else if (lagging && backlog < _lagOffMs) {
          lagging = false;
          out.send(const LiveLagState(lagging: false));
        }
        final nowSpeaking = live.speechDetected;
        if (nowSpeaking != speaking) {
          speaking = nowSpeaking;
          out.send(LiveSpeechState(speaking: speaking));
        }
      } else if (message is _Command) {
        final backlog = math.max(
          0,
          DateTime.now().millisecondsSinceEpoch - message.sentAtMs,
        );
        if (message.kind == _CommandKind.flush) {
          report(live.flush(backlogMs: backlog));
          if (speaking) {
            speaking = false;
            out.send(const LiveSpeechState(speaking: false));
          }
        } else {
          report(live.finish(backlogMs: backlog));
          shutdown();
        }
      }
      errors = 0;
    } catch (_) {
      errors++;
      final fatal = errors >= _maxConsecutiveErrors;
      out.send(LiveFailure('در رونویسی زنده خطایی رخ داد.', fatal: fatal));
      if (fatal) shutdown();
    }
  });
}

/// Silero VAD with the post-recording transcriber's thresholds.
class _SherpaVad implements LiveVad {
  _SherpaVad(VadSegmentConfig config)
    : _vad = sherpa.VoiceActivityDetector(
        config: sherpa.VadModelConfig(
          sileroVad: sherpa.SileroVadModelConfig(
            model: config.vadModelPath,
            threshold: kSileroThreshold,
            minSilenceDuration: config.minSilenceSeconds,
            minSpeechDuration: kSileroMinSpeechSeconds,
            windowSize: kSileroWindowSize,
            maxSpeechDuration: kAsrWindowSeconds,
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

class _SherpaDecoder implements LiveDecoder {
  _SherpaDecoder(this._recognizer);

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
