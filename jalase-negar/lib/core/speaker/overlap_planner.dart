/// One speaker turn from the segmentation model, in milliseconds from the
/// start of the analysed audio. Turns of different local speakers may overlap
/// (the model marks up to two people talking at once).
class SpeakerTurn {
  const SpeakerTurn({
    required this.startMs,
    required this.endMs,
    required this.speaker,
  });

  final int startMs;
  final int endMs;

  /// Local label (0, 1, …) that is only meaningful inside one analysed audio.
  final int speaker;
}

/// A stretch of an utterance with a fixed set of active local speakers.
class PlannedPart {
  const PlannedPart({
    required this.startMs,
    required this.endMs,
    required this.speakers,
    this.shaky = false,
  });

  final int startMs;
  final int endMs;

  /// One local speaker, or two when they talk at once.
  final List<int> speakers;

  /// Built from a very short stretch that was folded into a neighbour; its
  /// label deserves less trust.
  final bool shaky;

  bool get overlap => speakers.length > 1;
  int get durationMs => endMs - startMs;
}

/// Turns segmentation output into the parts an utterance is split into.
///
/// * Time is cut at every point where the set of active speakers changes.
/// * Overlap shorter than [minOverlapMs] is not worth a mixed line: it goes to
///   the speaker who also talks next to it.
/// * A single-speaker part shorter than [minPartMs] is folded into the
///   neighbouring part, because a recognizer decodes very short audio badly.
/// * More than two simultaneous speakers are reduced to the two lowest local
///   labels (the model reports at most two at once).
List<PlannedPart> planParts(
  List<SpeakerTurn> turns, {
  int minOverlapMs = 500,
  int minPartMs = 1200,
}) {
  final valid = [
    for (final t in turns)
      if (t.endMs > t.startMs) t,
  ];
  if (valid.isEmpty) return const [];

  final cuts = <int>{
    for (final t in valid) ...[t.startMs, t.endMs],
  }.toList()..sort();

  var parts = <PlannedPart>[];
  for (var i = 0; i + 1 < cuts.length; i++) {
    final from = cuts[i];
    final to = cuts[i + 1];
    final active = <int>{
      for (final t in valid)
        if (t.startMs <= from && t.endMs >= to) t.speaker,
    }.toList()..sort();
    if (active.isEmpty) continue;
    parts.add(
      PlannedPart(
        startMs: from,
        endMs: to,
        speakers: active.length > 2 ? active.sublist(0, 2) : active,
      ),
    );
  }
  parts = _merge(parts);

  // Short overlap becomes plain speech of the speaker present next to it.
  final resolved = <PlannedPart>[];
  for (var i = 0; i < parts.length; i++) {
    final p = parts[i];
    if (!p.overlap || p.durationMs >= minOverlapMs) {
      resolved.add(p);
      continue;
    }
    final neighbours = <int>{
      if (i > 0) ...parts[i - 1].speakers,
      if (i + 1 < parts.length) ...parts[i + 1].speakers,
    };
    final keep = p.speakers.firstWhere(
      neighbours.contains,
      orElse: () => p.speakers.first,
    );
    resolved.add(
      PlannedPart(
        startMs: p.startMs,
        endMs: p.endMs,
        speakers: [keep],
        shaky: true,
      ),
    );
  }
  parts = _merge(resolved);

  // Fold short single-speaker parts into a neighbour, shortest first.
  while (parts.length > 1) {
    var shortest = -1;
    for (var i = 0; i < parts.length; i++) {
      if (parts[i].overlap || parts[i].durationMs >= minPartMs) continue;
      if (shortest < 0 || parts[i].durationMs < parts[shortest].durationMs) {
        shortest = i;
      }
    }
    if (shortest < 0) break;
    final p = parts[shortest];
    final intoPrevious = shortest > 0;
    final neighbour = parts[intoPrevious ? shortest - 1 : shortest + 1];
    final absorbed = PlannedPart(
      startMs: intoPrevious ? neighbour.startMs : p.startMs,
      endMs: intoPrevious ? p.endMs : neighbour.endMs,
      speakers: neighbour.speakers,
      shaky: true,
    );
    parts = [
      ...parts.sublist(0, intoPrevious ? shortest - 1 : shortest),
      absorbed,
      ...parts.sublist(shortest + (intoPrevious ? 1 : 2)),
    ];
    parts = _merge(parts);
  }
  return parts;
}

List<PlannedPart> _merge(List<PlannedPart> parts) {
  final out = <PlannedPart>[];
  for (final p in parts) {
    if (out.isNotEmpty && _sameSpeakers(out.last.speakers, p.speakers)) {
      final last = out.removeLast();
      out.add(
        PlannedPart(
          startMs: last.startMs,
          endMs: p.endMs,
          speakers: last.speakers,
          shaky: last.shaky || p.shaky,
        ),
      );
    } else {
      out.add(p);
    }
  }
  return out;
}

bool _sameSpeakers(List<int> a, List<int> b) {
  if (a.length != b.length) return false;
  for (var i = 0; i < a.length; i++) {
    if (a[i] != b[i]) return false;
  }
  return true;
}

/// Time spans where only [speaker] is active: the audio that is safe to embed
/// (overlapping speech would blend two voices into the embedding).
List<(int, int)> cleanSpans(List<SpeakerTurn> turns, int speaker) {
  final cuts = <int>{
    for (final t in turns) ...[t.startMs, t.endMs],
  }.toList()..sort();
  final spans = <(int, int)>[];
  for (var i = 0; i + 1 < cuts.length; i++) {
    final from = cuts[i];
    final to = cuts[i + 1];
    final active = <int>{
      for (final t in turns)
        if (t.startMs <= from && t.endMs >= to) t.speaker,
    };
    if (active.length == 1 && active.contains(speaker)) {
      if (spans.isNotEmpty && spans.last.$2 == from) {
        spans[spans.length - 1] = (spans.last.$1, to);
      } else {
        spans.add((from, to));
      }
    }
  }
  return spans;
}
