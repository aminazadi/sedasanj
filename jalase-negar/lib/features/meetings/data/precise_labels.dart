import '../../../core/speaker/overlap_planner.dart';
import '../../../core/speaker/speaker_matcher.dart';
import 'meeting.dart';

/// Result of whole-recording diarization (layer B): who the global speaker
/// clusters are, and when each one talks.
class PreciseAnalysis {
  const PreciseAnalysis({required this.turns, required this.identities});

  /// Speaker turns in milliseconds from the start of the recording; the
  /// speaker is a global cluster number (consistent across the whole file).
  final List<SpeakerTurn> turns;

  /// Cluster number to the enrolled person it matched, or "Unknown N".
  final Map<int, SpeakerIdentity> identities;
}

/// How much of a line a speaker must cover to be named for it, and how long a
/// second voice must be heard to make the line an overlap.
const double kPreciseMinShare = 0.3;
const int kPreciseMinOverlapMs = 500;

/// Re-labels the lines of a meeting from a whole-recording analysis.
///
/// * A line the user labelled by hand is never touched.
/// * The text and times stay as they are; only who spoke changes.
/// * A line mostly covered by one cluster gets that speaker; a second cluster
///   heard for at least [kPreciseMinOverlapMs] makes it an overlap line with
///   both names.
/// * A line the analysis does not cover keeps its live label.
List<Segment> applyPreciseLabels(
  List<Segment> segments,
  PreciseAnalysis analysis,
) {
  return [for (final s in segments) _relabel(s, analysis)];
}

Segment _relabel(Segment s, PreciseAnalysis analysis) {
  if (s.speakerManual) return s;
  final span = s.endMs - s.startMs;
  if (span <= 0) return s;

  final byCluster = <int, int>{};
  for (final t in analysis.turns) {
    final from = t.startMs > s.startMs ? t.startMs : s.startMs;
    final to = t.endMs < s.endMs ? t.endMs : s.endMs;
    if (to > from) byCluster[t.speaker] = (byCluster[t.speaker] ?? 0) + (to - from);
  }
  if (byCluster.isEmpty) return s;
  final ranked = byCluster.entries.toList()
    ..sort((a, b) => b.value.compareTo(a.value));
  final top = ranked.first;
  final first = analysis.identities[top.key];
  if (first == null || top.value < span * kPreciseMinShare) return s;

  SpeakerIdentity? second;
  if (ranked.length > 1 && ranked[1].value >= kPreciseMinOverlapMs) {
    final candidate = analysis.identities[ranked[1].key];
    if (candidate != null && candidate.key != first.key) second = candidate;
  }

  final share = top.value / span;
  var confidence = (first.confidence * share.clamp(0.0, 1.0)).round();
  if (second != null) {
    confidence = confidence < 45 ? confidence : 45;
    if (second.confidence < confidence) confidence = second.confidence;
  }
  return Segment(
    channel: s.channel,
    startMs: s.startMs,
    endMs: s.endMs,
    text: s.text,
    confidence: s.confidence,
    timestampSource: s.timestampSource,
    source: s.source,
    speaker: first.name,
    speakerPersonId: first.personId,
    speaker2: second?.name,
    speaker2PersonId: second?.personId,
    overlap: second != null,
    speakerConfidence: confidence,
  );
}
