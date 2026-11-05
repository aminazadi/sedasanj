// Wire types and the interface of the speaker-profile sync API
// (`/v1/meetings/speaker-profiles`). Embeddings travel as base64 of
// little-endian float32 values; they are never logged.

class RemoteVoiceprint {
  const RemoteVoiceprint({
    required this.clientId,
    required this.modelId,
    required this.modelVersion,
    required this.dim,
    required this.embeddingB64,
    this.quality,
    this.durationMs,
  });

  final String clientId;
  final String modelId;
  final String modelVersion;
  final int dim;
  final String embeddingB64;
  final int? quality;
  final int? durationMs;

  factory RemoteVoiceprint.fromJson(Map<String, dynamic> json) =>
      RemoteVoiceprint(
        clientId: json['client_id'] as String,
        modelId: json['model_id'] as String,
        modelVersion: json['model_version'] as String,
        dim: (json['dim'] as num).toInt(),
        embeddingB64: json['embedding_b64'] as String,
        quality: (json['quality'] as num?)?.toInt(),
        durationMs: (json['duration_ms'] as num?)?.toInt(),
      );

  Map<String, Object?> toJson() => {
    'client_id': clientId,
    'model_id': modelId,
    'model_version': modelVersion,
    'dim': dim,
    'embedding_b64': embeddingB64,
    'quality': ?quality,
    'duration_ms': ?durationMs,
  };
}

/// A person as SedaSanj reports it (`SpeakerProfileOut`).
class RemoteProfile {
  const RemoteProfile({
    required this.clientId,
    required this.displayName,
    required this.visibility,
    required this.version,
    required this.changeSeq,
    required this.deleted,
    required this.mine,
    required this.voiceprints,
    this.consentAt,
    this.consentVersion,
  });

  final String clientId;
  final String displayName;
  final String visibility;
  final int version;
  final int changeSeq;
  final bool deleted;
  final bool mine;
  final DateTime? consentAt;
  final String? consentVersion;
  final List<RemoteVoiceprint> voiceprints;

  factory RemoteProfile.fromJson(Map<String, dynamic> json) => RemoteProfile(
    clientId: json['client_id'] as String,
    displayName: (json['display_name'] ?? '') as String,
    visibility: (json['visibility'] ?? 'private') as String,
    version: (json['version'] as num).toInt(),
    changeSeq: (json['change_seq'] as num).toInt(),
    deleted: json['deleted'] == true,
    mine: json['mine'] != false,
    consentAt: json['consent_at'] == null
        ? null
        : DateTime.parse(json['consent_at'] as String),
    consentVersion: json['consent_version'] as String?,
    voiceprints: [
      for (final v in (json['voiceprints'] as List? ?? const []))
        RemoteVoiceprint.fromJson(v as Map<String, dynamic>),
    ],
  );
}

class RemoteChanges {
  const RemoteChanges({
    required this.items,
    required this.nextCursor,
    required this.hasMore,
  });

  final List<RemoteProfile> items;
  final int nextCursor;
  final bool hasMore;
}

/// What the app sends for one person (`SpeakerProfilePut`).
class ProfilePutRequest {
  const ProfilePutRequest({
    required this.displayName,
    required this.visibility,
    required this.baseVersion,
    required this.voiceprints,
    required this.removeVoiceprints,
    this.consentAt,
    this.consentVersion,
  });

  final String displayName;
  final String visibility;
  final int baseVersion;
  final DateTime? consentAt;
  final String? consentVersion;
  final List<RemoteVoiceprint> voiceprints;
  final List<String> removeVoiceprints;

  Map<String, Object?> toJson() => {
    'display_name': displayName,
    'visibility': visibility,
    'base_version': baseVersion,
    if (consentAt != null && consentVersion != null)
      'consent': {
        'at': consentAt!.toUtc().toIso8601String(),
        'version': consentVersion,
      },
    'voiceprints': [for (final v in voiceprints) v.toJson()],
    'remove_voiceprints': removeVoiceprints,
  };
}

/// Server calls the sync engine needs; faked in tests.
abstract class SpeakerSyncApi {
  Future<RemoteChanges> changes({required int cursor, int? limit});

  /// Throws an `ApiException` with code `speaker_profile_conflict` (and the
  /// server state in `details['current']`) when `base_version` is stale.
  Future<RemoteProfile> putProfile(String clientId, ProfilePutRequest request);

  Future<RemoteProfile> deleteProfile(String clientId);
}
