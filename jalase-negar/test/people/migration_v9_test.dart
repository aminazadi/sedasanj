import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/db/app_database.dart';
import 'package:jalase_negar/features/meetings/data/meeting_repository.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'people_test_support.dart';

void main() {
  test('v8 databases upgrade to v9 and keep their segments', () async {
    sqfliteFfiInit();
    final dir = Directory.systemTemp.createTempSync('v8');
    addTearDown(() => dir.deleteSync(recursive: true));
    final path = '${dir.path}/old.db';

    final old = await databaseFactoryFfi.openDatabase(
      path,
      options: OpenDatabaseOptions(
        version: 8,
        onConfigure: (db) => db.execute('PRAGMA foreign_keys = ON'),
        onCreate: (db, _) => AppDatabase.createV8ForTest(db),
      ),
    );
    await old.insert('meetings', {
      'id': 'm1',
      'title': 'جلسه',
      'created_at': 1,
      'duration_ms': 5000,
      'audio_path': '/a.wav',
      'sample_rate': 16000,
      'channels': 1,
      'status': 'complete',
    });
    await old.insert('segments', {
      'meeting_id': 'm1',
      'channel': 0,
      't_start_ms': 0,
      't_end_ms': 1000,
      'text': 'سلام',
    });
    await old.close();

    final db = await AppDatabase.open(path, factory: databaseFactoryFfi);
    addTearDown(db.db.close);

    final tables = [
      for (final r in await db.db.rawQuery(
        "SELECT name FROM sqlite_master WHERE type = 'table'",
      ))
        r['name'] as String,
    ];
    expect(tables, containsAll(['people', 'voiceprints', 'sync_outbox']));

    final segments = await MeetingRepository(db).segments('m1');
    expect(segments.single.text, 'سلام');
    expect(segments.single.speaker, isNull);
    expect(segments.single.overlap, isFalse);
    expect(segments.single.speakerManual, isFalse);

    // The new columns round-trip.
    await MeetingRepository(db).replaceSegments('m1', const [
      Segment(
        channel: 0,
        startMs: 0,
        endMs: 1000,
        text: 'سلام',
        speaker: 'علی',
        speakerPersonId: 'ali',
        speaker2: 'سارا',
        speaker2PersonId: 'sara',
        overlap: true,
        speakerConfidence: 41,
        speakerManual: true,
      ),
    ]);
    final back = (await MeetingRepository(db).segments('m1')).single;
    expect(back.speakerLabel, 'علی / سارا');
    expect(back.overlap, isTrue);
    expect(back.speakerConfidence, 41);
    expect(back.speakerManual, isTrue);
  });

  test('a fresh install has the v9 schema', () async {
    final (db, dir) = await openTestDb();
    addTearDown(() => dir.deleteSync(recursive: true));
    final version = await db.db.getVersion();
    expect(version, AppDatabase.schemaVersion);
    expect(AppDatabase.schemaVersion, 9);
    final columns = [
      for (final r in await db.db.rawQuery('PRAGMA table_info(segments)'))
        r['name'] as String,
    ];
    expect(
      columns,
      containsAll([
        'speaker_person_id',
        'overlap',
        'speaker_confidence',
        'speaker_manual',
      ]),
    );
  });
}
