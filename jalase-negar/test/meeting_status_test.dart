import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';

Meeting _meeting(MeetingStatus status) => Meeting(
  id: 'm1',
  title: 't',
  createdAt: DateTime(2026),
  duration: Duration.zero,
  audioPath: '/a.wav',
  sampleRate: 16000,
  channels: 1,
  status: status,
);

void main() {
  test('a recording row with no open recorder reads as recorded', () {
    expect(
      _meeting(MeetingStatus.recording).asClosedRecording().status,
      MeetingStatus.recorded,
    );
  });

  test('other statuses are left alone', () {
    for (final s in MeetingStatus.values.where(
      (s) => s != MeetingStatus.recording,
    )) {
      expect(_meeting(s).asClosedRecording().status, s);
    }
  });
}
