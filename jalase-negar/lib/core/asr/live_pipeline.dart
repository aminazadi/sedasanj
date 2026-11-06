import 'dart:math' as math;
import 'dart:typed_data';

import '../speaker/speaker_labeler.dart';
import 'asr_common.dart';
import 'live_asr_engine.dart';
import 'sound_events.dart';

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
    this.maxDeferredSeconds = 600,
    UtteranceLabeler? labeler,
    SoundEventDetector? soundEvents,
    int maxSpeechSeconds = 30,
    int Function()? nowMicros,
  }) : _nowMicros = nowMicros ?? _wallMicros,
       _vadFactory = vadFactory,
       _decoder = decoder,
       _labeler = labeler,
       _soundEvents = soundEvents,
       _vad = vadFactory(),
       // A span can be a full max-speech long and still needs look-back
       // context, so the ring covers both plus the look-around on each side.
       _history = SampleHistory((maxSpeechSeconds + 4) * kAsrSampleRate);

  final LiveVadFactory _vadFactory;
  final LiveDecoder _decoder;
  final SampleHistory _history;
  final UtteranceLabeler? _labeler;

  /// Names laughter, crying and other non-speech sounds. Dropped for good if
  /// it ever throws: the speech text must not depend on it.
  SoundEventDetector? _soundEvents;
  LiveVad _vad;

  /// Sound analysis is skipped while the phone is this far behind the
  /// microphone, so the text keeps priority over the extras.
  static const int soundEventsMaxBacklogMs = 2000;

  /// Speech detected while the engine is further behind than this is skipped
  /// instead of decoded, so the live text catches up with the microphone.
  final int maxBacklogMs;

  /// While decoding runs slower than this fraction of real time, utterances
  /// shorter than [lightModeMinSpanMs] (fillers, coughs) are not decoded, which
  /// frees time for the sentences that matter.
  final double lightModeRtf;
  final int lightModeMinSpanMs;

  /// Audio kept for spans that were not decoded in time, so they can be
  /// decoded later instead of being lost. Beyond this, a skipped span stays
  /// skipped (the recording itself still has it).
  final int maxDeferredSeconds;

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
  final List<String?> _recentSpeakers = [];
  final List<_Deferred> _deferred = [];
  int _deferredSamples = 0;

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
    final events = _drain(backlogMs);
    events.addAll(_detectSounds(samples, backlogMs));
    return events;
  }

  /// Sound events inside this chunk. When the engine is behind (or shedding
  /// load) the chunk is not analysed, only counted, so later events keep the
  /// right times.
  List<LiveEvent> _detectSounds(Float32List samples, int backlogMs) {
    final detector = _soundEvents;
    if (detector == null) return const [];
    try {
      final found = backlogMs > soundEventsMaxBacklogMs || lightMode
          ? detector.skip(samples.length)
          : detector.accept(samples);
      return _soundEventEvents(found);
    } catch (_) {
      _soundEvents = null;
      return const [];
    }
  }

  List<LiveEvent> _flushSounds() {
    final detector = _soundEvents;
    if (detector == null) return const [];
    try {
      return _soundEventEvents(detector.flush());
    } catch (_) {
      _soundEvents = null;
      return const [];
    }
  }

  static List<LiveEvent> _soundEventEvents(List<DetectedSoundEvent> found) => [
    for (final e in found)
      LiveSoundEvent(
        startMs: e.startMs,
        endMs: e.endMs,
        kindId: e.kind.id,
        text: e.text,
      ),
  ];

  /// Ends the utterance in progress and restarts the VAD (pause, interruption).
  /// The timeline keeps counting, so later spans stay aligned with the WAV.
  List<LiveEvent> flush({int backlogMs = 0}) {
    _vad.flush();
    final events = _drain(backlogMs);
    events.addAll(_flushSounds());
    _vad.dispose();
    _vad = _vadFactory();
    _vadBase = _fed;
    return events;
  }

  /// Final flush; the pipeline is unusable afterwards.
  ///
  /// Deferred spans are decoded for at most [recoverBudgetMs] of wall time;
  /// whatever does not fit stays reported as skipped.
  List<LiveEvent> finish({int backlogMs = 0, int recoverBudgetMs = 0}) {
    _vad.flush();
    final events = _drain(backlogMs);
    events.addAll(_flushSounds());
    _vad.dispose();
    if (recoverBudgetMs > 0) {
      events.addAll(recover(budgetMs: recoverBudgetMs, maxSpans: 1 << 30));
    }
    return events;
  }

  /// True while skipped speech is waiting to be decoded.
  bool get hasDeferred => _deferred.isNotEmpty;

  /// Decodes spans that were skipped or shed earlier, oldest first, stopping
  /// after [maxSpans] or once [budgetMs] of wall time is used (0 = no limit
  /// besides [maxSpans]). Call it only while the engine is idle.
  List<LiveEvent> recover({int budgetMs = 0, int maxSpans = 1}) {
    final events = <LiveEvent>[];
    final began = _nowMicros();
    var done = 0;
    while (_deferred.isNotEmpty && done < maxSpans) {
      if (budgetMs > 0 && (_nowMicros() - began) ~/ 1000 >= budgetMs) break;
      final item = _deferred.removeAt(0);
      _deferredSamples -= item.pcm.length;
      done++;
      final samples = Float32List(item.pcm.length);
      for (var i = 0; i < samples.length; i++) {
        samples[i] = item.pcm[i] / 32768.0;
      }
      _process(samples, item.startSample, events);
      if (item.reported) {
        events.add(
          LiveRecovered(
            startMs: item.startSample * 1000 ~/ kAsrSampleRate,
            endMs: (item.startSample + samples.length) * 1000 ~/ kAsrSampleRate,
          ),
        );
      }
    }
    return events;
  }

  void _defer(Float32List samples, int startSample, {required bool reported}) {
    if ((_deferredSamples + samples.length) >
        maxDeferredSeconds * kAsrSampleRate) {
      return;
    }
    final pcm = Int16List(samples.length);
    for (var i = 0; i < samples.length; i++) {
      pcm[i] = (samples[i] * 32767).round().clamp(-32768, 32767);
    }
    _deferred.add(_Deferred(startSample, pcm, reported));
    _deferredSamples += pcm.length;
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
        _defer(span.samples, startSample, reported: true);
        events.add(LiveSkipped(startMs: startMs, endMs: endMs));
        continue;
      }
      if (lightMode && endMs - startMs < lightModeMinSpanMs) {
        _defer(span.samples, startSample, reported: false);
        continue;
      }
      _process(span.samples, startSample, events);
    }
    return events;
  }

  /// Labels (when possible), decodes and reports one span of speech.
  void _process(Float32List samples, int startSample, List<LiveEvent> events) {
    final endSample = startSample + samples.length;
    final startMs = startSample * 1000 ~/ kAsrSampleRate;
    final parts = _labelSpan(samples, startMs);
    if (parts == null || parts.length <= 1) {
      _emit(
        events,
        text: _decodeSpan(samples, startSample, endSample),
        startMs: startMs,
        endMs: endSample * 1000 ~/ kAsrSampleRate,
        part: parts?.first,
      );
      return;
    }
    // Several speakers: decode each stretch on its own so every line has one
    // speaker (or is marked as overlapping).
    for (final part in parts) {
      final from = math.max(0, part.startMs - startMs) * kAsrSampleRate ~/ 1000;
      final to = math.min(
        samples.length,
        (part.endMs - startMs) * kAsrSampleRate ~/ 1000,
      );
      if (to <= from) continue;
      _emit(
        events,
        text: _decodeSpan(
          Float32List.sublistView(samples, from, to),
          startSample + from,
          startSample + to,
        ),
        startMs: part.startMs,
        endMs: part.endMs,
        part: part,
      );
    }
  }

  /// Speaker parts of a span, or null when identification is off, shed to
  /// keep up, or failed (the text is then shown without a name).
  List<LabeledPart>? _labelSpan(Float32List samples, int startMs) {
    final labeler = _labeler;
    if (labeler == null || lightMode) return null;
    try {
      return labeler.label(samples, startMs: startMs);
    } catch (_) {
      return null;
    }
  }

  void _emit(
    List<LiveEvent> events, {
    required String text,
    required int startMs,
    required int endMs,
    LabeledPart? part,
  }) {
    if (text.isEmpty) return;
    final key = text.replaceAll(RegExp(r'\s+'), ' ').trim().toLowerCase();
    // Two different people saying the same short word ("yes") back to back is
    // not a duplicate: only compare with lines of the same (or unknown) voice.
    final who = _speakerKey(part);
    final comparable = <(int, int, String)>[
      for (var i = 0; i < _recent.length; i++)
        if (who == null ||
            _recentSpeakers[i] == null ||
            _recentSpeakers[i] == who)
          _recent[i],
    ];
    if (isDuplicateTranscript(
      candidate: key,
      startMs: startMs,
      endMs: endMs,
      emitted: comparable,
    )) {
      return;
    }
    _recent.add((startMs, endMs, key));
    _recentSpeakers.add(who);
    if (_recent.length > kAsrRecentKeep) {
      _recent.removeAt(0);
      _recentSpeakers.removeAt(0);
    }
    events.add(
      LiveUtterance(
        startMs: startMs,
        endMs: endMs,
        text: text,
        speaker: part?.speakers.first,
        speaker2: part != null && part.speakers.length > 1
            ? part.speakers[1]
            : null,
        overlap: part?.overlap ?? false,
        speakerConfidence: part?.confidence,
      ),
    );
  }

  static String? _speakerKey(LabeledPart? part) {
    if (part == null) return null;
    final first = part.speakers.first;
    return first.personId ?? first.name;
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

class _Deferred {
  _Deferred(this.startSample, this.pcm, this.reported);

  final int startSample;
  final Int16List pcm;

  /// Whether a [LiveSkipped] was sent for it (so [LiveRecovered] must follow).
  final bool reported;
}
