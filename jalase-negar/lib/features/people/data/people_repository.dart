import 'dart:convert';
import 'dart:typed_data';

import 'package:sqflite/sqflite.dart';
import 'package:uuid/uuid.dart';

import '../../../core/db/app_database.dart';
import '../../../core/platform/speaker_api.dart';
import '../../../core/speaker/speaker_math.dart';
import 'embedding_cipher.dart';
import 'person.dart';
import '../../../core/speaker/voiceprint_diversity.dart';

/// Settings keys of the sync state.
const String kSpeakerSyncCursorKey = 'speaker_sync_cursor';
const String kSpeakerSyncAccountKey = 'speaker_sync_account';
const String kSpeakerSyncLastAtKey = 'speaker_sync_last_at';

/// A pending change of one person, as the sync engine sees it.
class OutboxEntry {
  const OutboxEntry({
    required this.entityId,
    required this.op,
    required this.rev,
    required this.removedVoiceprints,
    required this.attempts,
    this.nextAttemptAt,
  });

  final String entityId;

  /// `upsert` or `delete`.
  final String op;

  /// Bumped whenever the entry is rewritten, so a push that finished while the
  /// user kept editing does not discard the newer change.
  final int rev;
  final List<String> removedVoiceprints;
  final int attempts;
  final int? nextAttemptAt;

  bool get isDelete => op == 'delete';
}

/// People, their voiceprints and the outbox of changes waiting to reach
/// SedaSanj. A change and its outbox entry are written in one transaction, so
/// a killed app never loses either.
class PeopleRepository {
  PeopleRepository(this._db, this._cipher, {Uuid uuid = const Uuid()})
    : _uuid = uuid;

  final AppDatabase _db;
  final EmbeddingCipher _cipher;
  final Uuid _uuid;

  // --- reading ---------------------------------------------------------

  Future<List<Person>> people() async {
    final rows = await _db.db.query(
      'people',
      orderBy: 'display_name COLLATE NOCASE',
    );
    final counts = {
      for (final r in await _db.db.rawQuery(
        'SELECT person_id, COUNT(*) AS n FROM voiceprints GROUP BY person_id',
      ))
        r['person_id'] as String: r['n'] as int,
    };
    final pending = {
      for (final r in await _db.db.query('sync_outbox', columns: ['entity_id']))
        r['entity_id'] as String,
    };
    return [
      for (final r in rows)
        Person.fromRow(
          r,
          voiceprintCount: counts[r['client_id']] ?? 0,
          pendingSync: pending.contains(r['client_id']),
        ),
    ];
  }

  Future<Person?> person(String clientId) async {
    final all = await people();
    for (final p in all) {
      if (p.clientId == clientId) return p;
    }
    return null;
  }

  Future<List<Voiceprint>> voiceprints(String personId) async {
    final rows = await _db.db.query(
      'voiceprints',
      where: 'person_id = ?',
      whereArgs: [personId],
      orderBy: 'created_at ASC',
    );
    return [for (final r in rows) await _voiceprint(r)];
  }

  Future<Voiceprint> _voiceprint(Map<String, Object?> r) async {
    final plain = await _cipher.decrypt(r['embedding'] as Uint8List);
    return Voiceprint(
      clientId: r['client_id'] as String,
      personId: r['person_id'] as String,
      modelId: r['model_id'] as String,
      modelVersion: r['model_version'] as String,
      embedding: embeddingFromBytes(plain),
      createdAt: DateTime.fromMillisecondsSinceEpoch(r['created_at'] as int),
      quality: r['quality'] as int?,
      durationMs: r['duration_ms'] as int?,
      synced: (r['synced'] as int) != 0,
    );
  }

  /// Everyone who can be recognised with the installed embedding model: the
  /// mean of their samples made by that model. People with only samples of
  /// another model are left out (they need to record again).
  Future<List<EnrolledVoice>> enrolledVoices({
    required String modelId,
    required String modelVersion,
  }) async {
    final out = <EnrolledVoice>[];
    for (final p in await people()) {
      final usable = [
        for (final v in await voiceprints(p.clientId))
          if (v.modelId == modelId && v.modelVersion == modelVersion)
            v.embedding,
      ];
      if (usable.isEmpty) continue;
      out.add(
        EnrolledVoice(
          personId: p.clientId,
          name: p.name,
          centroid: centroid(usable),
          samples: usable.length,
        ),
      );
    }
    return out;
  }

  /// Whether the person has samples, none of which the installed model made.
  Future<bool> needsReEnrollment(
    String personId, {
    required String modelId,
    required String modelVersion,
  }) async {
    final all = await voiceprints(personId);
    return all.isNotEmpty &&
        !all.any((v) => v.modelId == modelId && v.modelVersion == modelVersion);
  }

  // --- local changes (each also queues a sync) -------------------------

  /// Creates a person. [consentAt] must be set when a voice will be recorded.
  Future<Person> create({
    required String name,
    PersonVisibility visibility = PersonVisibility.private,
    DateTime? consentAt,
    String? consentVersion,
    DateTime? now,
  }) async {
    final id = _uuid.v4();
    final stamp = (now ?? DateTime.now()).millisecondsSinceEpoch;
    await _db.db.transaction((txn) async {
      await txn.insert('people', {
        'client_id': id,
        'display_name': name.trim(),
        'visibility': visibility.name,
        'version': 0,
        'change_seq': 0,
        'mine': 1,
        'consent_at': consentAt?.millisecondsSinceEpoch,
        'consent_version': consentVersion,
        'updated_at': stamp,
      });
      await _queue(txn, id, 'upsert', stamp);
    });
    return (await person(id))!;
  }

  Future<void> update(
    String clientId, {
    String? name,
    PersonVisibility? visibility,
    DateTime? consentAt,
    String? consentVersion,
  }) async {
    final stamp = DateTime.now().millisecondsSinceEpoch;
    await _db.db.transaction((txn) async {
      final rows = await txn.query(
        'people',
        where: 'client_id = ? AND mine = 1',
        whereArgs: [clientId],
      );
      if (rows.isEmpty) return;
      await txn.update(
        'people',
        {
          'display_name': ?name?.trim(),
          'visibility': ?visibility?.name,
          'consent_at': ?consentAt?.millisecondsSinceEpoch,
          'consent_version': ?consentVersion,
          'updated_at': stamp,
        },
        where: 'client_id = ?',
        whereArgs: [clientId],
      );
      await _queue(txn, clientId, 'upsert', stamp);
    });
  }

  /// Stores new voice samples of one person.
  Future<void> addVoiceprints(String personId, List<Voiceprint> samples) async {
    final sealed = [
      for (final v in samples)
        (v, await _cipher.encrypt(embeddingToBytes(v.embedding))),
    ];
    final stamp = DateTime.now().millisecondsSinceEpoch;
    await _db.db.transaction((txn) async {
      for (final (v, blob) in sealed) {
        await txn.insert('voiceprints', {
          'client_id': v.clientId,
          'person_id': personId,
          'model_id': v.modelId,
          'model_version': v.modelVersion,
          'dim': v.dim,
          'embedding': blob,
          'quality': v.quality,
          'duration_ms': v.durationMs,
          'created_at': v.createdAt.millisecondsSinceEpoch,
          'synced': 0,
        }, conflictAlgorithm: ConflictAlgorithm.replace);
      }
      await txn.update(
        'people',
        {'updated_at': stamp},
        where: 'client_id = ?',
        whereArgs: [personId],
      );
      await _queue(txn, personId, 'upsert', stamp);
    });
  }

  /// Keeps this person's voiceprints varied: alike samples are grouped and a
  /// group holds at most [policy].perGroup of them (see
  /// `voiceprint_diversity.dart`). Readings made during enrolment (they have a
  /// quality score) are never removed. Models are pruned separately, because
  /// their embeddings cannot be compared. Returns how many were removed.
  Future<int> pruneVoiceprints(
    String personId, {
    DiversityPolicy policy = const DiversityPolicy(),
  }) async {
    final byModel = <String, List<VoiceSample>>{};
    for (final v in await voiceprints(personId)) {
      byModel
          .putIfAbsent('${v.modelId}/${v.modelVersion}', () => [])
          .add(
            VoiceSample(
              id: v.clientId,
              embedding: v.embedding,
              createdAt: v.createdAt,
              protected: v.quality != null,
              quality: v.quality,
              durationMs: v.durationMs,
            ),
          );
    }
    var removed = 0;
    for (final samples in byModel.values) {
      for (final id in voiceSamplesToRemove(samples, policy)) {
        await removeVoiceprint(personId, id);
        removed++;
      }
    }
    return removed;
  }

  Future<void> removeVoiceprint(String personId, String voiceprintId) async {
    final stamp = DateTime.now().millisecondsSinceEpoch;
    await _db.db.transaction((txn) async {
      final rows = await txn.query(
        'voiceprints',
        columns: ['synced'],
        where: 'client_id = ? AND person_id = ?',
        whereArgs: [voiceprintId, personId],
      );
      if (rows.isEmpty) return;
      await txn.delete(
        'voiceprints',
        where: 'client_id = ?',
        whereArgs: [voiceprintId],
      );
      await _queue(
        txn,
        personId,
        'upsert',
        stamp,
        // A sample the server never saw needs no removal request.
        removed: (rows.first['synced'] as int) != 0 ? [voiceprintId] : const [],
      );
    });
  }

  /// Forgets a person on this phone and, through the outbox, on SedaSanj and
  /// every other phone. Transcript lines keep the name they were written with.
  Future<void> delete(String clientId) async {
    final stamp = DateTime.now().millisecondsSinceEpoch;
    await _db.db.transaction((txn) async {
      final rows = await txn.query(
        'people',
        columns: ['version', 'mine'],
        where: 'client_id = ?',
        whereArgs: [clientId],
      );
      if (rows.isEmpty) return;
      final knownToServer = (rows.first['version'] as int) > 0;
      await txn.delete('people', where: 'client_id = ?', whereArgs: [clientId]);
      if (knownToServer && (rows.first['mine'] as int) != 0) {
        await _queue(txn, clientId, 'delete', stamp);
      } else {
        await txn.delete(
          'sync_outbox',
          where: 'entity_id = ?',
          whereArgs: [clientId],
        );
      }
    });
  }

  Future<void> _queue(
    Transaction txn,
    String entityId,
    String op,
    int stamp, {
    List<String> removed = const [],
  }) async {
    final rows = await txn.query(
      'sync_outbox',
      where: 'entity_id = ?',
      whereArgs: [entityId],
    );
    if (rows.isEmpty) {
      await txn.insert('sync_outbox', {
        'entity_id': entityId,
        'op': op,
        'rev': 1,
        'removed_voiceprints': jsonEncode(removed),
        'created_at': stamp,
      });
      return;
    }
    final merged = {
      ...(jsonDecode(rows.first['removed_voiceprints'] as String) as List)
          .cast<String>(),
      ...removed,
    };
    await txn.update(
      'sync_outbox',
      {
        // A delete is never turned back into an edit.
        'op': rows.first['op'] == 'delete' ? 'delete' : op,
        'rev': (rows.first['rev'] as int) + 1,
        'removed_voiceprints': jsonEncode(merged.toList()),
        'attempts': 0,
        'next_attempt_at': null,
        'last_error_code': null,
      },
      where: 'entity_id = ?',
      whereArgs: [entityId],
    );
  }

  // --- sync ------------------------------------------------------------

  Future<List<OutboxEntry>> outbox() async {
    final rows = await _db.db.query('sync_outbox', orderBy: 'created_at ASC');
    return [
      for (final r in rows)
        OutboxEntry(
          entityId: r['entity_id'] as String,
          op: r['op'] as String,
          rev: r['rev'] as int,
          removedVoiceprints:
              (jsonDecode(r['removed_voiceprints'] as String) as List)
                  .cast<String>(),
          attempts: r['attempts'] as int,
          nextAttemptAt: r['next_attempt_at'] as int?,
        ),
    ];
  }

  Future<int> pendingCount() async =>
      Sqflite.firstIntValue(
        await _db.db.rawQuery('SELECT COUNT(*) FROM sync_outbox'),
      ) ??
      0;

  /// The request that brings SedaSanj up to date with [entityId], or null when
  /// the person no longer exists locally.
  Future<ProfilePutRequest?> buildPut(OutboxEntry entry) async {
    final p = await person(entry.entityId);
    if (p == null) return null;
    final unsynced = [
      for (final v in await voiceprints(entry.entityId))
        if (!v.synced) v,
    ];
    return ProfilePutRequest(
      displayName: p.name,
      visibility: p.visibility.name,
      baseVersion: p.version,
      consentAt: p.consentAt,
      consentVersion: p.consentVersion,
      voiceprints: [
        for (final v in unsynced)
          RemoteVoiceprint(
            clientId: v.clientId,
            modelId: v.modelId,
            modelVersion: v.modelVersion,
            dim: v.dim,
            embeddingB64: embeddingToBase64(v.embedding),
            quality: v.quality,
            durationMs: v.durationMs,
          ),
      ],
      removeVoiceprints: entry.removedVoiceprints,
    );
  }

  /// The server accepted [entry]'s push and answered with [profile]: adopt its
  /// version, merge samples other phones added, and drop the outbox entry
  /// unless the user changed the person again meanwhile.
  Future<void> completePush(OutboxEntry entry, RemoteProfile profile) async {
    final incoming = await _sealVoiceprints(profile.voiceprints);
    await _db.db.transaction((txn) async {
      await txn.update(
        'people',
        {'version': profile.version, 'change_seq': profile.changeSeq},
        where: 'client_id = ?',
        whereArgs: [entry.entityId],
      );
      await _mergeVoiceprints(txn, entry.entityId, incoming);
      for (final v in profile.voiceprints) {
        await txn.update(
          'voiceprints',
          {'synced': 1},
          where: 'person_id = ? AND client_id = ?',
          whereArgs: [entry.entityId, v.clientId],
        );
      }
      await txn.delete(
        'sync_outbox',
        where: 'entity_id = ? AND rev = ?',
        whereArgs: [entry.entityId, entry.rev],
      );
    });
  }

  /// A stale push: take the server's version (and its samples) as the new
  /// base and keep the local edit queued, so the retry applies on top of it.
  Future<void> rebaseOnServer(OutboxEntry entry, RemoteProfile current) async {
    if (current.deleted) {
      await dropPerson(entry.entityId);
      return;
    }
    final incoming = await _sealVoiceprints(current.voiceprints);
    await _db.db.transaction((txn) async {
      await txn.update(
        'people',
        {'version': current.version, 'change_seq': current.changeSeq},
        where: 'client_id = ?',
        whereArgs: [entry.entityId],
      );
      await _mergeVoiceprints(txn, entry.entityId, incoming);
      await txn.update(
        'sync_outbox',
        {'attempts': 0, 'next_attempt_at': null, 'last_error_code': null},
        where: 'entity_id = ?',
        whereArgs: [entry.entityId],
      );
    });
  }

  /// A delete reached the server (or there was nothing left to delete).
  Future<void> completeDelete(OutboxEntry entry) => _db.db.delete(
    'sync_outbox',
    where: 'entity_id = ? AND rev = ?',
    whereArgs: [entry.entityId, entry.rev],
  );

  /// Removes a person and its queued changes without telling the server (it
  /// already knows, or never will).
  Future<void> dropPerson(String clientId) async {
    await _db.db.transaction((txn) async {
      await txn.delete('people', where: 'client_id = ?', whereArgs: [clientId]);
      await txn.delete(
        'sync_outbox',
        where: 'entity_id = ?',
        whereArgs: [clientId],
      );
    });
  }

  Future<void> markPushFailed(
    OutboxEntry entry, {
    required int nextAttemptAt,
    String? code,
  }) => _db.db.update(
    'sync_outbox',
    {
      'attempts': entry.attempts + 1,
      'next_attempt_at': nextAttemptAt,
      'last_error_code': code,
    },
    where: 'entity_id = ?',
    whereArgs: [entry.entityId],
  );

  /// Applies a change from SedaSanj. A person with a queued local change keeps
  /// its local name and visibility (the local edit is newer and will be
  /// pushed), but still learns the server version and new samples.
  Future<void> applyRemote(RemoteProfile profile) async {
    final id = profile.clientId;
    if (profile.deleted) {
      await dropPerson(id);
      return;
    }
    final incoming = await _sealVoiceprints(profile.voiceprints);
    await _db.db.transaction((txn) async {
      final queued = await txn.query(
        'sync_outbox',
        where: 'entity_id = ?',
        whereArgs: [id],
      );
      if (queued.isNotEmpty && queued.first['op'] == 'delete') return;
      final existing = await txn.query(
        'people',
        where: 'client_id = ?',
        whereArgs: [id],
      );
      final stamp = DateTime.now().millisecondsSinceEpoch;
      final values = <String, Object?>{
        'version': profile.version,
        'change_seq': profile.changeSeq,
        'mine': profile.mine ? 1 : 0,
        'consent_at': profile.consentAt?.millisecondsSinceEpoch,
        'consent_version': profile.consentVersion,
      };
      if (queued.isEmpty) {
        values['display_name'] = profile.displayName;
        values['visibility'] = profile.visibility;
        values['updated_at'] = stamp;
      }
      if (existing.isEmpty) {
        await txn.insert('people', {
          'client_id': id,
          'display_name': profile.displayName,
          'visibility': profile.visibility,
          'updated_at': stamp,
          ...values,
        });
      } else {
        await txn.update(
          'people',
          values,
          where: 'client_id = ?',
          whereArgs: [id],
        );
      }
      // Samples the server dropped (removed on another phone) go too, except
      // ones still waiting to be pushed from here.
      final keep = {for (final v in profile.voiceprints) v.clientId};
      final local = await txn.query(
        'voiceprints',
        columns: ['client_id', 'synced'],
        where: 'person_id = ?',
        whereArgs: [id],
      );
      for (final r in local) {
        if ((r['synced'] as int) != 0 && !keep.contains(r['client_id'])) {
          await txn.delete(
            'voiceprints',
            where: 'client_id = ?',
            whereArgs: [r['client_id']],
          );
        }
      }
      await _mergeVoiceprints(txn, id, incoming);
    });
  }

  Future<List<(RemoteVoiceprint, Uint8List)>> _sealVoiceprints(
    List<RemoteVoiceprint> items,
  ) async => [
    for (final v in items)
      (v, await _cipher.encrypt(base64Decode(v.embeddingB64))),
  ];

  Future<void> _mergeVoiceprints(
    Transaction txn,
    String personId,
    List<(RemoteVoiceprint, Uint8List)> incoming,
  ) async {
    for (final (v, blob) in incoming) {
      final exists = await txn.query(
        'voiceprints',
        columns: ['client_id'],
        where: 'client_id = ?',
        whereArgs: [v.clientId],
      );
      if (exists.isNotEmpty) continue;
      await txn.insert('voiceprints', {
        'client_id': v.clientId,
        'person_id': personId,
        'model_id': v.modelId,
        'model_version': v.modelVersion,
        'dim': v.dim,
        'embedding': blob,
        'quality': v.quality,
        'duration_ms': v.durationMs,
        'created_at': DateTime.now().millisecondsSinceEpoch,
        'synced': 1,
      });
    }
  }

  Future<int> cursor() async =>
      int.tryParse(await _db.getSetting(kSpeakerSyncCursorKey) ?? '') ?? 0;

  Future<void> setCursor(int value) =>
      _db.setSetting(kSpeakerSyncCursorKey, '$value');

  /// Local people belong to the account that was paired when they were
  /// created. When another account pairs, they are cleared so one user's
  /// voices never reach another's server account.
  Future<bool> bindToAccount(String account) async {
    final bound = await _db.getSetting(kSpeakerSyncAccountKey);
    if (bound == account) return false;
    if (bound != null) {
      await _db.db.transaction((txn) async {
        await txn.delete('people');
        await txn.delete('sync_outbox');
      });
      await setCursor(0);
    }
    await _db.setSetting(kSpeakerSyncAccountKey, account);
    return bound != null;
  }

  Future<DateTime?> lastSyncAt() async {
    final raw = int.tryParse(await _db.getSetting(kSpeakerSyncLastAtKey) ?? '');
    return raw == null ? null : DateTime.fromMillisecondsSinceEpoch(raw);
  }

  Future<void> setLastSyncAt(DateTime at) =>
      _db.setSetting(kSpeakerSyncLastAtKey, '${at.millisecondsSinceEpoch}');
}
