import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/features/meetings/data/attendee.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';
import 'package:jalase_negar/features/meetings/data/meeting_repository.dart';

import 'people/people_test_support.dart';

Meeting meeting(String id) => Meeting(
  id: id,
  title: 'جلسه',
  createdAt: DateTime(2026, 1, 1),
  duration: Duration.zero,
  audioPath: '/nonexistent/$id.wav',
  sampleRate: 16000,
  channels: 1,
  status: MeetingStatus.recorded,
);

void main() {
  test('a fresh install has the attendees table', () async {
    final (db, dir) = await openTestDb();
    addTearDown(() => dir.deleteSync(recursive: true));
    final tables = [
      for (final r in await db.db.rawQuery(
        "SELECT name FROM sqlite_master WHERE type = 'table'",
      ))
        r['name'] as String,
    ];
    expect(tables, contains('meeting_attendees'));
  });

  test('upgrading from v10 adds the attendees table', () async {
    final (db, dir) = await openTestDb();
    addTearDown(() => dir.deleteSync(recursive: true));
    await db.db.execute('DROP TABLE meeting_attendees');
    await db.db.execute('PRAGMA user_version = 10');
    await db.db.close();
    final (reopened, _) = await openTestDb(dir);
    final rows = await reopened.db.rawQuery(
      "SELECT name FROM sqlite_master WHERE name = 'meeting_attendees'",
    );
    expect(rows, hasLength(1));
  });

  test(
    'attendees are replaced, ordered and removed with the meeting',
    () async {
      final (db, dir) = await openTestDb();
      addTearDown(() => dir.deleteSync(recursive: true));
      final repo = MeetingRepository(db);
      await repo.insert(meeting('m1'));

      await repo.setAttendees('m1', const [
        Attendee(personId: 'p2', name: 'سارا'),
        Attendee(personId: 'p1', name: 'علی'),
      ]);
      expect((await repo.attendees('m1')).map((a) => a.personId).toSet(), {
        'p1',
        'p2',
      });

      await repo.setAttendees('m1', const [
        Attendee(personId: 'p1', name: 'علی'),
      ]);
      expect(await repo.attendees('m1'), const [
        Attendee(personId: 'p1', name: 'علی'),
      ]);
      expect(await repo.attendees('other'), isEmpty);

      await repo.delete(meeting('m1'));
      final left = await db.db.query('meeting_attendees');
      expect(left, isEmpty);
    },
  );

  test('the same person twice is stored once', () async {
    final (db, dir) = await openTestDb();
    addTearDown(() => dir.deleteSync(recursive: true));
    final repo = MeetingRepository(db);
    await repo.insert(meeting('m1'));
    await repo.setAttendees('m1', const [
      Attendee(personId: 'p1', name: 'علی'),
      Attendee(personId: 'p1', name: 'علی'),
    ]);
    expect(await repo.attendees('m1'), hasLength(1));
    expect(Directory(dir.path).existsSync(), isTrue);
  });
}
