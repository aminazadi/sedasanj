import 'meeting.dart';
import 'speaker_edit.dart';

/// A voice heard in a meeting that nobody enrolled, found by the live or the
/// precise pass ("Unknown 2").
class DetectedSpeaker {
  const DetectedSpeaker({
    required this.label,
    required this.lineCount,
    required this.speechMs,
    required this.sampleText,
    required this.usable,
  });

  final String label;
  final int lineCount;
  final int speechMs;

  /// The first words this voice said, so the user can tell who it is.
  final String sampleText;

  /// Enough clean speech to make a voiceprint.
  final bool usable;
}

/// Speech needed from one voice before it can become a person.
const int kMinDetectedSpeechMs = 4000;

bool _isNumberedUnknown(Segment s) {
  final name = s.speaker;
  if (name == null || s.speakerPersonId != null) return false;
  return RegExp(r'^ناشناس \S+$').hasMatch(name);
}

/// The unnamed voices of a meeting, most talkative first. Overlapping lines
/// are left out of the speech time: two voices are mixed in them.
List<DetectedSpeaker> detectUnnamedSpeakers(List<Segment> segments) {
  final lines = <String, int>{};
  final speech = <String, int>{};
  final sample = <String, String>{};
  for (final s in segments) {
    if (!_isNumberedUnknown(s) || s.text.trim().isEmpty) continue;
    final label = s.speaker!;
    lines[label] = (lines[label] ?? 0) + 1;
    sample.putIfAbsent(label, () => s.text.trim());
    if (!s.overlap) {
      speech[label] = (speech[label] ?? 0) + (s.endMs - s.startMs);
    }
  }
  final out = [
    for (final label in lines.keys)
      DetectedSpeaker(
        label: label,
        lineCount: lines[label]!,
        speechMs: speech[label] ?? 0,
        sampleText: sample[label]!,
        usable: (speech[label] ?? 0) >= kMinDetectedSpeechMs,
      ),
  ]..sort((a, b) => b.speechMs.compareTo(a.speechMs));
  return out;
}

/// Splits the clean lines of [label] into at most [maxGroups] groups of at
/// least [targetMs] each (several short samples make a steadier voiceprint
/// than one). Each group is a list of `[startMs, endMs]`.
List<List<List<int>>> voiceprintGroups(
  List<Segment> segments,
  String label, {
  int targetMs = 8000,
  int maxGroups = 3,
}) {
  final spans = [
    for (final s in segments)
      if (_isNumberedUnknown(s) &&
          s.speaker == label &&
          !s.overlap &&
          s.endMs > s.startMs)
        [s.startMs, s.endMs],
  ]..sort((a, b) => a[0].compareTo(b[0]));
  final groups = <List<List<int>>>[];
  var current = <List<int>>[];
  var length = 0;
  for (final span in spans) {
    current.add(span);
    length += span[1] - span[0];
    if (length >= targetMs) {
      groups.add(current);
      current = [];
      length = 0;
    }
  }
  if (current.isNotEmpty && length >= kMinDetectedSpeechMs ~/ 2) {
    groups.add(current);
  }
  if (groups.length <= maxGroups) return groups;
  // Spread the samples over the meeting instead of taking the first ones.
  return [
    for (var i = 0; i < maxGroups; i++)
      groups[i * (groups.length - 1) ~/ (maxGroups - 1)],
  ];
}

/// Gives every line of [label] to [choice].
List<Segment> nameDetectedSpeaker(
  List<Segment> segments,
  String label,
  SpeakerChoice choice,
) {
  final index = segments.indexWhere(
    (s) => !s.overlap && _isNumberedUnknown(s) && s.speaker == label,
  );
  if (index < 0) return segments;
  return assignSpeaker(segments, index, choice, allWithSameLabel: true);
}

/// Longest stretch played for one sample, so a long monologue stays short.
const int kMaxSamplePlayMs = 12000;

/// One line of an unnamed voice offered for listening.
class SpeakerSample {
  const SpeakerSample({
    required this.startMs,
    required this.endMs,
    required this.text,
    required this.overlap,
  });

  final int startMs;
  final int endMs;
  final String text;
  final bool overlap;
}

/// Lines of the unnamed voice [label] worth listening to, longest first.
/// Clean lines come before overlapped ones (two voices are mixed there); very
/// short blips are skipped; one sample never plays longer than
/// [kMaxSamplePlayMs].
List<SpeakerSample> unnamedSpeakerSampleLines(
  List<Segment> segments,
  String label,
) {
  List<SpeakerSample> pick({required bool overlap}) {
    final spans = [
      for (final s in segments)
        if (_isNumberedUnknown(s) &&
            s.speaker == label &&
            s.overlap == overlap &&
            s.endMs - s.startMs >= 800)
          SpeakerSample(
            startMs: s.startMs,
            endMs: s.endMs.clamp(s.startMs, s.startMs + kMaxSamplePlayMs),
            text: s.text.trim(),
            overlap: overlap,
          ),
    ]..sort((a, b) => (b.endMs - b.startMs).compareTo(a.endMs - a.startMs));
    return spans;
  }

  return [...pick(overlap: false), ...pick(overlap: true)];
}

/// The same samples as `[startMs, endMs]` pairs.
List<List<int>> unnamedSpeakerSamples(List<Segment> segments, String label) => [
  for (final s in unnamedSpeakerSampleLines(segments, label))
    [s.startMs, s.endMs],
];
