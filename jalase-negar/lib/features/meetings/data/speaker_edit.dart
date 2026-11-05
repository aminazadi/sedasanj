import 'meeting.dart';

/// A speaker the user can give to a line: an enrolled person, or a free label
/// such as "Unknown 1".
class SpeakerChoice {
  const SpeakerChoice({required this.name, this.personId});

  final String name;
  final String? personId;

  bool get isPerson => personId != null;

  /// A voice nobody enrolled ("Unknown", "Unknown 2").
  bool get isUnknownLabel => personId == null && name.startsWith('ناشناس');

  @override
  bool operator ==(Object other) =>
      other is SpeakerChoice &&
      other.name == name &&
      other.personId == personId;

  @override
  int get hashCode => Object.hash(name, personId);
}

/// The first speaker of [s] as a choice; null when the line has none.
SpeakerChoice? firstSpeakerOf(Segment s) => s.speaker == null
    ? null
    : SpeakerChoice(name: s.speaker!, personId: s.speakerPersonId);

SpeakerChoice? secondSpeakerOf(Segment s) => s.speaker2 == null
    ? null
    : SpeakerChoice(name: s.speaker2!, personId: s.speaker2PersonId);

/// Gives line [index] to [choice] (or removes the speaker when null). A hand
/// made choice is marked manual, so no automatic pass changes it again, and it
/// is certain, so its confidence is full. With [allWithSameLabel], every line
/// of the same unknown speaker is renamed as well (naming "Unknown 1").
List<Segment> assignSpeaker(
  List<Segment> segments,
  int index,
  SpeakerChoice? choice, {
  bool allWithSameLabel = false,
}) {
  final target = segments[index];
  final oldKey = _key(firstSpeakerOf(target));
  return [
    for (var i = 0; i < segments.length; i++)
      if (i == index)
        _assigned(segments[i], choice)
      else if (allWithSameLabel &&
          oldKey != null &&
          !segments[i].overlap &&
          _key(firstSpeakerOf(segments[i])) == oldKey)
        _assigned(segments[i], choice)
      else
        segments[i],
  ];
}

String? _key(SpeakerChoice? c) =>
    c == null ? null : (c.personId ?? 'u:${c.name}');

Segment _assigned(Segment s, SpeakerChoice? choice) {
  if (choice == null) {
    return Segment(
      channel: s.channel,
      startMs: s.startMs,
      endMs: s.endMs,
      text: s.text,
      confidence: s.confidence,
      timestampSource: s.timestampSource,
      source: s.source,
      speakerManual: true,
    );
  }
  return Segment(
    channel: s.channel,
    startMs: s.startMs,
    endMs: s.endMs,
    text: s.text,
    confidence: s.confidence,
    timestampSource: s.timestampSource,
    source: s.source,
    speaker: choice.name,
    speakerPersonId: choice.personId,
    speakerConfidence: 100,
    speakerManual: true,
  );
}

/// Where to cut [text] so the first part holds about [fraction] of it, at a
/// space when there is one nearby. Never returns 0 or the full length.
int suggestSplitOffset(String text, {double fraction = 0.5}) {
  if (text.length < 2) return text.length;
  var at = (text.length * fraction).round().clamp(1, text.length - 1);
  final before = text.lastIndexOf(' ', at);
  final after = text.indexOf(' ', at);
  final candidates = [
    if (before > 0) before,
    if (after > 0 && after < text.length - 1) after,
  ];
  if (candidates.isNotEmpty) {
    candidates.sort((a, b) => (a - at).abs().compareTo((b - at).abs()));
    at = candidates.first;
  }
  return at;
}

/// Splits line [index] into two lines for two speakers: the text is cut at
/// [offset] and the time is shared in proportion to the text. Both lines are
/// hand made (manual, full confidence, not overlapping). Returns the segments
/// unchanged when the text cannot be split.
List<Segment> splitToTwoSpeakers(
  List<Segment> segments,
  int index, {
  required int offset,
  required SpeakerChoice first,
  required SpeakerChoice second,
}) {
  final s = segments[index];
  final text = s.text;
  final cut = offset.clamp(0, text.length);
  final head = text.substring(0, cut).trim();
  final tail = text.substring(cut).trim();
  if (head.isEmpty || tail.isEmpty) return segments;
  final span = s.endMs - s.startMs;
  final mid = s.startMs + (span * head.length ~/ (head.length + tail.length));
  Segment part(String text, int from, int to, SpeakerChoice who) => Segment(
    channel: s.channel,
    startMs: from,
    endMs: to,
    text: text,
    timestampSource: s.timestampSource,
    source: s.source,
    speaker: who.name,
    speakerPersonId: who.personId,
    speakerConfidence: 100,
    speakerManual: true,
  );
  return [
    ...segments.sublist(0, index),
    part(head, s.startMs, mid, first),
    part(tail, mid, s.endMs, second),
    ...segments.sublist(index + 1),
  ];
}

/// The whole transcript as `Name: text` lines, for copying and sharing.
String labeledTranscriptText(List<Segment> segments) {
  final lines = <String>[];
  final ordered = [...segments]..sort((a, b) => a.startMs.compareTo(b.startMs));
  for (final s in ordered) {
    final text = s.text.replaceAll(RegExp(r'\s*[\r\n]+\s*'), ' ').trim();
    if (text.isEmpty) continue;
    lines.add(Segment(
      channel: s.channel,
      startMs: s.startMs,
      endMs: s.endMs,
      text: text,
      speaker: s.speaker,
      speaker2: s.speaker2,
    ).labeledText);
  }
  return lines.join('\n');
}

/// Distinct speakers of a meeting in order of appearance (for the picker).
List<SpeakerChoice> speakersIn(List<Segment> segments) {
  final seen = <String>{};
  final out = <SpeakerChoice>[];
  for (final s in segments) {
    for (final c in [firstSpeakerOf(s), secondSpeakerOf(s)]) {
      if (c != null && seen.add(_key(c)!)) out.add(c);
    }
  }
  return out;
}

/// Share of the meeting's speech time that is overlapping, 0..1.
double overlapShare(List<Segment> segments) {
  var total = 0;
  var over = 0;
  for (final s in segments) {
    final d = s.endMs - s.startMs;
    total += d;
    if (s.overlap) over += d;
  }
  return total == 0 ? 0 : over / total;
}
