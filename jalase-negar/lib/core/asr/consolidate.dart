/// One recognised span on the way to becoming a readable turn.
///
/// Mirrors the server's `AsrSegment` plus its channel (see
/// `sedasanj/docs/asr-parity-contract.md`).
class AsrTurn {
  const AsrTurn({
    required this.channel,
    required this.startMs,
    required this.endMs,
    required this.text,
    this.confidence,
    this.timestampSource,
    this.speaker,
    this.speakerPersonId,
    this.speaker2,
    this.speaker2PersonId,
    this.overlap = false,
    this.speakerConfidence,
  });

  final int channel;
  final int startMs;
  final int endMs;
  final String text;
  final double? confidence;

  /// `silero_vad`, `vad_window`, `native` or `diarization`; null when unknown.
  final String? timestampSource;

  /// Speaker identification (null when it was off): who spoke, and for an
  /// [overlap] line the second voice. [speakerConfidence] is 0..100.
  final String? speaker;
  final String? speakerPersonId;
  final String? speaker2;
  final String? speaker2PersonId;
  final bool overlap;
  final int? speakerConfidence;

  /// Identifies the voice for merging: two turns only join when it is equal.
  String? get voiceKey =>
      speaker == null ? null : (speakerPersonId ?? 'u:$speaker');
}

/// Server default `turn_merge_gap_ms` (worker_asr `TURN_MERGE_GAP_MS`).
const int kTurnMergeGapMs = 1200;

String _cleanText(String text) =>
    text.split(RegExp(r'\s+')).where((part) => part.isNotEmpty).join(' ');

/// Port of `consolidate_segments` (sedasanj/apps/worker_asr/worker_asr/main.py).
///
/// Creates readable chronological turns without discarding cross-talk:
/// consecutive segments of the same channel with a silence of at most
/// [mergeGapMs] become one turn, exact repeats inside an overlap are
/// suppressed, and speech on the other channel is never dropped. The shared
/// test vectors in `sedasanj/tests/fixtures/asr_parity/consolidation.json`
/// pin the behaviour on both sides.
List<AsrTurn> consolidateSegments(
  List<AsrTurn> rows, {
  int mergeGapMs = kTurnMergeGapMs,
}) {
  // Stable sort by (start, channel, end), like the Python tuple key.
  final ordered = [...rows]
    ..sort((a, b) {
      final byStart = a.startMs.compareTo(b.startMs);
      if (byStart != 0) return byStart;
      final byChannel = a.channel.compareTo(b.channel);
      if (byChannel != 0) return byChannel;
      return a.endMs.compareTo(b.endMs);
    });

  final merged = <AsrTurn>[];
  for (final segment in ordered) {
    final text = _cleanText(segment.text);
    if (text.isEmpty) continue;
    final start = segment.startMs < 0 ? 0 : segment.startMs;
    final rawEnd = segment.endMs > segment.startMs
        ? segment.endMs
        : segment.startMs;
    final current = AsrTurn(
      channel: segment.channel,
      startMs: start,
      endMs: rawEnd < 0 ? 0 : rawEnd,
      text: text,
      confidence: segment.confidence,
      timestampSource: segment.timestampSource,
      speaker: segment.speaker,
      speakerPersonId: segment.speakerPersonId,
      speaker2: segment.speaker2,
      speaker2PersonId: segment.speaker2PersonId,
      overlap: segment.overlap,
      speakerConfidence: segment.speakerConfidence,
    );
    if (merged.isEmpty) {
      merged.add(current);
      continue;
    }
    final previous = merged.last;
    // A change of speaker, or speech over another voice, always starts a new
    // line, however close in time.
    if (previous.channel == current.channel &&
        !previous.overlap &&
        !current.overlap &&
        previous.voiceKey == current.voiceKey &&
        current.startMs <= previous.endMs + mergeGapMs) {
      final overlaps = current.startMs <= previous.endMs;
      final String combined;
      if (overlaps &&
          (current.text == previous.text ||
              previous.text.endsWith(current.text))) {
        combined = previous.text;
      } else if (overlaps && current.text.startsWith(previous.text)) {
        combined = current.text;
      } else {
        combined = '${previous.text} ${current.text}';
      }
      final known = [
        if (previous.confidence != null) previous.confidence!,
        if (current.confidence != null) current.confidence!,
      ];
      merged[merged.length - 1] = AsrTurn(
        channel: previous.channel,
        startMs: previous.startMs,
        endMs: previous.endMs > current.endMs ? previous.endMs : current.endMs,
        text: combined,
        confidence: known.isEmpty
            ? null
            : known.reduce((a, b) => a < b ? a : b),
        // Like the server, a merged turn always carries a source.
        timestampSource:
            previous.timestampSource ?? current.timestampSource ?? 'native',
        speaker: previous.speaker,
        speakerPersonId: previous.speakerPersonId,
        speakerConfidence: _minNullable(
          previous.speakerConfidence,
          current.speakerConfidence,
        ),
      );
      continue;
    }
    merged.add(current);
  }
  return merged;
}

int? _minNullable(int? a, int? b) {
  if (a == null) return b;
  if (b == null) return a;
  return a < b ? a : b;
}
