import 'dart:io';
import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/platform/api_client.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';
import 'package:jalase_negar/features/upload/upload_queue.dart';

class FakeStore implements UploadStore {
  FakeStore(this.meetings, this.segmentMap, [Map<String, List<UploadChunk>>? c])
    : chunkMap = c ?? {};

  final List<Meeting> meetings;
  final Map<String, List<Segment>> segmentMap;
  final Map<String, List<UploadChunk>> chunkMap;

  @override
  Future<List<Meeting>> uploadableMeetings() async => [
    for (final m in meetings)
      if (m.sendText &&
          const [
            MeetingStatus.recording,
            MeetingStatus.recorded,
            MeetingStatus.transcribed,
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
  Future<List<Segment>> segments(String id) async => segmentMap[id] ?? [];

  @override
  Future<Meeting?> meeting(String id) async =>
      meetings.firstWhere((m) => m.id == id);

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

  @override
  Future<void> setSendText(String id, bool send) async {
    final i = meetings.indexWhere((m) => m.id == id);
    meetings[i] = meetings[i].copyWith(sendText: send);
  }
}

class FakeApi implements MeetingUploadApi {
  int createCalls = 0;
  int transcriptCalls = 0;
  int finishCalls = 0;
  final List<int> chunkSeqs = [];
  ApiException? chunkError;
  String sessionKind = 'text';
  String remoteStatus = 'processing';
  ApiException? transcriptError;
  ApiException? finishError;
  List<Segment>? sentSegments;
  String? sentIdentity;
  int? finishedChunks;

  @override
  Future<RemoteSession> createSession({
    required String clientMeetingId,
    required String title,
    required DateTime startedAt,
    required String appVersion,
  }) async {
    createCalls += 1;
    return RemoteSession(
      meetingId: 'remote-1',
      status: 'receiving',
      receivedSeqs: const [],
      inputKind: sessionKind,
    );
  }

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
    if (chunkError != null) throw chunkError!;
    chunkSeqs.add(seq);
  }

  @override
  Future<void> putTranscript({
    required String meetingId,
    required List<Segment> segments,
    String? asrIdentity,
  }) async {
    transcriptCalls += 1;
    if (transcriptError != null) throw transcriptError!;
    sentSegments = segments;
    sentIdentity = asrIdentity;
  }

  @override
  Future<RemoteStatus> status(String meetingId) async => RemoteStatus(
    status: remoteStatus,
    receivedSeqs: const [],
    progressPct: 50,
  );

  @override
  Future<void> finish({
    required String meetingId,
    required DateTime endedAt,
    required int totalChunks,
    required int durationMs,
  }) async {
    finishCalls += 1;
    if (finishError != null) throw finishError!;
    finishedChunks = totalChunks;
  }
}

void main() {
  late FakeApi api;
  late FakeStore store;

  Meeting meeting({
    MeetingStatus status = MeetingStatus.recorded,
    bool sendText = true,
    String? identity = 'live-model',
    String? remoteId,
  }) => Meeting(
    id: 'm1',
    title: 'جلسه',
    createdAt: DateTime(2026, 11, 1, 11),
    duration: const Duration(minutes: 2),
    audioPath: '/nowhere/full.wav',
    sampleRate: 16000,
    channels: 1,
    status: status,
    sendText: sendText,
    asrIdentity: identity,
    remoteMeetingId: remoteId,
  );

  const lines = [
    Segment(channel: 0, startMs: 0, endMs: 1000, text: 'سلام'),
    Segment(channel: 0, startMs: 1000, endMs: 2000, text: '   '),
    Segment(channel: 0, startMs: 2000, endMs: 3000, text: 'شروع کنیم'),
  ];

  UploadQueue queue() => UploadQueue(store: store, api: api, random: Random(1));

  late Directory dir;

  setUp(() => dir = Directory.systemTemp.createTempSync('uq'));
  tearDown(() => dir.deleteSync(recursive: true));

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

  void setUpStore(Meeting m, [List<Segment> segments = lines, int chunks = 0]) {
    api = FakeApi();
    store = FakeStore([m], {'m1': segments}, {'m1': makeChunks(chunks)});
  }

  test(
    'sends the text only when there is no audio, finishing with zero chunks',
    () async {
      setUpStore(meeting());
      final outcome = await queue().processOnce();
      expect(api.createCalls, 1);
      expect(api.transcriptCalls, 1);
      expect(api.sentSegments!.map((s) => s.text), ['سلام', 'شروع کنیم']);
      expect(api.sentIdentity, 'live-model');
      expect(api.finishCalls, 1);
      expect(api.finishedChunks, 0);
      expect(store.meetings.single.status, MeetingStatus.processing);
      expect(store.meetings.single.remoteMeetingId, 'remote-1');
      expect(outcome.nextWake, isNotNull);
    },
  );

  test(
    'sends the text and the audio chunks, then finishes with their count',
    () async {
      setUpStore(meeting(), lines, 3);
      await queue().processOnce();
      expect(api.transcriptCalls, 1);
      expect(api.chunkSeqs..sort(), [0, 1, 2]);
      expect(api.finishedChunks, 3);
      expect(store.meetings.single.status, MeetingStatus.processing);
      expect(
        File('${dir.path}/0.wav').existsSync(),
        isFalse,
        reason: 'chunk copies are removed once the server has them',
      );
    },
  );

  test('audio uploads while recording, the text waits for the end', () async {
    setUpStore(meeting(status: MeetingStatus.recording), const [], 2);
    store.meetings[0] = Meeting(
      id: 'm1',
      title: 'جلسه',
      createdAt: DateTime(2026, 11, 1, 11),
      duration: Duration.zero,
      audioPath: '/nowhere/full.wav',
      sampleRate: 16000,
      channels: 1,
      status: MeetingStatus.recording,
      recordingState: 'recording',
    );
    await queue().processOnce();
    expect(api.chunkSeqs..sort(), [0, 1]);
    expect(api.transcriptCalls, 0);
    expect(api.finishCalls, 0);
  });

  test('an audio chunk the server refuses never blocks the text', () async {
    setUpStore(meeting(), lines, 2);
    api.chunkError = const ApiException(
      message: 'فرمت',
      code: 'meeting_chunk_invalid_audio',
      statusCode: 422,
    );
    await queue().processOnce();
    expect(api.finishedChunks, 0);
    expect(store.meetings.single.status, MeetingStatus.processing);
  });

  test('a meeting with the switch off is never touched', () async {
    setUpStore(meeting(sendText: false));
    await queue().processOnce();
    expect(api.createCalls, 0);
    expect(api.transcriptCalls, 0);
  });

  test(
    'no transcript: nothing is sent and the user gets a next step',
    () async {
      setUpStore(meeting(), const []);
      final outcome = await queue().processOnce();
      expect(api.createCalls, 0);
      expect(store.meetings.single.sendText, isFalse);
      expect(outcome.lastError, contains('رونویسی زنده'));
    },
  );

  test(
    'transcript without an ASR identity counts as not transcribed',
    () async {
      setUpStore(meeting(identity: null));
      await queue().processOnce();
      expect(api.createCalls, 0);
      expect(store.meetings.single.sendText, isFalse);
    },
  );

  test('a session an old app opened as audio is not reused', () async {
    setUpStore(meeting());
    api.sessionKind = 'audio';
    await queue().processOnce();
    expect(api.transcriptCalls, 0);
    expect(store.meetings.single.status, MeetingStatus.failed);
    expect(store.meetings.single.error, contains('نسخه‌ی قدیمی'));
  });

  test('a network error keeps the meeting for the next pass', () async {
    setUpStore(meeting());
    api.transcriptError = const ApiException(message: 'قطع');
    final outcome = await queue().processOnce();
    expect(store.meetings.single.status, MeetingStatus.uploading);
    expect(outcome.nextWake, isNotNull);
    api.transcriptError = null;
    await queue().processOnce();
    expect(api.createCalls, 1, reason: 'the remote id is reused');
    expect(store.meetings.single.status, MeetingStatus.processing);
  });

  test('a refusal is final: the meeting fails instead of looping', () async {
    setUpStore(meeting());
    api.transcriptError = const ApiException(
      message: 'متن نامعتبر',
      code: 'meeting_transcript_invalid',
      statusCode: 422,
    );
    await queue().processOnce();
    expect(store.meetings.single.status, MeetingStatus.failed);
    expect(store.meetings.single.error, 'متن نامعتبر');
  });

  test('a finish the server already holds counts as done', () async {
    setUpStore(meeting());
    api.finishError = const ApiException(
      message: 'بسته',
      code: 'meeting_closed',
      statusCode: 409,
    );
    await queue().processOnce();
    expect(store.meetings.single.status, MeetingStatus.processing);
  });

  test('revoked token stops the pass and asks to reconnect', () async {
    setUpStore(meeting());
    api.transcriptError = const ApiException(
      message: 'توکن',
      statusCode: 401,
      requiresReconnect: true,
    );
    final outcome = await queue().processOnce();
    expect(outcome.needsReconnect, isTrue);
  });

  test('exhausted credit is reported without failing the meeting', () async {
    setUpStore(meeting());
    api.transcriptError = const ApiException(
      message: 'اعتبار',
      statusCode: 402,
    );
    final outcome = await queue().processOnce();
    expect(outcome.creditExhausted, isTrue);
    expect(store.meetings.single.status, MeetingStatus.uploading);
  });

  test('processing meetings follow the server until complete', () async {
    setUpStore(meeting(status: MeetingStatus.processing, remoteId: 'remote-1'));
    var outcome = await queue().processOnce();
    expect(store.meetings.single.status, MeetingStatus.processing);
    expect(outcome.nextWake, const Duration(seconds: 20));
    api.remoteStatus = 'complete';
    await queue().processOnce();
    expect(store.meetings.single.status, MeetingStatus.complete);
    expect(api.transcriptCalls, 0);
  });

  test('a failed server run marks the meeting failed', () async {
    setUpStore(meeting(status: MeetingStatus.processing, remoteId: 'remote-1'));
    api.remoteStatus = 'failed_terminal';
    await queue().processOnce();
    expect(store.meetings.single.status, MeetingStatus.failed);
  });

  test('backoff grows and is capped', () {
    final r = Random(1);
    expect(uploadBackoff(1, r).inSeconds, lessThan(10));
    expect(uploadBackoff(20, r).inSeconds, lessThanOrEqualTo(375));
  });
}
