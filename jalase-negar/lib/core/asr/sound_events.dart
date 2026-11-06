import 'dart:math' as math;
import 'dart:typed_data';

import 'asr_common.dart';

/// Non-speech human sounds written into the transcript between square
/// brackets, for example laughter or coughing.
///
/// The labels come from an AudioSet audio tagger (CED, 527 classes), which
/// scores every class independently, so laughter and speech can both be high
/// in the same second. Class names below are the AudioSet display names as
/// written in `class_labels_indices.csv` of the sherpa-onnx CED package.
///
/// ⚠ needs lab confirmation: every threshold is an informed starting value
/// taken from how AudioSet taggers behave (rare classes such as sigh or gasp
/// score low even when present), not a number measured on Persian meeting
/// audio. They live in this one table so they can be calibrated from the
/// benchmark without touching the detector.
enum SoundEventGroup {
  /// All kinds of laughter. One event per stretch, named after the strongest.
  laughter,

  /// Crying, whimpering, wailing, sighing.
  crying,

  /// How something is said: whispered, shouted, screamed, sung.
  voice,

  /// Body sounds: cough, sneeze, throat clearing, hiccup, snoring.
  body,

  /// Reactions of a crowd: applause, cheering.
  crowd,
}

/// One kind of sound the transcript can name.
class SoundEventKind {
  const SoundEventKind({
    required this.id,
    required this.labelFa,
    required this.group,
    required this.audioSetNames,
    required this.threshold,
    this.minWindows = 2,
  });

  /// Stable English id (settings, tests, logs).
  final String id;

  /// Persian text written between the brackets, without them.
  final String labelFa;
  final SoundEventGroup group;

  /// AudioSet display names that mean this kind (any of them counts).
  final List<String> audioSetNames;

  /// Smallest tagger probability (0..1) that counts as present.
  final double threshold;

  /// How many consecutive analysis windows must agree before the event is
  /// written. Short bursts (a cough, a sneeze) need only one, but with a
  /// higher threshold; long sounds need two so a single noisy window cannot
  /// put a word into the text.
  final int minWindows;

  /// The text as it appears in the transcript.
  String get marker => '[$labelFa]';
}

/// Every kind the app can write, in the order used to break ties.
///
/// The tagger uses one shared class for crying and sobbing.
const List<SoundEventKind> kSoundEventKinds = [
  // Laughter: the specific kinds first so they win a tie with the parent.
  SoundEventKind(
    id: 'belly_laugh',
    labelFa: 'قهقهه',
    group: SoundEventGroup.laughter,
    audioSetNames: ['Belly laugh'],
    threshold: 0.30,
  ),
  SoundEventKind(
    id: 'giggle',
    labelFa: 'ریزخنده',
    group: SoundEventGroup.laughter,
    audioSetNames: ['Giggle'],
    threshold: 0.30,
  ),
  SoundEventKind(
    id: 'snicker',
    labelFa: 'پوزخند',
    group: SoundEventGroup.laughter,
    audioSetNames: ['Snicker'],
    threshold: 0.35,
  ),
  SoundEventKind(
    id: 'chuckle',
    labelFa: 'خنده‌ی آرام',
    group: SoundEventGroup.laughter,
    audioSetNames: ['Chuckle, chortle'],
    threshold: 0.30,
  ),
  SoundEventKind(
    id: 'baby_laughter',
    labelFa: 'خنده‌ی کودک',
    group: SoundEventGroup.laughter,
    audioSetNames: ['Baby laughter'],
    threshold: 0.35,
  ),
  SoundEventKind(
    id: 'laughter',
    labelFa: 'خنده',
    group: SoundEventGroup.laughter,
    audioSetNames: ['Laughter'],
    threshold: 0.30,
  ),
  // Crying and related.
  SoundEventKind(
    id: 'baby_cry',
    labelFa: 'گریه‌ی نوزاد',
    group: SoundEventGroup.crying,
    audioSetNames: ['Baby cry, infant cry'],
    threshold: 0.35,
  ),
  SoundEventKind(
    id: 'whimper',
    labelFa: 'ناله‌ی آهسته',
    group: SoundEventGroup.crying,
    audioSetNames: ['Whimper'],
    threshold: 0.35,
  ),
  SoundEventKind(
    id: 'wail',
    labelFa: 'ناله',
    group: SoundEventGroup.crying,
    audioSetNames: ['Wail, moan'],
    threshold: 0.35,
  ),
  SoundEventKind(
    id: 'crying',
    labelFa: 'گریه',
    group: SoundEventGroup.crying,
    audioSetNames: ['Crying, sobbing'],
    threshold: 0.30,
  ),
  SoundEventKind(
    id: 'sigh',
    labelFa: 'آه کشیدن',
    group: SoundEventGroup.crying,
    audioSetNames: ['Sigh'],
    // Rare in AudioSet (about 300 clips), so the tagger rarely goes high.
    threshold: 0.20,
    minWindows: 1,
  ),
  SoundEventKind(
    id: 'gasp',
    labelFa: 'هین',
    group: SoundEventGroup.crying,
    audioSetNames: ['Gasp'],
    threshold: 0.25,
    minWindows: 1,
  ),
  // How it is said.
  SoundEventKind(
    id: 'scream',
    labelFa: 'جیغ',
    group: SoundEventGroup.voice,
    audioSetNames: ['Screaming'],
    threshold: 0.40,
  ),
  SoundEventKind(
    id: 'shout',
    labelFa: 'فریاد',
    group: SoundEventGroup.voice,
    audioSetNames: ['Shout', 'Yell', 'Children shouting'],
    threshold: 0.45,
  ),
  SoundEventKind(
    id: 'whisper',
    labelFa: 'پچ‌پچ',
    group: SoundEventGroup.voice,
    audioSetNames: ['Whispering'],
    // Quiet speech from a distant microphone looks like a whisper, so this
    // is deliberately strict.
    threshold: 0.60,
    minWindows: 3,
  ),
  SoundEventKind(
    id: 'singing',
    labelFa: 'آواز',
    group: SoundEventGroup.voice,
    audioSetNames: [
      'Singing',
      'Male singing',
      'Female singing',
      'Child singing',
    ],
    // Persian meetings are full of drawn-out hesitation sounds:
    // on one benchmark clip a hesitation scored 0.66 as singing, so this is
    // strict until it is calibrated on more audio.
    threshold: 0.70,
    minWindows: 4,
  ),
  SoundEventKind(
    id: 'humming',
    labelFa: 'زمزمه',
    group: SoundEventGroup.voice,
    audioSetNames: ['Humming'],
    threshold: 0.70,
    minWindows: 4,
  ),
  SoundEventKind(
    id: 'whistling',
    labelFa: 'سوت',
    group: SoundEventGroup.voice,
    audioSetNames: ['Whistling'],
    threshold: 0.45,
  ),
  // Body sounds.
  SoundEventKind(
    id: 'cough',
    labelFa: 'سرفه',
    group: SoundEventGroup.body,
    audioSetNames: ['Cough'],
    threshold: 0.40,
    minWindows: 1,
  ),
  SoundEventKind(
    id: 'throat_clearing',
    labelFa: 'صاف کردن گلو',
    group: SoundEventGroup.body,
    audioSetNames: ['Throat clearing'],
    threshold: 0.40,
    minWindows: 1,
  ),
  SoundEventKind(
    id: 'sneeze',
    labelFa: 'عطسه',
    group: SoundEventGroup.body,
    audioSetNames: ['Sneeze'],
    threshold: 0.40,
    minWindows: 1,
  ),
  SoundEventKind(
    id: 'hiccup',
    labelFa: 'سکسکه',
    group: SoundEventGroup.body,
    audioSetNames: ['Hiccup'],
    threshold: 0.40,
    minWindows: 1,
  ),
  SoundEventKind(
    id: 'snoring',
    labelFa: 'خروپف',
    group: SoundEventGroup.body,
    audioSetNames: ['Snoring'],
    threshold: 0.45,
    minWindows: 3,
  ),
  // Crowd.
  SoundEventKind(
    id: 'applause',
    labelFa: 'تشویق',
    group: SoundEventGroup.crowd,
    audioSetNames: ['Applause', 'Clapping'],
    threshold: 0.40,
  ),
  SoundEventKind(
    id: 'cheering',
    labelFa: 'هلهله',
    group: SoundEventGroup.crowd,
    audioSetNames: ['Cheering'],
    threshold: 0.40,
  ),
];

final Map<String, SoundEventKind> _kindByAudioSetName = {
  for (final kind in kSoundEventKinds)
    for (final name in kind.audioSetNames) name.toLowerCase(): kind,
};

/// The kind that an AudioSet display name stands for, or null when the app
/// does not write that sound (speech, music, breathing, dog barks, ...).
SoundEventKind? soundEventKindForName(String audioSetName) =>
    _kindByAudioSetName[audioSetName.trim().toLowerCase()];

/// One class score from the tagger.
class SoundScore {
  const SoundScore(this.name, this.probability);

  final String name;
  final double probability;
}

/// Audio tagger seen by the detector (CED in production, a fake in tests).
abstract interface class SoundTagger {
  /// The most likely classes for [samples] (16 kHz mono floats), best first.
  /// Must not throw for short or silent input.
  List<SoundScore> tag(Float32List samples);
}

/// One sound found on the recording timeline.
class DetectedSoundEvent {
  const DetectedSoundEvent({
    required this.kind,
    required this.startMs,
    required this.endMs,
    required this.score,
  });

  final SoundEventKind kind;
  final int startMs;
  final int endMs;

  /// Strongest tagger probability seen inside the event, 0..1.
  final double score;

  String get text => kind.marker;

  @override
  String toString() =>
      'DetectedSoundEvent(${kind.id} $startMs-$endMs '
      '${score.toStringAsFixed(2)})';
}

/// Finds sounds in a live audio stream.
///
/// Audio is analysed in overlapping windows ([windowMs] long, one every
/// [hopMs]). A window votes for a [SoundEventKind] when its probability
/// reaches that kind's threshold. Within one [SoundEventGroup] only the
/// strongest kind votes, so «Giggle» and «Laughter» firing together make one
/// event, not two. Consecutive votes of a group become one event (a short gap
/// of [gapWindows] windows is bridged); the event is named after the kind with
/// the largest summed probability and written only when it lasted at least
/// that kind's `minWindows`.
///
/// A vote covers the hop around the window's centre, not the whole window, so
/// the event lands within about one hop of the sound instead of smeared over
/// the window.
class SoundEventDetector {
  SoundEventDetector({
    required SoundTagger tagger,
    this.windowMs = 3000,
    this.hopMs = 1000,
    this.gapWindows = 1,
    this.silenceRms = 0.002,
  }) : assert(windowMs >= hopMs && hopMs > 0),
       _tagger = tagger,
       _windowSamples = windowMs * kAsrSampleRate ~/ 1000,
       _hopSamples = hopMs * kAsrSampleRate ~/ 1000 {
    _buffer = Float32List(_windowSamples);
  }

  final SoundTagger _tagger;
  final int windowMs;
  final int hopMs;

  /// Windows without a vote that still keep an event open.
  final int gapWindows;

  /// Windows quieter than this (RMS) are not analysed: room silence never
  /// holds a sound, and skipping it saves the tagger's time.
  final double silenceRms;

  final int _windowSamples;
  final int _hopSamples;
  late final Float32List _buffer;

  /// Samples consumed on the recording timeline.
  int _fed = 0;

  /// Timeline position of the next window end.
  int _nextEnd = 0;
  final Map<SoundEventGroup, _Run> _runs = {};

  int get fedSamples => _fed;

  /// Advances the timeline over audio that is not analysed (the phone is
  /// behind). Open events are closed so nothing is stretched over the gap.
  List<DetectedSoundEvent> skip(int samples) {
    if (samples <= 0) return const [];
    final closed = flush();
    _fed += samples;
    // The first window after the gap must hold only new audio.
    _nextEnd = _fed + _windowSamples;
    return closed;
  }

  /// Consumes [samples] and returns the events that finished meanwhile.
  List<DetectedSoundEvent> accept(Float32List samples) {
    final events = <DetectedSoundEvent>[];
    if (samples.isEmpty) return events;
    var offset = 0;
    if (_nextEnd == 0) _nextEnd = _windowSamples;
    while (offset < samples.length) {
      final untilEnd = _nextEnd - _fed;
      final take = math.min(samples.length - offset, math.max(1, untilEnd));
      _push(samples, offset, take);
      offset += take;
      if (_fed >= _nextEnd) {
        events.addAll(_analyseWindow(_nextEnd));
        _nextEnd += _hopSamples;
      }
    }
    return events;
  }

  /// Closes everything in progress (pause, stop).
  List<DetectedSoundEvent> flush() {
    final events = <DetectedSoundEvent>[];
    for (final group in _runs.keys.toList()) {
      final event = _runs.remove(group)!.finish();
      if (event != null) events.add(event);
    }
    return events;
  }

  /// Rolling window of the latest [_windowSamples] samples.
  void _push(Float32List samples, int offset, int count) {
    if (count >= _windowSamples) {
      _buffer.setRange(
        0,
        _windowSamples,
        samples,
        offset + count - _windowSamples,
      );
    } else {
      _buffer.setRange(0, _windowSamples - count, _buffer, count);
      _buffer.setRange(_windowSamples - count, _windowSamples, samples, offset);
    }
    _fed += count;
  }

  List<DetectedSoundEvent> _analyseWindow(int endSample) {
    final events = <DetectedSoundEvent>[];
    final centerMs = (endSample - _windowSamples ~/ 2) * 1000 ~/ kAsrSampleRate;
    final fromMs = math.max(0, centerMs - hopMs ~/ 2);
    final toMs = centerMs + hopMs ~/ 2;

    final votes = <SoundEventGroup, ({SoundEventKind kind, double p})>{};
    if (_rms(_buffer) >= silenceRms) {
      final scores = _tagger.tag(_buffer);
      for (final score in scores) {
        final kind = soundEventKindForName(score.name);
        if (kind == null || score.probability < kind.threshold) continue;
        final best = votes[kind.group];
        // Equal scores keep the earlier (more specific) kind of the table.
        if (best == null || score.probability > best.p + 1e-9) {
          votes[kind.group] = (kind: kind, p: score.probability);
        } else if ((score.probability - best.p).abs() <= 1e-9 &&
            kSoundEventKinds.indexOf(kind) <
                kSoundEventKinds.indexOf(best.kind)) {
          votes[kind.group] = (kind: kind, p: score.probability);
        }
      }
    }

    for (final group in SoundEventGroup.values) {
      final vote = votes[group];
      final run = _runs[group];
      if (vote != null) {
        (run ?? (_runs[group] = _Run())).add(vote.kind, vote.p, fromMs, toMs);
      } else if (run != null) {
        run.idle += 1;
        if (run.idle > gapWindows) {
          _runs.remove(group);
          final event = run.finish();
          if (event != null) events.add(event);
        }
      }
    }
    return events;
  }

  static double _rms(Float32List samples) {
    var sum = 0.0;
    for (final s in samples) {
      sum += s * s;
    }
    return math.sqrt(sum / samples.length);
  }
}

class _Run {
  int? _start;
  int _end = 0;
  int windows = 0;
  int idle = 0;
  double peak = 0;
  final Map<SoundEventKind, double> _sums = {};

  void add(SoundEventKind kind, double p, int fromMs, int toMs) {
    _start ??= fromMs;
    _end = toMs;
    windows += 1;
    idle = 0;
    if (p > peak) peak = p;
    _sums[kind] = (_sums[kind] ?? 0) + p;
  }

  /// The finished event, or null when it was too short for its kind.
  DetectedSoundEvent? finish() {
    final start = _start;
    if (start == null || _sums.isEmpty) return null;
    SoundEventKind? best;
    var bestSum = -1.0;
    for (final entry in _sums.entries) {
      final better =
          entry.value > bestSum + 1e-9 ||
          ((entry.value - bestSum).abs() <= 1e-9 &&
              best != null &&
              kSoundEventKinds.indexOf(entry.key) <
                  kSoundEventKinds.indexOf(best));
      if (better) {
        best = entry.key;
        bestSum = entry.value;
      }
    }
    if (best == null || windows < best.minWindows) return null;
    return DetectedSoundEvent(
      kind: best,
      startMs: start,
      endMs: _end,
      score: peak,
    );
  }
}
