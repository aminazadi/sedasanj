import 'dart:io';
import 'dart:typed_data';

import 'package:jalase_negar/core/db/app_database.dart';
import 'package:jalase_negar/core/platform/api_client.dart';
import 'package:jalase_negar/core/platform/speaker_api.dart';
import 'package:jalase_negar/core/speaker/speaker_math.dart';
import 'package:jalase_negar/features/people/data/embedding_cipher.dart';
import 'package:jalase_negar/features/people/data/people_repository.dart';
import 'package:jalase_negar/features/people/data/person.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

bool _ffiReady = false;

Future<(AppDatabase, Directory)> openTestDb([Directory? dir]) async {
  if (!_ffiReady) {
    sqfliteFfiInit();
    _ffiReady = true;
  }
  final d = dir ?? Directory.systemTemp.createTempSync('people');
  final db = await AppDatabase.open(
    '${d.path}/test.db',
    factory: databaseFactoryFfi,
  );
  return (db, d);
}

Float32List vec(List<double> values) => Float32List.fromList(values);

Voiceprint voiceprint(
  String id,
  String personId,
  List<double> embedding, {
  String modelId = 'campplus',
  String modelVersion = '1',
}) => Voiceprint(
  clientId: id,
  personId: personId,
  modelId: modelId,
  modelVersion: modelVersion,
  embedding: vec(embedding),
  createdAt: DateTime(2026, 11, 1),
  quality: 80,
  durationMs: 20000,
);

PeopleRepository repoFor(AppDatabase db, [EmbeddingCipher? cipher]) =>
    PeopleRepository(db, cipher ?? AesGcmEmbeddingCipher.random());

/// An in-memory stand-in for the speaker-profiles endpoints, with the same
/// version, change_seq and tombstone rules as the real server.
class FakeSpeakerServer implements SpeakerSyncApi {
  final Map<String, RemoteProfile> profiles = {};
  int seq = 0;
  int putCalls = 0;
  int changeCalls = 0;
  ApiException? failPut;
  ApiException? failChanges;
  int pageLimit = 500;
  final List<ProfilePutRequest> received = [];

  RemoteProfile _store(
    String id, {
    required String name,
    required String visibility,
    required int version,
    required List<RemoteVoiceprint> voiceprints,
    DateTime? consentAt,
    String? consentVersion,
    bool deleted = false,
    bool mine = true,
  }) {
    seq += 1;
    final p = RemoteProfile(
      clientId: id,
      displayName: deleted ? '' : name,
      visibility: visibility,
      version: version,
      changeSeq: seq,
      deleted: deleted,
      mine: mine,
      consentAt: consentAt,
      consentVersion: consentVersion,
      voiceprints: deleted ? const [] : voiceprints,
    );
    profiles[id] = p;
    return p;
  }

  /// Another phone of the same user changed [id].
  void editElsewhere(String id, {String? name}) {
    final old = profiles[id]!;
    _store(
      id,
      name: name ?? old.displayName,
      visibility: old.visibility,
      version: old.version + 1,
      voiceprints: old.voiceprints,
      consentAt: old.consentAt,
      consentVersion: old.consentVersion,
    );
  }

  void deleteElsewhere(String id) {
    final old = profiles[id]!;
    _store(
      id,
      name: '',
      visibility: 'private',
      version: old.version + 1,
      voiceprints: const [],
      deleted: true,
    );
  }

  void addExisting(
    String id,
    String name,
    List<RemoteVoiceprint> voiceprints, {
    bool mine = true,
  }) {
    _store(
      id,
      name: name,
      visibility: mine ? 'private' : 'org',
      version: 1,
      voiceprints: voiceprints,
      consentAt: DateTime.utc(2026, 11, 1),
      consentVersion: kSpeakerConsentVersion,
      mine: mine,
    );
  }

  @override
  Future<RemoteChanges> changes({required int cursor, int? limit}) async {
    changeCalls += 1;
    if (failChanges != null) throw failChanges!;
    final all = profiles.values.where((p) => p.changeSeq > cursor).toList()
      ..sort((a, b) => a.changeSeq.compareTo(b.changeSeq));
    final size = limit ?? pageLimit;
    final page = all.take(size).toList();
    final more = all.length > page.length;
    return RemoteChanges(
      items: page,
      nextCursor: more ? page.last.changeSeq : seq,
      hasMore: more,
    );
  }

  @override
  Future<RemoteProfile> putProfile(
    String clientId,
    ProfilePutRequest request,
  ) async {
    putCalls += 1;
    received.add(request);
    if (failPut != null) throw failPut!;
    final existing = profiles[clientId];
    if (existing == null && request.baseVersion != 0) {
      throw const ApiException(
        message: 'x',
        code: 'speaker_profile_not_found',
        statusCode: 404,
      );
    }
    if (existing != null && existing.deleted) {
      throw const ApiException(
        message: 'x',
        code: 'speaker_profile_not_found',
        statusCode: 404,
      );
    }
    if (existing != null && existing.version != request.baseVersion) {
      throw ApiException(
        message: 'x',
        code: 'speaker_profile_conflict',
        statusCode: 409,
        details: {'current': _json(existing)},
      );
    }
    final merged = {
      for (final v in existing?.voiceprints ?? <RemoteVoiceprint>[])
        v.clientId: v,
      for (final v in request.voiceprints) v.clientId: v,
    }..removeWhere((id, _) => request.removeVoiceprints.contains(id));
    return _store(
      clientId,
      name: request.displayName,
      visibility: request.visibility,
      version: (existing?.version ?? 0) + 1,
      voiceprints: merged.values.toList(),
      consentAt: request.consentAt ?? existing?.consentAt,
      consentVersion: request.consentVersion ?? existing?.consentVersion,
    );
  }

  @override
  Future<RemoteProfile> deleteProfile(String clientId) async {
    final existing = profiles[clientId];
    if (existing == null) {
      throw const ApiException(
        message: 'x',
        code: 'speaker_profile_not_found',
        statusCode: 404,
      );
    }
    return _store(
      clientId,
      name: '',
      visibility: 'private',
      version: existing.version + 1,
      voiceprints: const [],
      deleted: true,
    );
  }

  Map<String, dynamic> _json(RemoteProfile p) => {
    'client_id': p.clientId,
    'display_name': p.displayName,
    'visibility': p.visibility,
    'version': p.version,
    'change_seq': p.changeSeq,
    'deleted': p.deleted,
    'mine': p.mine,
    'consent_at': p.consentAt?.toIso8601String(),
    'consent_version': p.consentVersion,
    'voiceprints': [for (final v in p.voiceprints) v.toJson()],
  };
}

RemoteVoiceprint remoteVoiceprint(String id, List<double> embedding) =>
    RemoteVoiceprint(
      clientId: id,
      modelId: 'campplus',
      modelVersion: '1',
      dim: embedding.length,
      embeddingB64: embeddingToBase64(vec(embedding)),
      quality: 80,
      durationMs: 20000,
    );
