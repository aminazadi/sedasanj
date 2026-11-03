import 'dart:math' as math;
import 'dart:typed_data';

import 'asr_common.dart';
import 'live_asr_engine.dart';

/// A finished speech span cut by the VAD. [startSample] counts from when that
/// VAD instance was created.
class VadSpan {
  const VadSpan({required this.startSample, required this.samples});

  final int startSample;
  final Float32List samples;
}

/// Voice activity detector seen by the pipeline (Silero in production, a fake
/// in tests).
abstract interface class LiveVad {
  void accept(Float32List samples);
  bool get speechDetected;

  /// The next finished span, or null when none is ready.
  VadSpan? pop();

  /// Closes the span in progress so [pop] can return it.
  void flush();
  void dispose();
}

typedef LiveVadFactory = LiveVad Function();

/// Speech-to-text for one prepared utterance.
abstract interface class LiveDecoder {
  String decode(Float32List samples);
}

/// Fixed-size ring of the most recent samples, addressed by absolute sample
/// index, so context around a finished span can be cut without keeping the
/// whole recording in memory.
class SampleHistory {
  SampleHistory(this.capacity) : _buffer = Float32List(capacity);

  final int capacity;
  final Float32List _buffer;
  int _end = 0;

  int get endSample => _end;
  int get startSample => math.max(0, _end - capacity);

  void append(Float32List samples) {
    if (samples.isEmpty) return;
    final skip = math.max(0, samples.length - capacity);
    var position = (_end + skip) % capacity;
    var source = skip;
    var remaining = samples.length - skip;
    while (remaining > 0) {
      final count = math.min(remaining, capacity - position);
      _buffer.setRange(position, position + count, samples, source);
      position = (position + count) % capacity;
      source += count;
      remaining -= count;
    }
    _end += samples.length;
  }

  /// Samples in `[from, to)` clipped to what is still held, with the absolute
  /// index of the first returned sample.
  ({Float32List samples, int start}) slice(int from, int to) {
    final start = math.max(from, startSample);
    final end = math.min(to, _end);
    if (end <= start) return (samples: Float32List(0), start: start);
    final output = Float32List(end - start);
    var position = start % capacity;
    var written = 0;
    while (written < output.length) {
      final count = math.min(output.length - written, capacity - position);
      output.setRange(written, written + count, _buffer, position);
      written += count;
      position = (position + count) % capacity;
    }
    return (samples: output, start: start);
  }
}

/// Turns a PCM16 stream into utterances: VAD cuts speech, each finished span
/// gets look-around context and a gain lift, then one decode.
///
/// This is the single-threaded core of the live engine. It holds no native
/// handles itself, so the timeline, context and backpressure rules are tested
/// with fakes; the isolate that owns Silero and the recognizer lives in
/// `vad_segment_engine.dart`.
class LivePipeline {
  LivePipeline({
    required LiveVadFactory vadFactory,
    required LiveDecoder decoder,
    this.maxBacklogMs = 60000,
    this.lightModeRtf = 0.8,
    this.lightModeMinSpanMs = 600,
    int maxSpeechSeconds = 30,
    int Function()? nowMicros,
  }) : _nowMicros = nowMicros ?? _wallMicros,
       _vadFactory = vadFactory,
       _decoder = decoder,
       _vad = vadFactory(),
       // A span can be a full max-speech long and still needs look-back
       // context, so the ring covers both plus the look-around on each side.
       _history = SampleHistory((maxSpeechSeconds + 4) * kAsrSampleRate);

  final LiveVadFactory _vadFactory;
  final LiveDecoder _decoder;
  final SampleHistory _history;
  LiveVad _vad;

  /// Speech detected while the engine is further behind than this is skipped
  /// instead of decoded, so the live text catches up with the microphone.
  final int maxBacklogMs;

  /// While decoding runs slower than this fraction of real time, utterances
  /// shorter than [lightModeMinSpanMs] (fillers, coughs) are not decoded, which
  /// frees time for the sentences that matter.
  final double lightModeRtf;
  final int lightModeMinSpanMs;

  final int Function() _nowMicros;
  static int _wallMicros() => DateTime.now().microsecondsSinceEpoch;

  /// Smoothed decode-time / audio-time of the latest utterances.
  double _recentRtf = 0;

  /// True while the pipeline is shedding short utterances to keep up.
  bool get lightMode => _recentRtf > lightModeRtf;

  int _fed = 0;
  int _vadBase = 0;
  int? _carry;
  final List<(int, int, String)> _recent = [];

  int _decodedSamples = 0;
  int _decodeMicros = 0;

  /// Samples consumed so far on the recording timeline.
  int get fedSamples => _fed;

  bool get speechDetected => _vad.speechDetected;

  /// Decode time divided by the audio duration it covered; below 1 means the
  /// decoder keeps up with real time.
  double get realTimeFactor => _decodedSamples == 0
      ? 0
      : _decodeMicros / (_decodedSamples * 1e6 / kAsrSampleRate);

  /// [backlogMs] is how long the audio waited before reaching the pipeline.
  List<LiveEvent> feed(Uint8List pcm16, {int backlogMs = 0}) {
    final samples = _toFloat(pcm16);
    if (samples.isEmpty) return const [];
    // History first: the context cut for a span that finishes inside this
    // chunk may need the chunk's own tail as look-ahead.
    _history.append(samples);
    _fed += samples.length;
    _vad.accept(samples);
    return _drain(backlogMs);
  }

  /// Ends the utterance in progress and restarts the VAD (pause, interruption).
  /// The timeline keeps counting, so later spans stay aligned with the WAV.
  List<LiveEvent> flush({int backlogMs = 0}) {
    _vad.flush();
    final events = _drain(backlogMs);
    _vad.dispose();
    _vad = _vadFactory();
    _vadBase = _fed;
    return events;
  }

  /// Final flush; the pipeline is unusable afterwards.
  List<LiveEvent> finish({int backlogMs = 0}) {
    _vad.flush();
    final events = _drain(backlogMs);
    _vad.dispose();
    return events;
  }

  void dispose() => _vad.dispose();

  List<LiveEvent> _drain(int backlogMs) {
    final events = <LiveEvent>[];
    for (var span = _vad.pop(); span != null; span = _vad.pop()) {
      final startSample = _vadBase + span.startSample;
      final endSample = startSample + span.samples.length;
      final startMs = startSample * 1000 ~/ kAsrSampleRate;
      final endMs = endSample * 1000 ~/ kAsrSampleRate;
      if (backlogMs > maxBacklogMs) {
        events.add(LiveSkipped(startMs: startMs, endMs: endMs));
        continue;
      }
      if (lightMode && endMs - startMs < lightModeMinSpanMs) continue;
      final text = _decodeSpan(span.samples, startSample, endSample);
      if (text.isEmpty) continue;
      final key = text.replaceAll(RegExp(r'\s+'), ' ').trim().toLowerCase();
      if (isDuplicateTranscript(
        candidate: key,
        startMs: startMs,
        endMs: endMs,
        emitted: _recent,
      )) {
        continue;
      }
      _recent.add((startMs, endMs, key));
      if (_recent.length > 8) _recent.removeAt(0);
      events.add(LiveUtterance(startMs: startMs, endMs: endMs, text: text));
    }
    return events;
  }

  String _decodeSpan(Float32List speech, int startSample, int endSample) {
    final context = _history.slice(
      startSample - kAsrPreRollSamples,
      endSample + kAsrPostRollSamples,
    );
    final withContext = addAsrContext(
      speech: speech,
      speechStartSample: startSample,
      speechEndSample: endSample,
      availableContext: context.samples,
      availableContextStartSample: context.start,
    );
    final prepared = normalizeQuietAudio(withContext.samples);
    final began = _nowMicros();
    final raw = _decoder.decode(prepared);
    final elapsed = math.max(0, _nowMicros() - began);
    _decodedSamples += prepared.length;
    _decodeMicros += elapsed;
    final audioMicros = prepared.length * 1e6 / kAsrSampleRate;
    final rtf = elapsed / audioMicros;
    _recentRtf = _recentRtf == 0 ? rtf : _recentRtf * 0.7 + rtf * 0.3;
    return normalizePersianAsrText(raw);
  }

  /// PCM16 little-endian to floats in [-1, 1). An odd trailing byte waits for
  /// the next chunk.
  Float32List _toFloat(Uint8List bytes) {
    var data = bytes;
    final carry = _carry;
    if (carry != null) {
      data = Uint8List(bytes.length + 1)
        ..[0] = carry
        ..setRange(1, bytes.length + 1, bytes);
      _carry = null;
    }
    if (data.length.isOdd) _carry = data[data.length - 1];
    final count = data.length ~/ 2;
    final view = ByteData.sublistView(data);
    final output = Float32List(count);
    for (var i = 0; i < count; i++) {
      output[i] = view.getInt16(i * 2, Endian.little) / 32768.0;
    }
    return output;
  }
}
