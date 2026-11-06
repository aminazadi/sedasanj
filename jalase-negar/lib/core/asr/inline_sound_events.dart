/// Puts sound markers such as `[خنده]` inside the line of the person who was
/// speaking, at the word where the sound happened, instead of giving every
/// sound a line of its own.
library;

/// One recognised word with the time it was said (recording timeline, ms).
class TimedWord {
  const TimedWord(this.text, this.startMs);

  final String text;
  final int startMs;
}

/// A finished speech line: its text and, when the recognizer gave them, the
/// start time of every word.
class SpeechSpan {
  const SpeechSpan({
    required this.startMs,
    required this.endMs,
    required this.text,
    this.words,
  });

  final int startMs;
  final int endMs;
  final String text;
  final List<TimedWord>? words;
}

/// A sound on the recording timeline, already in brackets.
class SoundMark {
  const SoundMark({
    required this.startMs,
    required this.endMs,
    required this.marker,
  });

  final int startMs;
  final int endMs;
  final String marker;
}

/// A sound with no speech close enough to attach to.
class LooseSounds {
  const LooseSounds({
    required this.startMs,
    required this.endMs,
    required this.text,
  });

  final int startMs;
  final int endMs;

  /// The markers of the group joined by spaces, e.g. `[خنده] [سرفه]`.
  final String text;
}

/// Where each sound went.
class SoundPlacement {
  const SoundPlacement({required this.texts, required this.loose});

  /// The text of every span, with its sounds inserted (same order as the
  /// input spans).
  final List<String> texts;

  /// Sounds that stand on their own line, in time order.
  final List<LooseSounds> loose;
}

/// A sound this close (ms) to a speech line belongs to it.
const int kSoundAttachGapMs = 3000;

/// A sound that starts this long before a line, or ends this long after it,
/// still counts as happening during it.
const int kSoundOverlapSlackMs = 300;

/// Loose sounds closer than this (ms) share one line.
const int kLooseSoundMergeMs = 3000;

/// Decides where each of [marks] goes and returns the finished texts.
///
/// - A sound that happens during a line is written inside it, before the first
///   word that starts after the sound begins (after the last word when none
///   does). Without word times its place is estimated from the position in
///   time.
/// - A sound within [attachGapMs] after a line is written at the end of that
///   line; within [attachGapMs] before one, at its start.
/// - Any other sound is loose: it gets a line of its own, and loose sounds
///   within [kLooseSoundMergeMs] of each other share it.
SoundPlacement placeSoundMarks(
  List<SpeechSpan> spans,
  List<SoundMark> marks, {
  int attachGapMs = kSoundAttachGapMs,
}) {
  final inline = List.generate(spans.length, (_) => <SoundMark>[]);
  final atStart = List.generate(spans.length, (_) => <SoundMark>[]);
  final atEnd = List.generate(spans.length, (_) => <SoundMark>[]);
  final looseMarks = <SoundMark>[];

  final ordered = [...marks]..sort((a, b) => a.startMs.compareTo(b.startMs));
  for (final mark in ordered) {
    var overlapIndex = -1;
    var overlap = 0;
    var beforeIndex = -1; // nearest line that ended before the sound
    var beforeGap = 1 << 30;
    var afterIndex = -1; // nearest line that starts after the sound
    var afterGap = 1 << 30;
    for (var i = 0; i < spans.length; i++) {
      final span = spans[i];
      final from = span.startMs - kSoundOverlapSlackMs;
      final to = span.endMs + kSoundOverlapSlackMs;
      final shared =
          (mark.endMs < to ? mark.endMs : to) -
          (mark.startMs > from ? mark.startMs : from);
      if (shared >= 0 && (overlapIndex < 0 || shared > overlap)) {
        overlapIndex = i;
        overlap = shared;
      }
      final gapBefore = mark.startMs - span.endMs;
      if (gapBefore > 0 && gapBefore < beforeGap) {
        beforeGap = gapBefore;
        beforeIndex = i;
      }
      final gapAfter = span.startMs - mark.endMs;
      if (gapAfter > 0 && gapAfter < afterGap) {
        afterGap = gapAfter;
        afterIndex = i;
      }
    }
    if (overlapIndex >= 0) {
      inline[overlapIndex].add(mark);
    } else if (beforeIndex >= 0 &&
        beforeGap <= attachGapMs &&
        beforeGap <= afterGap) {
      atEnd[beforeIndex].add(mark);
    } else if (afterIndex >= 0 && afterGap <= attachGapMs) {
      atStart[afterIndex].add(mark);
    } else {
      looseMarks.add(mark);
    }
  }

  final texts = [
    for (var i = 0; i < spans.length; i++)
      _compose(spans[i], atStart[i], inline[i], atEnd[i]),
  ];
  return SoundPlacement(texts: texts, loose: _groupLoose(looseMarks));
}

String _compose(
  SpeechSpan span,
  List<SoundMark> atStart,
  List<SoundMark> inline,
  List<SoundMark> atEnd,
) {
  if (atStart.isEmpty && inline.isEmpty && atEnd.isEmpty) return span.text;
  final words = _wordsOf(span);
  // Insertion slots 0..words.length: slot i sits before word i.
  final slots = List.generate(words.length + 1, (_) => <String>[]);
  for (final mark in atStart) {
    slots[0].add(mark.marker);
  }
  for (final mark in inline) {
    slots[_slotFor(span, words, mark)].add(mark.marker);
  }
  for (final mark in atEnd) {
    slots[words.length].add(mark.marker);
  }
  final parts = <String>[];
  for (var i = 0; i <= words.length; i++) {
    parts.addAll(slots[i]);
    if (i < words.length) parts.add(words[i].text);
  }
  return parts.join(' ');
}

/// The words of a span: the recognizer's when they match the text, otherwise
/// the text split on spaces with times estimated evenly over the span.
List<TimedWord> _wordsOf(SpeechSpan span) {
  final given = span.words;
  if (given != null &&
      given.isNotEmpty &&
      given.map((w) => w.text).join(' ') == span.text) {
    return given;
  }
  final parts = span.text.split(' ').where((w) => w.isNotEmpty).toList();
  final length = span.endMs - span.startMs;
  return [
    for (var i = 0; i < parts.length; i++)
      TimedWord(parts[i], span.startMs + length * i ~/ parts.length),
  ];
}

int _slotFor(SpeechSpan span, List<TimedWord> words, SoundMark mark) {
  for (var i = 0; i < words.length; i++) {
    if (words[i].startMs >= mark.startMs) return i;
  }
  return words.length;
}

List<LooseSounds> _groupLoose(List<SoundMark> marks) {
  final groups = <LooseSounds>[];
  for (final mark in marks) {
    if (groups.isNotEmpty &&
        mark.startMs - groups.last.endMs <= kLooseSoundMergeMs) {
      final last = groups.removeLast();
      groups.add(
        LooseSounds(
          startMs: last.startMs,
          endMs: mark.endMs > last.endMs ? mark.endMs : last.endMs,
          text: '${last.text} ${mark.marker}',
        ),
      );
    } else {
      groups.add(
        LooseSounds(
          startMs: mark.startMs,
          endMs: mark.endMs,
          text: mark.marker,
        ),
      );
    }
  }
  return groups;
}
