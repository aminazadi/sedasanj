import 'meeting.dart';

/// The platform stores one text per segment and rejects longer ones, so the
/// editor never produces a line above this length (see `MeetingTranscriptSegmentIn`).
const int kMaxSegmentChars = 4000;

/// Text shown in the editor: one line per non-empty segment in time order.
///
/// The SedaSanj panel shows a transcript as a list of segments with plain text,
/// so the editor is plain text where a line break separates two segments.
String transcriptEditorText(List<Segment> segments) =>
    _orderedSegments(segments).map((s) => _lineOf(s.text)).join('\n');

List<Segment> _orderedSegments(List<Segment> segments) {
  final sorted = [...segments]
    ..sort((a, b) {
      final byTime = a.startMs.compareTo(b.startMs);
      return byTime != 0 ? byTime : a.channel.compareTo(b.channel);
    });
  return [
    for (final s in sorted)
      if (_lineOf(s.text).isNotEmpty) s,
  ];
}

/// One segment text as a single editor line.
String _lineOf(String text) =>
    text.replaceAll(RegExp(r'\s*[\r\n]+\s*'), ' ').trim();

/// Editor text as the lines that will be saved: trimmed, without blank lines,
/// each at most [kMaxSegmentChars] long (longer ones break at a space).
List<String> canonicalTranscriptLines(String text) {
  final lines = <String>[];
  for (final raw in text.split(RegExp(r'\r\n|\r|\n'))) {
    var rest = raw.trim();
    while (rest.length > kMaxSegmentChars) {
      var cut = rest.lastIndexOf(RegExp(r'\s'), kMaxSegmentChars);
      if (cut < kMaxSegmentChars ~/ 2) cut = kMaxSegmentChars;
      lines.add(rest.substring(0, cut).trim());
      rest = rest.substring(cut).trim();
    }
    if (rest.isNotEmpty) lines.add(rest);
  }
  return lines;
}

/// [text] as it will read after saving (what the editor shows once saved).
String canonicalTranscriptText(String text) =>
    canonicalTranscriptLines(text).join('\n');

/// Maps edited editor text back onto segments.
///
/// Lines that did not change keep their segment untouched. Edited lines keep
/// the timing of the line they replace; inserted lines take a share of the
/// time around them, and merged or split lines take the combined or divided
/// range, so start times never go backwards (a platform requirement).
List<Segment> applyTranscriptEdit(List<Segment> original, String edited) {
  final old = _orderedSegments(original);
  final lines = canonicalTranscriptLines(edited);
  final oldLines = [for (final s in old) _lineOf(s.text)];

  final result = <Segment?>[...List<Segment?>.filled(lines.length, null)];

  // Unchanged head and tail first: they are by far the common case.
  var head = 0;
  while (head < old.length &&
      head < lines.length &&
      oldLines[head] == lines[head]) {
    result[head] = old[head];
    head++;
  }
  var tail = 0;
  while (tail < old.length - head &&
      tail < lines.length - head &&
      oldLines[old.length - 1 - tail] == lines[lines.length - 1 - tail]) {
    result[lines.length - 1 - tail] = old[old.length - 1 - tail];
    tail++;
  }

  final oldEnd = old.length - tail;
  final newEnd = lines.length - tail;
  final anchors = _alignMiddle(oldLines, lines, head, oldEnd, head, newEnd);
  for (final (o, n) in anchors) {
    result[n] = old[o];
  }

  // Fill every gap between anchors.
  var oldFrom = head;
  var newFrom = head;
  final bounds = [...anchors, (oldEnd, newEnd)];
  for (final (o, n) in bounds) {
    if (n > newFrom || o > oldFrom) {
      _fillGap(
        old: old,
        lines: lines,
        result: result,
        oldRange: (oldFrom, o),
        newRange: (newFrom, n),
      );
    }
    oldFrom = o + 1;
    newFrom = n + 1;
  }
  // The tail anchors sit right after the last gap; nothing to fill past them.

  return _monotonic([for (final s in result) s!]);
}

/// Longest common run of equal lines inside the changed middle, as (old, new)
/// index pairs. Falls back to no anchors when the middle is too large for the
/// quadratic table, which only costs timing accuracy, never text.
List<(int, int)> _alignMiddle(
  List<String> oldLines,
  List<String> lines,
  int oldFrom,
  int oldTo,
  int newFrom,
  int newTo,
) {
  final rows = oldTo - oldFrom;
  final cols = newTo - newFrom;
  if (rows <= 0 || cols <= 0 || rows * cols > 4000000) return const [];

  final table = List.generate(rows + 1, (_) => List<int>.filled(cols + 1, 0));
  for (var i = rows - 1; i >= 0; i--) {
    for (var j = cols - 1; j >= 0; j--) {
      table[i][j] = oldLines[oldFrom + i] == lines[newFrom + j]
          ? table[i + 1][j + 1] + 1
          : (table[i + 1][j] >= table[i][j + 1]
                ? table[i + 1][j]
                : table[i][j + 1]);
    }
  }
  final pairs = <(int, int)>[];
  var i = 0;
  var j = 0;
  while (i < rows && j < cols) {
    if (oldLines[oldFrom + i] == lines[newFrom + j]) {
      pairs.add((oldFrom + i, newFrom + j));
      i++;
      j++;
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      i++;
    } else {
      j++;
    }
  }
  return pairs;
}

void _fillGap({
  required List<Segment> old,
  required List<String> lines,
  required List<Segment?> result,
  required (int, int) oldRange,
  required (int, int) newRange,
}) {
  final (oldFrom, oldTo) = oldRange;
  final (newFrom, newTo) = newRange;
  final k = oldTo - oldFrom;
  final m = newTo - newFrom;
  if (m <= 0) return;

  if (k == 0) {
    // Pure insertion: share the time between the neighbours.
    final prevEnd = _neighbourEnd(old, result, newFrom, oldFrom);
    final nextStart = oldFrom < old.length ? old[oldFrom].startMs : prevEnd;
    final lo = prevEnd;
    final hi = nextStart < lo ? lo : nextStart;
    final base = _templateFor(old, result, newFrom, oldFrom);
    for (var j = 0; j < m; j++) {
      result[newFrom + j] = _edited(
        base,
        lines[newFrom + j],
        lo + (hi - lo) * j ~/ m,
        lo + (hi - lo) * (j + 1) ~/ m,
        replacing: false,
      );
    }
    return;
  }

  for (var j = 0; j < m; j++) {
    final int start;
    final int end;
    final Segment base;
    if (m <= k) {
      // Lines merged: take the whole range of the lines they replace.
      final first = j * k ~/ m;
      final last = ((j + 1) * k ~/ m - 1).clamp(first, k - 1).toInt();
      base = old[oldFrom + first];
      start = base.startMs;
      end = old[oldFrom + last].endMs;
    } else {
      // Lines split: divide the replaced line's range between its parts.
      final i = j * k ~/ m;
      base = old[oldFrom + i];
      var from = j;
      while (from > 0 && (from - 1) * k ~/ m == i) {
        from--;
      }
      var to = j;
      while (to + 1 < m && (to + 1) * k ~/ m == i) {
        to++;
      }
      final parts = to - from + 1;
      final p = j - from;
      final span = base.endMs - base.startMs;
      start = base.startMs + span * p ~/ parts;
      end = base.startMs + span * (p + 1) ~/ parts;
    }
    result[newFrom + j] = _edited(
      base,
      lines[newFrom + j],
      start,
      end,
      replacing: true,
    );
  }
}

int _neighbourEnd(
  List<Segment> old,
  List<Segment?> result,
  int newIndex,
  int oldIndex,
) {
  for (var i = newIndex - 1; i >= 0; i--) {
    final s = result[i];
    if (s != null) return s.endMs;
  }
  if (oldIndex < old.length) return old[oldIndex].startMs;
  return 0;
}

Segment _templateFor(
  List<Segment> old,
  List<Segment?> result,
  int newIndex,
  int oldIndex,
) {
  for (var i = newIndex - 1; i >= 0; i--) {
    final s = result[i];
    if (s != null) return s;
  }
  if (oldIndex < old.length) return old[oldIndex];
  return const Segment(channel: 0, startMs: 0, endMs: 0, text: '');
}

/// A new or rewritten segment. The recognizer's confidence and speaker belong
/// to the original words, so they are dropped.
Segment _edited(
  Segment base,
  String text,
  int startMs,
  int endMs, {
  required bool replacing,
}) => Segment(
  channel: base.channel,
  startMs: startMs,
  endMs: endMs < startMs ? startMs : endMs,
  text: text,
  speaker: replacing ? base.speaker : null,
  timestampSource: base.timestampSource,
  source: base.source,
  speakerPersonId: replacing ? base.speakerPersonId : null,
  speaker2: replacing ? base.speaker2 : null,
  speaker2PersonId: replacing ? base.speaker2PersonId : null,
  overlap: replacing && base.overlap,
  speakerConfidence: replacing ? base.speakerConfidence : null,
  speakerManual: replacing && base.speakerManual,
);

/// Start times never go backwards and every end is at or after its start.
List<Segment> _monotonic(List<Segment> segments) {
  final out = <Segment>[];
  var previousStart = 0;
  for (final s in segments) {
    final start = s.startMs < previousStart ? previousStart : s.startMs;
    final end = s.endMs < start ? start : s.endMs;
    out.add(
      start == s.startMs && end == s.endMs
          ? s
          : s.copyWith(startMs: start, endMs: end),
    );
    previousStart = start;
  }
  return out;
}

/// Folds characters that Persian text mixes freely, one code unit to one, so
/// match offsets in the folded text are offsets in the real text.
String foldForSearch(String text) {
  final buffer = StringBuffer();
  for (final unit in text.codeUnits) {
    buffer.writeCharCode(switch (unit) {
      0x064A || 0x0649 => 0x06CC, // ي ى → ی
      0x0643 => 0x06A9, // ك → ک
      >= 0x0660 && <= 0x0669 => unit - 0x0660 + 0x06F0, // ٠-٩ → ۰-۹
      >= 0x41 && <= 0x5A => unit + 0x20, // A-Z → a-z
      _ => unit,
    });
  }
  return buffer.toString();
}

/// Start offsets of every non-overlapping match of [query] in [text],
/// ignoring Latin case and Arabic/Persian letter and digit variants.
List<int> findTranscriptMatches(String text, String query) {
  if (query.isEmpty) return const [];
  final haystack = foldForSearch(text);
  final needle = foldForSearch(query);
  final matches = <int>[];
  var from = 0;
  while (true) {
    final at = haystack.indexOf(needle, from);
    if (at < 0) break;
    matches.add(at);
    from = at + needle.length;
  }
  return matches;
}

/// [text] with the matches (from [findTranscriptMatches]) replaced.
String replaceTranscriptMatches(
  String text,
  List<int> matches,
  int length,
  String replacement,
) {
  final buffer = StringBuffer();
  var cursor = 0;
  for (final at in matches) {
    buffer
      ..write(text.substring(cursor, at))
      ..write(replacement);
    cursor = at + length;
  }
  buffer.write(text.substring(cursor));
  return buffer.toString();
}
