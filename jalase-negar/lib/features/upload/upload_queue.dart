import 'dart:io';
import 'dart:math';

import 'package:crypto/crypto.dart';

import '../../core/platform/api_client.dart';
import '../meetings/data/meeting.dart';

/// A closed WAV chunk waiting for (or already past) upload.
class UploadChunk {
  const UploadChunk({
    required this.seq,
    required this.path,
    required this.startMs,
    required this.endMs,
    required this.status,
    required this.attempts,
    this.sha256,
    this.nextAttemptAt,
    this.deviceText,
  });

  final int seq;
  final String path;
  final int startMs;
  final int endMs;

  /// `pending`, `sent` or `failed` (terminal: the server rejected the chunk).
  final String status;
  final int attempts;
  final String? sha256;

  /// Epoch milliseconds before which the chunk is not retried.
  final int? nextAttemptAt;
  final String? deviceText;
}

/// Persistence the queue needs; implemented by the meeting repository.
abstract class UploadStore {
  Future<List<Meeting>> uploadableMeetings();
  Future<List<UploadChunk>> chunks(String meetingId);
  Future<void> updateChunk(
    String meetingId,
    int seq, {
    String? status,
    int? attempts,
    int? nextAttemptAt,
    String? lastError,
    String? sha256,
  });
  Future<Meeting?> meeting(String id);

  /// Targeted writes: the recorder updates the same row while a meeting is
  /// still being captured, so the queue must never rewrite whole rows.
  Future<void> setRemoteMeetingId(String id, String remoteId);
  Future<void> setStatus(String id, MeetingStatus status, {String? error});
}

/// What a pass of the queue learned; the controller turns it into UI state
/// and the next wake-up.
class UploadOutcome {
  const UploadOutcome({
    this.needsReconnect = false,
    this.creditExhausted = false,
    this.nextWake,
    this.lastError,
  });

  final bool needsReconnect;
  final bool creditExhausted;
  final Duration? nextWake;
  final String? lastError;
}

Duration uploadBackoff(int attempts, Random random) {
  final base = min(300, 2 * pow(2, attempts.clamp(0, 10)).toInt());
  return Duration(
    milliseconds: (base * 1000 * (1 + random.nextDouble() * 0.25)).round(),
  );
}

/// Uploads meeting chunks to SedaSanj while the meeting is still recording,
/// finishes the session once the last chunk is in, and follows server-side
/// processing. Every step is driven by the stored state, so a killed app or a
/// lost connection simply resumes on the next pass.
class UploadQueue {
  UploadQueue({
    required this.store,
    required this.api,
    this.appVersion = '2.0.0',
    this.concurrency = 2,
    Random? random,
    DateTime Function()? now,
  }) : _random = random ?? Random(),
       _now = now ?? DateTime.now;

  final UploadStore store;
  final MeetingUploadApi api;
  final String appVersion;
  final int concurrency;
  final Random _random;
  final DateTime Function() _now;

  Future<UploadOutcome> processOnce() async {
    var needsReconnect = false;
    var creditExhausted = false;
    Duration? wake;
    String? lastError;

    void wakeIn(Duration d) {
      if (wake == null || d < wake!) wake = d;
    }

    for (final meeting in await store.uploadableMeetings()) {
      try {
        final result = await _processMeeting(meeting, wakeIn);
        if (result != null) lastError = result;
      } on ApiException catch (e) {
        if (e.requiresReconnect) {
          needsReconnect = true;
          lastError = e.message;
          break;
        }
        if (e.statusCode == 402) {
          creditExhausted = true;
          lastError = e.message;
          continue;
        }
        lastError = e.message;
        if (e.retryable) wakeIn(uploadBackoff(1, _random));
      }
    }
    return UploadOutcome(
      needsReconnect: needsReconnect,
      creditExhausted: creditExhausted,
      nextWake: wake,
      lastError: lastError,
    );
  }

  /// Returns a user-facing problem text, or null when the pass went fine.
  Future<String?> _processMeeting(
    Meeting meeting,
    void Function(Duration) wakeIn,
  ) async {
    final live = meeting.recordingState == 'recording';
    var chunks = await store.chunks(meeting.id);
    if (chunks.isEmpty && live) return null;

    var current = meeting;
    if (current.remoteMeetingId == null) {
      if (chunks.isEmpty) return null;
      final session = await api.createSession(
        clientMeetingId: current.id,
        title: current.title,
        startedAt: current.createdAt,
        appVersion: appVersion,
      );
      current = current.copyWith(remoteMeetingId: session.meetingId);
      await store.setRemoteMeetingId(current.id, session.meetingId);
      for (final chunk in chunks) {
        if (session.receivedSeqs.contains(chunk.seq) &&
            chunk.status != 'sent') {
          await store.updateChunk(current.id, chunk.seq, status: 'sent');
        }
      }
      chunks = await store.chunks(current.id);
    }
    final remoteId = current.remoteMeetingId!;

    if (current.status == MeetingStatus.processing) {
      return _followProcessing(current, remoteId, wakeIn);
    }

    final nowMs = _now().millisecondsSinceEpoch;
    final due = [
      for (final c in chunks)
        if (c.status == 'pending' && (c.nextAttemptAt ?? 0) <= nowMs) c,
    ];
    for (final c in chunks) {
      if (c.status == 'pending' && (c.nextAttemptAt ?? 0) > nowMs) {
        wakeIn(Duration(milliseconds: c.nextAttemptAt! - nowMs));
      }
    }

    if (due.isNotEmpty && !live && current.status != MeetingStatus.uploading) {
      current = current.copyWith(status: MeetingStatus.uploading);
      await store.setStatus(current.id, MeetingStatus.uploading);
    }

    String? problem;
    ApiException? fatal;
    for (var i = 0; i < due.length; i += concurrency) {
      final batch = due.skip(i).take(concurrency);
      final results = await Future.wait(
        batch.map((c) => _uploadChunk(current, remoteId, c, wakeIn)),
      );
      for (final r in results) {
        if (r == null) continue;
        problem = r.message;
        if (r.requiresReconnect || r.statusCode == 402) fatal = r;
      }
      if (fatal != null) throw fatal;
    }

    chunks = await store.chunks(current.id);
    final allSent =
        chunks.isNotEmpty && chunks.every((c) => c.status == 'sent');
    if (!live && allSent) {
      await _finish(current, remoteId, chunks);
    }
    return problem;
  }

  /// Uploads one chunk. Returns the error for the caller to react to, or null.
  Future<ApiException?> _uploadChunk(
    Meeting meeting,
    String remoteId,
    UploadChunk chunk,
    void Function(Duration) wakeIn,
  ) async {
    try {
      final file = File(chunk.path);
      if (!await file.exists()) {
        await store.updateChunk(
          meeting.id,
          chunk.seq,
          status: 'failed',
          lastError: 'chunk_file_missing',
        );
        return const ApiException(
          message: 'فایل یکی از تکه‌های صدا روی گوشی پیدا نشد.',
        );
      }
      final digest =
          chunk.sha256 ?? (await sha256.bind(file.openRead()).first).toString();
      if (chunk.sha256 == null) {
        await store.updateChunk(meeting.id, chunk.seq, sha256: digest);
      }
      await api.putChunk(
        meetingId: remoteId,
        seq: chunk.seq,
        filePath: chunk.path,
        startMs: chunk.startMs,
        endMs: chunk.endMs,
        sha256: digest,
        deviceText: chunk.deviceText,
      );
      await store.updateChunk(meeting.id, chunk.seq, status: 'sent');
      return null;
    } on ApiException catch (e) {
      if (e.requiresReconnect || e.statusCode == 402) return e;
      if (e.code == 'meeting_chunk_conflict') {
        // The server already holds different audio for this seq; resync
        // instead of looping.
        final remote = await api.status(remoteId);
        await store.updateChunk(
          meeting.id,
          chunk.seq,
          status: remote.receivedSeqs.contains(chunk.seq) ? 'sent' : 'failed',
          lastError: e.code,
        );
        return null;
      }
      if (e.retryable) {
        final delay = uploadBackoff(chunk.attempts + 1, _random);
        await store.updateChunk(
          meeting.id,
          chunk.seq,
          attempts: chunk.attempts + 1,
          nextAttemptAt: _now().add(delay).millisecondsSinceEpoch,
          lastError: e.code ?? 'http_${e.statusCode ?? 'network'}',
        );
        wakeIn(delay);
        return e;
      }
      await store.updateChunk(
        meeting.id,
        chunk.seq,
        status: 'failed',
        lastError: e.code ?? 'http_${e.statusCode}',
      );
      return e;
    }
  }

  Future<void> _finish(
    Meeting meeting,
    String remoteId,
    List<UploadChunk> chunks,
  ) async {
    final total = chunks.map((c) => c.seq).reduce(max) + 1;
    try {
      await api.finish(
        meetingId: remoteId,
        endedAt: meeting.createdAt.add(meeting.duration),
        totalChunks: total,
        durationMs: meeting.duration.inMilliseconds,
      );
    } on ApiException catch (e) {
      if (e.code == 'meeting_incomplete_chunks') {
        // The server lost track of some chunks: send them again.
        for (final seq in e.missingSeqs) {
          await store.updateChunk(
            meeting.id,
            seq,
            status: 'pending',
            attempts: 0,
            nextAttemptAt: 0,
          );
        }
        return;
      }
      rethrow;
    }
    await store.setStatus(meeting.id, MeetingStatus.processing);
    // The server has everything; the chunk copies only cost disk space.
    for (final c in chunks) {
      final file = File(c.path);
      if (await file.exists()) await file.delete();
    }
  }

  Future<String?> _followProcessing(
    Meeting meeting,
    String remoteId,
    void Function(Duration) wakeIn,
  ) async {
    final RemoteStatus remote;
    try {
      remote = await api.status(remoteId);
    } on ApiException catch (e) {
      if (e.statusCode != 404) rethrow;
      // Deleted on the server (e.g. from the panel): stop polling it.
      await store.setStatus(
        meeting.id,
        MeetingStatus.failed,
        error: 'این جلسه در صداسنج پیدا نشد؛ احتمالاً از پنل حذف شده است.',
      );
      return null;
    }
    if (remote.isComplete) {
      await store.setStatus(meeting.id, MeetingStatus.complete);
    } else if (remote.isFailed) {
      await store.setStatus(
        meeting.id,
        MeetingStatus.failed,
        error:
            'پردازش جلسه در صداسنج ناموفق بود؛ در پنل صداسنج «تلاش مجدد» را بزنید.',
      );
    } else {
      wakeIn(const Duration(seconds: 20));
    }
    return null;
  }
}
