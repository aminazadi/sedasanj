import 'dart:typed_data';

import 'speaker_math.dart';

/// Keeps a person's voiceprints varied instead of numerous.
///
/// One voice sounds different when it is close or far, loud or soft, fast or
/// tired. Rather than guessing a label for each of those conditions (emotion
/// recognition is unreliable on Persian meeting speech), voiceprints are
/// grouped by how alike their embeddings are, and each group keeps at most
/// [DiversityPolicy.perGroup] samples. Pure Dart, no I/O, unit-tested.
///
/// ⚠ needs lab confirmation: [kVoiceGroupJoinSimilarity] is a starting value.
/// It has not been measured on Persian recordings of one person in different
/// conditions; calibrate it with the bench before relying on it.

/// Cosine similarity two embeddings need to count as the same voice
/// condition. Stricter than the matcher's "same person" scores, because the
/// point is to tell conditions of one person apart.
const double kVoiceGroupJoinSimilarity = 0.70;

/// Samples kept per condition group.
const int kVoiceSamplesPerGroup = 3;

/// Most voiceprints kept for one person across all groups.
const int kVoiceSamplesPerPerson = 12;

class DiversityPolicy {
  const DiversityPolicy({
    this.joinSimilarity = kVoiceGroupJoinSimilarity,
    this.perGroup = kVoiceSamplesPerGroup,
    this.maxTotal = kVoiceSamplesPerPerson,
  }) : assert(perGroup > 0),
       assert(maxTotal > 0);

  final double joinSimilarity;
  final int perGroup;
  final int maxTotal;
}

/// One stored voiceprint, as far as pruning needs to know.
class VoiceSample {
  const VoiceSample({
    required this.id,
    required this.embedding,
    required this.createdAt,
    this.protected = false,
    this.quality,
    this.durationMs,
  });

  final String id;
  final Float32List embedding;
  final DateTime createdAt;

  /// Never removed (the person read it on purpose during enrolment).
  final bool protected;
  final int? quality;
  final int? durationMs;
}

/// A group of alike samples, best first.
class VoiceGroup {
  VoiceGroup(VoiceSample first)
    : members = [first],
      centre = normalized(first.embedding);

  final List<VoiceSample> members;
  Float32List centre;

  void add(VoiceSample sample) {
    members.add(sample);
    centre = centroid([for (final m in members) m.embedding]);
  }
}

/// Best first: protected, then quality, then longer, then newer. The id is the
/// last key so the order never depends on input order.
int _rank(VoiceSample a, VoiceSample b) {
  if (a.protected != b.protected) return a.protected ? -1 : 1;
  final q = (b.quality ?? 0).compareTo(a.quality ?? 0);
  if (q != 0) return q;
  final d = (b.durationMs ?? 0).compareTo(a.durationMs ?? 0);
  if (d != 0) return d;
  final t = b.createdAt.compareTo(a.createdAt);
  return t != 0 ? t : a.id.compareTo(b.id);
}

/// Groups [samples] by embedding similarity. Samples of another embedding
/// length (another model) never share a group with these.
List<VoiceGroup> groupVoiceSamples(
  List<VoiceSample> samples,
  DiversityPolicy policy,
) {
  final ordered = [...samples]..sort(_rank);
  final groups = <VoiceGroup>[];
  for (final sample in ordered) {
    VoiceGroup? best;
    var bestScore = policy.joinSimilarity;
    for (final group in groups) {
      final score = cosine(sample.embedding, group.centre);
      if (score >= bestScore) {
        best = group;
        bestScore = score;
      }
    }
    if (best == null) {
      groups.add(VoiceGroup(sample));
    } else {
      best.add(sample);
    }
  }
  return groups;
}

/// Ids to delete so that no group holds more than [DiversityPolicy.perGroup]
/// samples and the person has at most [DiversityPolicy.maxTotal] in all.
/// Protected samples are never returned; they still count towards the limits.
List<String> voiceSamplesToRemove(
  List<VoiceSample> samples,
  DiversityPolicy policy,
) {
  final groups = groupVoiceSamples(samples, policy);
  final remove = <String>[];
  final kept = <VoiceGroup, List<VoiceSample>>{};
  for (final group in groups) {
    final keep = <VoiceSample>[];
    for (final m in group.members) {
      if (m.protected || keep.length < policy.perGroup) {
        keep.add(m);
      } else {
        remove.add(m.id);
      }
    }
    kept[group] = keep;
  }
  // Over the person-wide limit: trim the most crowded group, its weakest
  // removable sample first, so every condition keeps a representative.
  var total = kept.values.fold<int>(0, (n, list) => n + list.length);
  while (total > policy.maxTotal) {
    VoiceGroup? crowded;
    for (final entry in kept.entries) {
      final removable = entry.value.any((m) => !m.protected);
      if (!removable) continue;
      if (crowded == null || entry.value.length > kept[crowded]!.length) {
        crowded = entry.key;
      }
    }
    if (crowded == null) break;
    final list = kept[crowded]!;
    final weakest = list.lastWhere((m) => !m.protected);
    list.remove(weakest);
    remove.add(weakest.id);
    total--;
  }
  return remove;
}
