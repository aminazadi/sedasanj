import 'dart:async';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/features/people/data/enrollment_quality.dart';
import 'package:jalase_negar/features/people/data/enrollment_session.dart';

import 'people_test_support.dart';

class FakeRecorder implements EnrollmentRecorder {
  bool grant = true;
  final controller = StreamController<double>.broadcast();

  @override
  Stream<double> get levels => controller.stream;

  @override
  Future<bool> start() async => grant;

  @override
  Future<Float32List> stop() async => Float32List(16000);

  @override
  Future<void> dispose() async => controller.close();
}

class FakeEmbedder implements VoiceEmbeddingService {
  Float32List? result = vec([1, 0, 0]);

  @override
  String get modelId => 'campplus';

  @override
  String get modelVersion => '1';

  @override
  Future<Float32List?> embed(Float32List samples) async => result;
}

const _good = EnrollmentAssessment(
  issue: EnrollmentIssue.ok,
  speechMs: 15000,
  snrDb: 25,
  clippedShare: 0,
);
const _short = EnrollmentAssessment(
  issue: EnrollmentIssue.tooShort,
  speechMs: 2000,
  snrDb: 25,
  clippedShare: 0,
);

void main() {
  const prompts = SpeakerPrompts(
    version: 'v',
    prompts: [
      SpeakerPrompt(id: 'p1', text: 'a', required: true, near: true),
      SpeakerPrompt(id: 'p2', text: 'b', required: true, near: false),
      SpeakerPrompt(id: 'p3', text: 'c', required: false, near: true),
    ],
  );

  test('parses the bundled prompts file shape', () {
    final p = SpeakerPrompts.parse(
      '{"version":"1","prompts":[{"id":"x","text":"t","required":true,"distance":"far"}]}',
    );
    expect(p.prompts.single.near, isFalse);
    expect(p.requiredCount, 1);
  });

  test(
    'accepted recordings are stored one by one; refused ones are not',
    () async {
      final (db, _) = await openTestDb();
      final repo = repoFor(db);
      final person = await repo.create(name: 'علی');
      final recorder = FakeRecorder();
      final embedder = FakeEmbedder();
      var quality = _short;
      final session = EnrollmentSession(
        personId: person.clientId,
        prompts: prompts,
        recorder: recorder,
        embedder: embedder,
        repository: repo,
        assess: (_) => quality,
      );

      await session.start();
      expect(session.state.value.phase, EnrollmentPhase.recording);
      expect(await session.stop(), isFalse);
      expect(session.state.value.message, isNotEmpty);
      expect(await repo.voiceprints(person.clientId), isEmpty);
      expect(session.canFinish, isFalse);

      quality = _good;
      await session.start();
      expect(await session.stop(), isTrue);
      expect(session.state.value.index, 1);
      await session.start();
      expect(await session.stop(), isTrue);
      expect(await repo.voiceprints(person.clientId), hasLength(2));
      expect(session.canFinish, isTrue);
      expect(await repo.pendingCount(), greaterThan(0));
      await session.dispose();
    },
  );

  test('a missing embedding refuses the sample and tells what to do', () async {
    final (db, _) = await openTestDb();
    final repo = repoFor(db);
    final person = await repo.create(name: 'سارا');
    final embedder = FakeEmbedder()..result = null;
    final session = EnrollmentSession(
      personId: person.clientId,
      prompts: prompts,
      recorder: FakeRecorder(),
      embedder: embedder,
      repository: repo,
      assess: (_) => _good,
    );
    await session.start();
    expect(await session.stop(), isFalse);
    expect(session.state.value.message, contains('مدل'));
    expect(await repo.voiceprints(person.clientId), isEmpty);
    await session.dispose();
  });

  test('denied microphone permission is reported', () async {
    final (db, _) = await openTestDb();
    final repo = repoFor(db);
    final person = await repo.create(name: 'x');
    final recorder = FakeRecorder()..grant = false;
    final session = EnrollmentSession(
      personId: person.clientId,
      prompts: prompts,
      recorder: recorder,
      embedder: FakeEmbedder(),
      repository: repo,
    );
    await session.start();
    expect(session.state.value.permissionDenied, isTrue);
    expect(session.state.value.phase, EnrollmentPhase.idle);
    await session.dispose();
  });
}
