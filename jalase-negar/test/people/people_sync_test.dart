import 'dart:io';
import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/platform/api_client.dart';
import 'package:jalase_negar/core/platform/speaker_api.dart';
import 'package:jalase_negar/core/speaker/speaker_math.dart';
import 'package:jalase_negar/features/people/data/embedding_cipher.dart';
import 'package:jalase_negar/features/people/data/people_repository.dart';
import 'package:jalase_negar/features/people/data/person.dart';
import 'package:jalase_negar/features/people/sync/sync_engine.dart';

import 'people_test_support.dart';

void main() {
  late FakeSpeakerServer server;
  late Directory dir;
  var clock = DateTime(2026, 11, 5, 12);

  setUp(() {
    server = FakeSpeakerServer();
    clock = DateTime(2026, 11, 5, 12);
  });
  tearDown(() {
    if (dir.existsSync()) dir.deleteSync(recursive: true);
  });

  SyncEngine engine(PeopleRepository repo) => SyncEngine(
    repository: repo,
    api: server,
    random: Random(1),
    now: () => clock,
  );

  Future<PeopleRepository> open() async {
    final (db, d) = await openTestDb();
    dir = d;
    return repoFor(db);
  }

  test('a person made offline is pushed once the phone is online', () async {
    final repo = await open();
    final ali = await repo.create(
      name: 'علی',
      consentAt: DateTime.utc(2026, 11, 5),
      consentVersion: kSpeakerConsentVersion,
    );
    await repo.addVoiceprints(ali.clientId, [
      voiceprint('s1', ali.clientId, [1, 0, 0, 0]),
      voiceprint('s2', ali.clientId, [0.9, 0.1, 0, 0]),
    ]);
    expect(await repo.pendingCount(), 1, reason: 'one entry per person');

    final outcome = await engine(repo).syncOnce();

    expect(outcome.ok, isTrue);
    expect(outcome.pushed, 1);
    expect(await repo.pendingCount(), 0);
    final stored = (await repo.person(ali.clientId))!;
    expect(stored.version, 1);
    expect(stored.changeSeq, greaterThan(0));
    expect(server.profiles[ali.clientId]!.voiceprints, hasLength(2));
    expect(server.received.single.baseVersion, 0);
    expect((await repo.voiceprints(ali.clientId)).every((v) => v.synced), isTrue);
  });

  test('the outbox survives the app being killed', () async {
    final (db1, d) = await openTestDb();
    dir = d;
    final cipher = AesGcmEmbeddingCipher.random();
    final repo1 = repoFor(db1, cipher);
    final sara = await repo1.create(name: 'سارا');
    await db1.db.close();

    final (db2, _) = await openTestDb(d);
    final repo2 = repoFor(db2, cipher);
    expect(await repo2.pendingCount(), 1);
    await engine(repo2).syncOnce();
    expect(server.profiles.containsKey(sara.clientId), isTrue);
    expect(await repo2.pendingCount(), 0);
  });

  test('a failed push backs off and the retry sends it', () async {
    final repo = await open();
    await repo.create(name: 'علی');
    server.failPut = const ApiException(message: 'قطع');
    final failed = await engine(repo).syncOnce();
    expect(failed.lastError, isNotNull);
    expect(failed.nextWake, isNotNull);
    expect(await repo.pendingCount(), 1);

    // Not due yet: nothing is sent until the backoff passed.
    server.failPut = null;
    final calls = server.putCalls;
    final early = await engine(repo).syncOnce();
    expect(server.putCalls, calls);
    expect(early.nextWake, isNotNull);

    clock = clock.add(const Duration(minutes: 10));
    final later = await engine(repo).syncOnce();
    expect(later.pushed, 1);
    expect(await repo.pendingCount(), 0);
  });

  test('only new samples are pushed, and removals are reported', () async {
    final repo = await open();
    final p = await repo.create(
      name: 'علی',
      consentAt: DateTime.utc(2026, 11, 5),
      consentVersion: kSpeakerConsentVersion,
    );
    await repo.addVoiceprints(p.clientId, [
      voiceprint('s1', p.clientId, [1, 0, 0, 0]),
    ]);
    await engine(repo).syncOnce();

    await repo.addVoiceprints(p.clientId, [
      voiceprint('s2', p.clientId, [0, 1, 0, 0]),
    ]);
    await repo.removeVoiceprint(p.clientId, 's1');
    await engine(repo).syncOnce();

    final second = server.received.last;
    expect(second.baseVersion, 1);
    expect([for (final v in second.voiceprints) v.clientId], ['s2']);
    expect(second.removeVoiceprints, ['s1']);
    expect(
      server.profiles[p.clientId]!.voiceprints.map((v) => v.clientId),
      ['s2'],
    );
  });

  test('a sample removed before it ever synced needs no request', () async {
    final repo = await open();
    final p = await repo.create(name: 'علی');
    await repo.addVoiceprints(p.clientId, [
      voiceprint('s1', p.clientId, [1, 0, 0, 0]),
    ]);
    await repo.removeVoiceprint(p.clientId, 's1');
    final entry = (await repo.outbox()).single;
    expect(entry.removedVoiceprints, isEmpty);
  });

  test('a new phone gets everyone back, voiceprints included', () async {
    server.addExisting('11111111-1111-4111-8111-111111111111', 'مریم', [
      remoteVoiceprint('a1', [0, 0, 1, 0]),
    ]);
    server.addExisting('22222222-2222-4222-8222-222222222222', 'رضا', [
      remoteVoiceprint('b1', [0, 0, 0, 1]),
    ], mine: false);
    final repo = await open();

    final outcome = await engine(repo).syncOnce();

    expect(outcome.pulled, 2);
    final people = await repo.people();
    expect(people.map((p) => p.name).toSet(), {'مریم', 'رضا'});
    expect(people.firstWhere((p) => p.name == 'رضا').mine, isFalse);
    final voices = await repo.enrolledVoices(
      modelId: 'campplus',
      modelVersion: '1',
    );
    expect(voices, hasLength(2));
    expect(
      cosine(
        voices.firstWhere((v) => v.name == 'مریم').centroid,
        vec([0, 0, 1, 0]),
      ),
      closeTo(1, 1e-6),
    );
    expect(await repo.cursor(), server.seq);
  });

  test('pulls page by page and keeps the cursor of the last stored page', () async {
    for (var i = 0; i < 5; i++) {
      server.addExisting('00000000-0000-4000-8000-00000000000$i', 'نفر $i', [
        remoteVoiceprint('v$i', [1, 0, 0, 0]),
      ]);
    }
    final repo = await open();
    final paged = SyncEngine(
      repository: repo,
      api: server,
      pageSize: 2,
      random: Random(1),
      now: () => clock,
    );
    expect((await paged.syncOnce()).pulled, 5);
    expect(server.changeCalls, 3);
    final again = await paged.syncOnce();
    expect(again.pulled, 0, reason: 'nothing changed after the cursor');
  });

  test('a conflict is merged: the local edit lands on the server version', () async {
    final repo = await open();
    final p = await repo.create(
      name: 'علی',
      consentAt: DateTime.utc(2026, 11, 5),
      consentVersion: kSpeakerConsentVersion,
    );
    await engine(repo).syncOnce();
    // Another phone adds a sample, this phone renames offline.
    server.profiles[p.clientId] = RemoteProfile(
      clientId: p.clientId,
      displayName: 'علی',
      visibility: 'private',
      version: 5,
      changeSeq: ++server.seq,
      deleted: false,
      mine: true,
      voiceprints: [remoteVoiceprint('other', [0, 1, 0, 0])],
    );
    await repo.update(p.clientId, name: 'علی‌اکبر');

    final outcome = await engine(repo).syncOnce();

    expect(outcome.ok, isTrue);
    expect(server.profiles[p.clientId]!.displayName, 'علی‌اکبر');
    expect(server.profiles[p.clientId]!.version, 6);
    expect(
      (await repo.voiceprints(p.clientId)).map((v) => v.clientId),
      contains('other'),
      reason: 'the other phone\'s sample is kept',
    );
    expect(await repo.pendingCount(), 0);
  });

  test('a person deleted elsewhere beats a local edit', () async {
    final repo = await open();
    final p = await repo.create(name: 'علی');
    await engine(repo).syncOnce();
    server.deleteElsewhere(p.clientId);
    await repo.update(p.clientId, name: 'علی دو');

    await engine(repo).syncOnce();

    expect(await repo.person(p.clientId), isNull);
    expect(await repo.pendingCount(), 0);
  });

  test('a pull never overwrites a name that is waiting to be pushed', () async {
    final repo = await open();
    final p = await repo.create(name: 'علی');
    await engine(repo).syncOnce();
    server.editElsewhere(p.clientId, name: 'علی (دسکتاپ)');
    await repo.update(p.clientId, name: 'علی محلی');

    server.failPut = const ApiException(message: 'قطع');
    await engine(repo).syncOnce();
    expect((await repo.person(p.clientId))!.name, 'علی محلی');
  });

  test('deleting reaches the server and other phones see a tombstone', () async {
    final repo = await open();
    final p = await repo.create(name: 'علی');
    await engine(repo).syncOnce();

    await repo.delete(p.clientId);
    expect(await repo.person(p.clientId), isNull);
    expect(await repo.pendingCount(), 1);
    await engine(repo).syncOnce();

    expect(server.profiles[p.clientId]!.deleted, isTrue);
    expect(await repo.pendingCount(), 0);
  });

  test('a person the server never saw is deleted without a request', () async {
    final repo = await open();
    final p = await repo.create(name: 'علی');
    await repo.delete(p.clientId);
    expect(await repo.pendingCount(), 0);
    await engine(repo).syncOnce();
    expect(server.putCalls, 0);
  });

  test('a revoked token stops the pass and asks to pair again', () async {
    final repo = await open();
    await repo.create(name: 'علی');
    server.failPut = const ApiException(
      message: 'توکن',
      statusCode: 401,
      requiresReconnect: true,
    );
    final outcome = await engine(repo).syncOnce();
    expect(outcome.needsReconnect, isTrue);
    expect(await repo.pendingCount(), 1);
  });

  test('a refusal for good is not retried every pass', () async {
    final repo = await open();
    await repo.create(name: 'علی');
    server.failPut = const ApiException(
      message: 'سقف',
      code: 'speaker_profile_limit',
      statusCode: 409,
    );
    final first = await engine(repo).syncOnce();
    expect(first.lastError, 'سقف');
    final calls = server.putCalls;
    await engine(repo).syncOnce();
    expect(server.putCalls, calls);
  });

  test('another account clears the previous account\'s people', () async {
    final repo = await open();
    await repo.bindToAccount('a|t|u1');
    await repo.create(name: 'علی');
    expect(await repo.bindToAccount('a|t|u1'), isFalse);
    expect(await repo.people(), hasLength(1));
    expect(await repo.bindToAccount('a|t|u2'), isTrue);
    expect(await repo.people(), isEmpty);
    expect(await repo.pendingCount(), 0);
    expect(await repo.cursor(), 0);
  });

  test('voiceprints are encrypted in the database file', () async {
    final (db, d) = await openTestDb();
    dir = d;
    final repo = repoFor(db);
    final p = await repo.create(name: 'علی');
    final plain = vec([1, 2, 3, 4]);
    await repo.addVoiceprints(p.clientId, [
      voiceprint('s1', p.clientId, [1, 2, 3, 4]),
    ]);
    final raw =
        (await db.db.query('voiceprints')).single['embedding'] as List<int>;
    expect(raw, isNot(embeddingToBytes(plain)));
    expect(raw.length, embeddingToBytes(plain).length + 12 + 16);
    expect((await repo.voiceprints(p.clientId)).single.embedding, plain);
  });

  test('samples of another model are not used and flag re-enrolment', () async {
    final repo = await open();
    final p = await repo.create(name: 'علی');
    await repo.addVoiceprints(p.clientId, [
      voiceprint('s1', p.clientId, [1, 0, 0, 0], modelId: 'old'),
    ]);
    expect(
      await repo.enrolledVoices(modelId: 'campplus', modelVersion: '1'),
      isEmpty,
    );
    expect(
      await repo.needsReEnrollment(
        p.clientId,
        modelId: 'campplus',
        modelVersion: '1',
      ),
      isTrue,
    );
  });
}
