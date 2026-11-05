import '../../meetings/data/meeting.dart';

/// The `segments` and `speakers` of `PUT /v1/meetings/{id}/transcript`.
class TranscriptPayload {
  const TranscriptPayload({required this.segments, required this.speakers});

  final List<Map<String, Object?>> segments;
  final List<Map<String, Object?>> speakers;
}

/// Highest speaker number the platform accepts (`speaker` is 0..64).
const int kMaxSpeakerIdx = 64;

final _uuid = RegExp(
  r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$',
);

/// Builds the transcript body: one entry per segment, two entries with the
/// same times for a line spoken by two people at once (the platform stores one
/// speaker per row), and the speaker numbers with the names the app gave them.
/// Voices beyond the platform's limit are sent without a speaker.
TranscriptPayload buildTranscriptPayload(List<Segment> segments) {
  final indexOf = <String, int>{};
  final speakers = <Map<String, Object?>>[];

  int? speakerIdx(String? name, String? personId) {
    final label = name?.trim() ?? '';
    if (label.isEmpty) return null;
    final key = personId != null ? 'p:$personId' : 'u:$label';
    final known = indexOf[key];
    if (known != null) return known;
    if (indexOf.length > kMaxSpeakerIdx) return null;
    final idx = indexOf.length;
    indexOf[key] = idx;
    speakers.add({
      'idx': idx,
      'label': label.length > 80 ? label.substring(0, 80) : label,
      if (personId != null && _uuid.hasMatch(personId))
        'profile_client_id': personId,
    });
    return idx;
  }

  Map<String, Object?> entry(Segment s, int? idx, {required bool overlap}) {
    final text = s.text.length > 4000 ? s.text.substring(0, 4000) : s.text;
    return {
      't_start_ms': s.startMs,
      't_end_ms': s.endMs < s.startMs ? s.startMs : s.endMs,
      'text': text,
      'speaker': ?idx,
      if (overlap) 'overlap': true,
      if (idx != null) 'speaker_confidence': ?s.speakerConfidence,
    };
  }

  final out = <Map<String, Object?>>[];
  for (final s in segments) {
    final first = speakerIdx(s.speaker, s.speakerPersonId);
    out.add(entry(s, first, overlap: s.overlap));
    if (s.overlap) {
      final second = speakerIdx(s.speaker2, s.speaker2PersonId);
      if (second != null && second != first) {
        out.add(entry(s, second, overlap: true));
      }
    }
  }
  return TranscriptPayload(segments: out, speakers: speakers);
}
