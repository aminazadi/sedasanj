import 'dart:io';

import 'package:sqflite/sqflite.dart';

import '../../../core/audio/chunk_writer.dart';
import '../../../core/audio/wav.dart';
import '../../../core/db/app_database.dart';
import '../../upload/upload_queue.dart';
import 'attendee.dart';
import 'meeting.dart';
import 'transcript_store.dart';

class MeetingRepository implements UploadStore, TranscriptStore {
  MeetingRepository(this._db);

  final AppDatabase _db;

  Future<List<Meeting>> all() async {
    final rows = await _db.db.query('meetings', orderBy: 'created_at DESC');
    return rows.map(Meeting.fromRow).toList();
  }

  Future<Meeting?> byId(String id) async {
    final rows = await _db.db.query(
      'meetings',
      where: 'id = ?',
      whereArgs: [id],
    );
    return rows.isEmpty ? null : Meeting.fromRow(rows.first);
  }

  Future<void> insert(Meeting meeting) =>
      _db.db.insert('meetings', meeting.toRow());

  Future<void> update(Meeting meeting) => _db.db.update(
    'meetings',
    meeting.toRow(),
    where: 'id = ?',
    whereArgs: [meeting.id],
  );

  /// Replaces the attendees of [meetingId] with [attendees].
  Future<void> setAttendees(String meetingId, List<Attendee> attendees) =>
      _db.db.transaction((txn) async {
        await txn.delete(
          'meeting_attendees',
          where: 'meeting_id = ?',
          whereArgs: [meetingId],
        );
        for (final a in attendees) {
          await txn.insert('meeting_attendees', {
            'meeting_id': meetingId,
            'person_id': a.personId,
            'name_snapshot': a.name,
          }, conflictAlgorithm: ConflictAlgorithm.replace);
        }
      });

  @override
  Future<List<Attendee>> attendees(String meetingId) async {
    final rows = await _db.db.query(
      'meeting_attendees',
      where: 'meeting_id = ?',
      whereArgs: [meetingId],
      orderBy: 'name_snapshot COLLATE NOCASE',
    );
    return [
      for (final r in rows)
        Attendee(
          personId: r['person_id'] as String,
          name: r['name_snapshot'] as String,
        ),
    ];
  }

  Future<void> delete(
    Meeting meeting, {
    List<String> extraFiles = const [],
  }) async {
    await _db.db.delete('meetings', where: 'id = ?', whereArgs: [meeting.id]);
    for (final path in [meeting.audioPath, ...extraFiles]) {
      final file = File(path);
      if (await file.exists()) await file.delete();
    }
  }

  /// Resets meetings left mid-pipeline by a killed app to a stable status.
  Future<void> recoverStaleStatuses() async {
    await _db.db.rawUpdate('''
    UPDATE meetings SET status = CASE
      WHEN status = 'transcribing' AND EXISTS(
        SELECT 1 FROM segments WHERE meeting_id = meetings.id
      ) THEN 'transcribed'
      ELSE 'recorded'
    END
    WHERE status = 'transcribing'
  ''');
    // A closed recording can never still be "recording".
    await _db.db.rawUpdate('''
    UPDATE meetings SET status = 'recorded'
    WHERE status = 'recording' AND recording_state = 'finished'
  ''');
  }

  @override
  Future<List<Segment>> segments(String meetingId) async {
    final rows = await _db.db.query(
      'segments',
      where: 'meeting_id = ?',
      whereArgs: [meetingId],
      orderBy: 't_start_ms ASC',
    );
    return rows.map(Segment.fromRow).toList();
  }

  /// First non-empty segment texts in time order, for the list preview.
  Future<String> previewText(String meetingId, {int limit = 4}) async {
    final rows = await _db.db.query(
      'segments',
      columns: ['text'],
      where: "meeting_id = ? AND TRIM(text) != ''",
      whereArgs: [meetingId],
      orderBy: 't_start_ms ASC',
      limit: limit,
    );
    return rows.map((r) => (r['text'] as String).trim()).join(' ');
  }

  /// Ids of meetings whose stored transcript contains [query]. Arabic ی/ک
  /// variants are folded so typing either form finds the same text.
  Future<Set<String>> searchTranscripts(String query) async {
    final q = foldPersianLetters(query.trim());
    if (q.isEmpty) return const {};
    final escaped = q
        .replaceAll(r'\', r'\\')
        .replaceAll('%', r'\%')
        .replaceAll('_', r'\_');
    final rows = await _db.db.rawQuery(
      "SELECT DISTINCT meeting_id FROM segments WHERE "
      "REPLACE(REPLACE(text, 'ي', 'ی'), 'ك', 'ک') LIKE ? ESCAPE '\\'",
      ['%$escaped%'],
    );
    return {for (final r in rows) r['meeting_id']! as String};
  }

  @override
  Future<void> replaceSegments(String meetingId, List<Segment> segments) async {
    final batch = _db.db.batch();
    batch.delete('segments', where: 'meeting_id = ?', whereArgs: [meetingId]);
    for (final s in segments) {
      batch.insert('segments', {'meeting_id': meetingId, ...s.toRow()});
    }
    await batch.commit(noResult: true);
  }

  /// Records how the stored transcript was produced (ASR parity identity).
  @override
  Future<void> setAsrIdentity(String meetingId, String identity) =>
      _db.db.update(
        'meetings',
        {'asr_identity': identity},
        where: 'id = ?',
        whereArgs: [meetingId],
      );

  /// Adds segments after the ones already stored (live draft written while
  /// the recording is still running), in one transaction.
  @override
  Future<void> appendSegments(String meetingId, List<Segment> segments) async {
    if (segments.isEmpty) return;
    final batch = _db.db.batch();
    for (final s in segments) {
      batch.insert('segments', {'meeting_id': meetingId, ...s.toRow()});
    }
    await batch.commit(noResult: true);
  }

  Future<void> insertChunk(String meetingId, ChunkInfo chunk) =>
      _db.db.insert('upload_chunks', {
        'meeting_id': meetingId,
        'seq': chunk.seq,
        'local_path': chunk.path,
        'bytes': chunk.bytes,
        't_start_ms': chunk.startMs,
        't_end_ms': chunk.endMs,
      }, conflictAlgorithm: ConflictAlgorithm.replace);

  Future<List<Map<String, Object?>>> chunkRows(String meetingId) =>
      _db.db.query(
        'upload_chunks',
        where: 'meeting_id = ?',
        whereArgs: [meetingId],
        orderBy: 'seq ASC',
      );

  /// Finishes meetings whose recording was cut short (crash, kill, battery):
  /// repairs the full WAV and any unclosed chunk file, registers the orphan
  /// chunk for upload and marks the meeting as recorded. Returns how many
  /// meetings were recovered.
  Future<int> recoverInterruptedRecordings(String chunksRoot) async {
    final rows = await _db.db.query(
      'meetings',
      where: "recording_state = 'recording'",
    );
    for (final row in rows) {
      final meeting = Meeting.fromRow(row);
      final fullDuration = await repairWavHeader(meeting.audioPath);
      final registered = {
        for (final c in await chunkRows(meeting.id)) c['local_path'] as String,
      };
      var endMs = 0;
      for (final c in await chunkRows(meeting.id)) {
        endMs = c['t_end_ms'] as int;
      }
      var seq = registered.length;
      final dir = Directory('$chunksRoot/${meeting.id}');
      if (await dir.exists()) {
        final files = await dir
            .list()
            .where((e) => e is File && e.path.endsWith('.wav'))
            .map((e) => e.path)
            .toList();
        files.sort();
        for (final path in files) {
          if (registered.contains(path)) continue;
          final length = await repairWavHeader(path);
          if (length == null || length == Duration.zero) {
            await File(path).delete();
            continue;
          }
          final info = ChunkInfo(
            seq: seq,
            path: path,
            startMs: endMs,
            endMs: endMs + length.inMilliseconds,
            bytes: await File(path).length(),
          );
          await insertChunk(meeting.id, info);
          endMs = info.endMs;
          seq += 1;
        }
      }
      final duration = fullDuration ?? Duration(milliseconds: endMs);
      await update(
        meeting.copyWith(
          recordingState: 'finished',
          status: duration == Duration.zero
              ? MeetingStatus.failed
              : MeetingStatus.recorded,
          duration: duration,
          error: duration == Duration.zero
              ? 'ضبط پیش از ذخیره قطع شد و صدایی باقی نماند.'
              : null,
        ),
      );
    }
    return rows.length;
  }

  @override
  Future<List<Meeting>> uploadableMeetings() async {
    final rows = await _db.db.query(
      'meetings',
      where:
          "send_text = 1 AND (speakers_state = 'done' OR status = 'recording') "
          "AND status IN "
          "('recording', 'recorded', 'transcribed', 'uploading', 'processing')",
      orderBy: 'created_at ASC',
    );
    return rows.map(Meeting.fromRow).toList();
  }

  /// Recordings whose people still have to be identified (also those a
  /// closed app left mid-analysis).
  Future<List<Meeting>> speakerAnalysisPending() async {
    final rows = await _db.db.query(
      'meetings',
      where:
          "speakers_state != 'done' AND recording_state = 'finished' "
          "AND status != 'recording'",
      orderBy: 'created_at ASC',
    );
    return rows.map(Meeting.fromRow).toList();
  }

  Future<void> setSpeakersState(String id, String state) => _db.db.update(
    'meetings',
    {'speakers_state': state},
    where: 'id = ?',
    whereArgs: [id],
  );

  /// What still has to leave the phone: unsent audio chunks of meetings the
  /// queue will send, and transcript edits not yet pushed. The self-updater
  /// installs only when both are zero.
  Future<({int pendingChunks, int textSyncPending})> updateBacklog() async {
    final chunks = await _db.db.rawQuery(
      "SELECT COUNT(*) AS n FROM upload_chunks c JOIN meetings m ON m.id = c.meeting_id "
      "WHERE c.status != 'sent' AND m.send_text = 1 AND m.status IN "
      "('recording', 'recorded', 'transcribed', 'uploading', 'processing')",
    );
    final text = await _db.db.rawQuery(
      'SELECT COUNT(*) AS n FROM meetings WHERE text_sync_pending = 1',
    );
    return (
      pendingChunks: (chunks.first['n'] as int?) ?? 0,
      textSyncPending: (text.first['n'] as int?) ?? 0,
    );
  }

  @override
  Future<List<UploadChunk>> chunks(String meetingId) async {
    final rows = await chunkRows(meetingId);
    return [
      for (final r in rows)
        UploadChunk(
          seq: r['seq'] as int,
          path: r['local_path'] as String,
          startMs: r['t_start_ms'] as int,
          endMs: r['t_end_ms'] as int,
          status: r['status'] as String,
          attempts: r['attempts'] as int,
          sha256: r['sha256'] as String?,
          nextAttemptAt: r['next_attempt_at'] as int?,
          deviceText: r['device_text'] as String?,
        ),
    ];
  }

  @override
  Future<void> updateChunk(
    String meetingId,
    int seq, {
    String? status,
    int? attempts,
    int? nextAttemptAt,
    String? lastError,
    String? sha256,
  }) => _db.db.update(
    'upload_chunks',
    {
      'status': ?status,
      'attempts': ?attempts,
      'next_attempt_at': ?nextAttemptAt,
      'last_error_code': ?lastError,
      'sha256': ?sha256,
    },
    where: 'meeting_id = ? AND seq = ?',
    whereArgs: [meetingId, seq],
  );

  /// Queues the meeting's transcript for (re)sending, e.g. from the detail
  /// screen after the switch was off or a send failed for good.
  Future<void> requestSend(String id) => _db.db.rawUpdate(
    '''
    UPDATE meetings SET send_text = 1, error = NULL, text_sync_pending = 0,
      remote_meeting_id = NULL, status = 'recorded'
    WHERE id = ? AND status IN ('recorded', 'transcribed', 'failed')
  ''',
    [id],
  );

  /// Turns sending back on for meetings that were recorded while the switch
  /// was off (or before SedaSanj was connected) and have text but were never
  /// sent. Called when the app connects and when the switch is turned on.
  Future<int> enableSendForUnsent() => _db.db.rawUpdate('''
    UPDATE meetings SET send_text = 1
    WHERE send_text = 0 AND remote_meeting_id IS NULL
      AND status IN ('recorded', 'transcribed')
      AND EXISTS (
        SELECT 1 FROM segments s
        WHERE s.meeting_id = meetings.id AND TRIM(s.text) != ''
      )
  ''');

  @override
  Future<List<Meeting>> textSyncPendingMeetings() async {
    final rows = await _db.db.query(
      'meetings',
      where:
          "text_sync_pending = 1 AND remote_meeting_id IS NOT NULL AND "
          "status IN ('processing', 'uploaded', 'complete')",
      orderBy: 'created_at ASC',
    );
    return rows.map(Meeting.fromRow).toList();
  }

  /// Marks whether an edit of an already sent text still has to reach SedaSanj.
  @override
  Future<void> setTextSyncPending(String id, bool pending) => _db.db.update(
    'meetings',
    {'text_sync_pending': pending ? 1 : 0},
    where: 'id = ?',
    whereArgs: [id],
  );

  @override
  Future<void> setSendText(String id, bool send) => _db.db.update(
    'meetings',
    {'send_text': send ? 1 : 0},
    where: 'id = ?',
    whereArgs: [id],
  );

  @override
  Future<Meeting?> meeting(String id) => byId(id);

  @override
  Future<void> setRemoteMeetingId(String id, String remoteId) => _db.db.update(
    'meetings',
    {'remote_meeting_id': remoteId},
    where: 'id = ?',
    whereArgs: [id],
  );

  @override
  Future<void> setStatus(String id, MeetingStatus status, {String? error}) =>
      _db.db.update(
        'meetings',
        {'status': status.name, 'error': error},
        where: 'id = ?',
        whereArgs: [id],
      );

  /// Closes the recording on the meeting row without touching the columns the
  /// upload queue writes concurrently (remote id, status while uploading).
  Future<void> finishRecording(String id, Duration duration) =>
      _db.db.rawUpdate(
        '''
    UPDATE meetings SET recording_state = 'finished', duration_ms = ?,
      status = CASE WHEN status = 'recording' THEN 'recorded' ELSE status END
    WHERE id = ?
  ''',
        [duration.inMilliseconds, id],
      );

  /// (sent, total) chunk counts for upload progress.
  Future<(int, int)> chunkCounts(String meetingId) async {
    final rows = await chunkRows(meetingId);
    final sent = rows.where((r) => r['status'] == 'sent').length;
    return (sent, rows.length);
  }
}

/// Folds Arabic yeh/kaf to their Persian forms for text matching.
String foldPersianLetters(String s) =>
    s.replaceAll('ي', 'ی').replaceAll('ك', 'ک');
