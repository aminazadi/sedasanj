import 'dart:typed_data';

/// Who can see an enrolled person.
enum PersonVisibility {
  /// Only the user who created the person.
  private,

  /// Every phone paired to the same organisation (read-only for colleagues).
  org;

  static PersonVisibility parse(String? value) =>
      value == 'org' ? PersonVisibility.org : PersonVisibility.private;
}

/// Version of the consent text the user agreed to before a voice was
/// recorded. Bump it when the wording changes.
const String kSpeakerConsentVersion = '2026-11-fa-1';

/// An enrolled speaker. [version] is the server's optimistic-lock version of
/// the last state this phone saw (0 until the server has accepted the person).
class Person {
  const Person({
    required this.clientId,
    required this.name,
    required this.visibility,
    required this.version,
    required this.changeSeq,
    required this.mine,
    required this.updatedAt,
    this.consentAt,
    this.consentVersion,
    this.voiceprintCount = 0,
    this.pendingSync = false,
  });

  final String clientId;
  final String name;
  final PersonVisibility visibility;
  final int version;
  final int changeSeq;

  /// False for a colleague's shared person: usable for recognition, read-only.
  final bool mine;
  final DateTime updatedAt;
  final DateTime? consentAt;
  final String? consentVersion;
  final int voiceprintCount;

  /// A change of this person has not reached SedaSanj yet.
  final bool pendingSync;

  bool get shared => visibility == PersonVisibility.org;

  factory Person.fromRow(
    Map<String, Object?> row, {
    int voiceprintCount = 0,
    bool pendingSync = false,
  }) => Person(
    clientId: row['client_id'] as String,
    name: row['display_name'] as String,
    visibility: PersonVisibility.parse(row['visibility'] as String?),
    version: row['version'] as int,
    changeSeq: row['change_seq'] as int,
    mine: (row['mine'] as int) != 0,
    updatedAt: DateTime.fromMillisecondsSinceEpoch(row['updated_at'] as int),
    consentAt: row['consent_at'] == null
        ? null
        : DateTime.fromMillisecondsSinceEpoch(row['consent_at'] as int),
    consentVersion: row['consent_version'] as String?,
    voiceprintCount: voiceprintCount,
    pendingSync: pendingSync,
  );
}

/// One recorded sample of a person's voice, reduced to an embedding.
class Voiceprint {
  const Voiceprint({
    required this.clientId,
    required this.personId,
    required this.modelId,
    required this.modelVersion,
    required this.embedding,
    required this.createdAt,
    this.quality,
    this.durationMs,
    this.synced = false,
  });

  final String clientId;
  final String personId;
  final String modelId;
  final String modelVersion;
  final Float32List embedding;
  final DateTime createdAt;

  /// 0..100 quality score of the recording the embedding came from.
  final int? quality;
  final int? durationMs;

  /// SedaSanj holds this sample.
  final bool synced;

  int get dim => embedding.length;
}

/// A person with the mean embedding the live matcher compares against, for the
/// model that is installed.
class EnrolledVoice {
  const EnrolledVoice({
    required this.personId,
    required this.name,
    required this.centroid,
    required this.samples,
    this.preferred = false,
  });

  final String personId;
  final String name;
  final Float32List centroid;
  final int samples;

  /// True for a person chosen as present in this meeting; the matcher gives
  /// such voices a small head start over everyone else enrolled.
  final bool preferred;

  EnrolledVoice asPreferred(bool value) => EnrolledVoice(
    personId: personId,
    name: name,
    centroid: centroid,
    samples: samples,
    preferred: value,
  );

  /// Plain data for the live isolate.
  Map<String, Object?> toMap() => {
    'id': personId,
    'name': name,
    'centroid': centroid,
    'samples': samples,
    'preferred': preferred,
  };

  factory EnrolledVoice.fromMap(Map<Object?, Object?> map) => EnrolledVoice(
    personId: map['id']! as String,
    name: map['name']! as String,
    centroid: map['centroid']! as Float32List,
    samples: map['samples']! as int,
    preferred: map['preferred'] == true,
  );
}
