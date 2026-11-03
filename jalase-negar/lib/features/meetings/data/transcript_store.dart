import 'meeting.dart';

/// What the live transcript needs from storage while a meeting is recorded.
/// [MeetingRepository] implements it; tests use an in-memory fake.
abstract interface class TranscriptStore {
  /// Records how the stored transcript was produced (ASR parity identity).
  Future<void> setAsrIdentity(String meetingId, String identity);

  /// Adds segments after the ones already stored.
  Future<void> appendSegments(String meetingId, List<Segment> segments);

  /// Replaces every stored segment of the meeting.
  Future<void> replaceSegments(String meetingId, List<Segment> segments);
}
