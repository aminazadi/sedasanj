import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/features/meetings/application/meeting_providers.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';

Meeting _meeting(MeetingStatus status, {String? remote = 'remote'}) => Meeting(
  id: 'm',
  title: 'جلسه',
  createdAt: DateTime(2026, 11, 4),
  duration: const Duration(minutes: 1),
  audioPath: '/m.wav',
  sampleRate: 16000,
  channels: 1,
  status: status,
  remoteMeetingId: remote,
);

void main() {
  test('the pending flag survives the database row and copies', () {
    final meeting = _meeting(MeetingStatus.complete);
    expect(meeting.textSyncPending, isFalse);
    expect(meeting.toRow()['text_sync_pending'], 0);

    final pending = meeting.copyWith(textSyncPending: true);
    expect(pending.toRow()['text_sync_pending'], 1);
    expect(Meeting.fromRow(pending.toRow()).textSyncPending, isTrue);
    expect(pending == meeting, isFalse);
    // Rows written before database v8 have no such column.
    expect(
      Meeting.fromRow(
        {...meeting.toRow()}..remove('text_sync_pending'),
      ).textSyncPending,
      isFalse,
    );
    expect(pending.copyWith(title: 'x').textSyncPending, isTrue);
  });

  group('isTextSentToServer', () {
    test('is true only once the server holds the text', () {
      for (final status in [
        MeetingStatus.processing,
        MeetingStatus.uploaded,
        MeetingStatus.complete,
      ]) {
        expect(isTextSentToServer(_meeting(status)), isTrue, reason: '$status');
      }
      for (final status in [
        MeetingStatus.recorded,
        MeetingStatus.transcribed,
        MeetingStatus.uploading,
        MeetingStatus.failed,
      ]) {
        expect(
          isTextSentToServer(_meeting(status)),
          isFalse,
          reason: '$status',
        );
      }
    });

    test('needs a server meeting', () {
      expect(
        isTextSentToServer(_meeting(MeetingStatus.complete, remote: null)),
        isFalse,
      );
    });
  });
}
