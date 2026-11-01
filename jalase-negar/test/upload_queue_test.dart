import 'dart:io';
import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/platform/api_client.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';
import 'package:jalase_negar/features/upload/upload_queue.dart';

class FakeStore implements UploadStore {
  FakeStore(this.meetings, this.chunkMap);

  final List<Meeting> meetings;
  final Map<String, List<UploadChunk>> chunkMap;

  Meeting _m(String id) => meetings.firstWhere((m) => m.id == id);

  @override
  Future<List<Meeting>> uploadableMeetings() async => [
    for (final m in meetings)
      if (const [
        MeetingStatus.recording,
        MeetingStatus.recorded,
        MeetingStatus.uploading,
        MeetingStatus.processing,
      ].contains(m.status))
        m,
  ];

  @override
  Future<List<UploadChunk>> chunks(String id) async => chunkMap[id] ?? [];

  @override
  Future<void> updateChunk(
    String meetingId,
    int seq, {
    String? status,
    int? attempts,
    int? nextAttemptAt,
    String? lastError,
    String? sha256,
  }) async {
    final list = chunkMap[meetingId]!;
    final i = list.indexWhere((c) => c.seq == seq);
    final c = list[i];
    list[i] = UploadChunk(
      seq: c.seq,
      path: c.path,
      startMs: c.startMs,
      endMs: c.endMs,
      status: status ?? c.status,
      attempts: attempts ?? c.attempts,
      sha256: sha256 ?? c.sha256,
      nextAttemptAt: nextAttemptAt ?? c.nextAttemptAt,
    );
  }

  @override
  Future<Meeting?> meeting(String id) async => _m(id);

  @override
  Future<void> setRemoteMeetingId(String id, String remoteId) async {
    final i = meetings.indexWhere((m) => m.id == id);
    meetings[i] = meetings[i].copyWith(remoteMeetingId: remoteId);
  }

  @override
  Future<void> setStatus(
    String id,
    MeetingStatus status, {
    String? error,
  }) async {
    final i = meetings.indexWhere((m) => m.id == id);
    meetings[i] = meetings[i].copyWith(status: status, error: error);
  }
}

class FakeApi implements MeetingUploadApi {
  List<int> received = [];
  final List<ApiException> putErrors = [];
  ApiException? finishError;
  String remoteStatus = 'receiving';
  bool statusNotFound = false;
  final sent = <int>[];
  int finishCalls = 0;
  int? finishedTotal;

  @override
  Future<RemoteSession> createSession({
    required String clientMeetingId,
    required String title,
    required DateTime startedAt,
    required String appVersion,
  }) async => RemoteSession(
    meetingId: 'remote-1',
    status: 'receiving',
    receivedSeqs: received,
  );

  @override
  Future<void> putChunk({
    required String meetingId,
    required int seq,
    required String filePath,
    required int startMs,
    required int endMs,
    required String sha256,
    String? deviceText,
  }) async {
    if (putErrors.isNotEmpty) throw putErrors.removeAt(0);
    expect(sha256.length, 64);
    sent.add(seq);
  }

  @override
  Future<RemoteStatus> status(String meetingId) async {
    if (statusNotFound) {
      throw const ApiException(message: 'gone', statusCode: 404);
    }
    return RemoteStatus(
      status: remoteStatus,
      receivedSeqs: sent,
      progressPct: 50,
    );
  }

  @override
  Future<void> finish({
    required String meetingId,
    required DateTime endedAt,
    required int totalChunks,
    required int durationMs,
  }) async {
    finishCalls += 1;
    if (finishError != null) throw finishError!;
    finishedTotal = totalChunks;
  }
}

void main() {
  late Directory dir;
  late FakeApi api;
  late FakeStore store;
  var clock = DateTime(2026, 11, 1, 12);

  Meeting meeting({String recordingState = 'finished'}) => Meeting(
    id: 'm1',
    title: 'جلسه',
    createdAt: DateTime(2026, 11, 1, 11),
    duration: const Duration(minutes: 2),
    audioPath: '${dir.path}/full.wav',
    sampleRate: 16000,
    channels: 1,
    status: recordingState == 'recording'
        ? MeetingStatus.recording
        : MeetingStatus.recorded,
    recordingState: recordingState,
  );

  List<UploadChunk> makeChunks(int n) => [
    for (var i = 0; i < n; i++)
      () {
        final f = File('${dir.path}/$i.wav')..writeAsBytesSync([1, 2, 3, i]);
        return UploadChunk(
          seq: i,
          path: f.path,
          startMs: i * 1000,
          endMs: (i + 1) * 1000,
          status: 'pending',
          attempts: 0,
        );
      }(),
  ];

  UploadQueue queue() =>
      UploadQueue(store: store, api: api, random: Random(1), now: () => clock);

  setUp(() {
    dir = Directory.systemTemp.createTempSync('upload');
    api = FakeApi();
    clock = DateTime(2026, 11, 1, 12);
  });
  tearDown(() => dir.deleteSync(recursive: true));

  test(
    'uploads all chunks, finishes and cleans up local chunk files',
    () async {
      store = FakeStore([meeting()], {'m1': makeChunks(3)});
      final outcome = await queue().processOnce();
      expect(api.sent..sort(), [0, 1, 2]);
      expect(api.finishedTotal, 3);
      expect(store.meetings.single.status, MeetingStatus.processing);
      expect(store.meetings.single.remoteMeetingId, 'remote-1');
      expect(File('${dir.path}/0.wav').existsSync(), isFalse);
      expect(outcome.needsReconnect, isFalse);
    },
  );

  test('does not finish while the meeting is still recording', () async {
    store = FakeStore(
      [meeting(recordingState: 'recording')],
      {'m1': makeChunks(2)},
    );
    await queue().processOnce();
    expect(api.sent.length, 2);
    expect(api.finishCalls, 0);
    expect(store.meetings.single.status, MeetingStatus.recording);
  });

  test('skips chunks the server already has after a resume', () async {
    api.received = [0, 1];
    store = FakeStore([meeting()], {'m1': makeChunks(3)});
    await queue().processOnce();
    expect(api.sent, [2]);
    expect(api.finishedTotal, 3);
  });

  test('retries a failed chunk after the backoff delay', () async {
    api.putErrors.add(const ApiException(message: 'server', statusCode: 503));
    store = FakeStore([meeting()], {'m1': makeChunks(1)});
    final first = await queue().processOnce();
    expect(store.chunkMap['m1']!.single.status, 'pending');
    expect(store.chunkMap['m1']!.single.attempts, 1);
    expect(first.nextWake, isNotNull);
    expect(api.finishCalls, 0);

    // Too early: nothing is sent yet.
    await queue().processOnce();
    expect(api.sent, isEmpty);

    clock = clock.add(const Duration(minutes: 10));
    await queue().processOnce();
    expect(api.sent, [0]);
    expect(api.finishCalls, 1);
  });

  test('stops and asks to reconnect on 401', () async {
    api.putErrors.add(
      const ApiException(
        message: 'revoked',
        statusCode: 401,
        requiresReconnect: true,
      ),
    );
    store = FakeStore([meeting()], {'m1': makeChunks(2)});
    final outcome = await queue().processOnce();
    expect(outcome.needsReconnect, isTrue);
    expect(api.finishCalls, 0);
  });

  test('reports exhausted credit on 402 without losing chunks', () async {
    api.putErrors.add(const ApiException(message: 'credit', statusCode: 402));
    store = FakeStore([meeting()], {'m1': makeChunks(1)});
    final outcome = await queue().processOnce();
    expect(outcome.creditExhausted, isTrue);
    expect(store.chunkMap['m1']!.single.status, 'pending');
  });

  test('re-sends chunks the server reports missing at finish', () async {
    api.finishError = const ApiException(
      message: 'missing',
      statusCode: 409,
      code: 'meeting_incomplete_chunks',
      missingSeqs: [1],
    );
    store = FakeStore([meeting()], {'m1': makeChunks(2)});
    await queue().processOnce();
    expect(store.chunkMap['m1']![1].status, 'pending');
    expect(store.meetings.single.status, isNot(MeetingStatus.processing));
    api.finishError = null;
    await queue().processOnce();
    expect(api.finishedTotal, 2);
  });

  test('follows server processing to completion', () async {
    final m = meeting().copyWith(
      status: MeetingStatus.processing,
      remoteMeetingId: 'remote-1',
    );
    store = FakeStore([m], {'m1': makeChunks(1)});
    api.remoteStatus = 'processing';
    final waiting = await queue().processOnce();
    expect(waiting.nextWake, const Duration(seconds: 20));
    api.remoteStatus = 'complete';
    await queue().processOnce();
    expect(store.meetings.single.status, MeetingStatus.complete);
  });

  test('marks a meeting failed when the server no longer has it', () async {
    final m = meeting().copyWith(
      status: MeetingStatus.processing,
      remoteMeetingId: 'remote-1',
    );
    store = FakeStore([m], {'m1': makeChunks(1)});
    api.statusNotFound = true;
    await queue().processOnce();
    expect(store.meetings.single.status, MeetingStatus.failed);
  });
}
