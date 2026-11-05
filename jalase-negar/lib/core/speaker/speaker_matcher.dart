import 'dart:typed_data';

import '../../features/people/data/person.dart';
import 'speaker_math.dart';

/// Who a voice was matched to.
class SpeakerIdentity {
  const SpeakerIdentity({
    required this.name,
    this.personId,
    this.confidence = 0,
  });

  /// A person's name, or "Unknown N" for a voice nobody enrolled.
  final String name;

  /// The enrolled person; null for unknown voices.
  final String? personId;

  /// 0..100.
  final int confidence;

  bool get known => personId != null;

  /// The same voice, whatever the confidence of the match.
  String get key => personId ?? 'u:$name';

  SpeakerIdentity withConfidence(int value) =>
      SpeakerIdentity(name: name, personId: personId, confidence: value);
}

/// Thresholds of the live matcher.
///
/// ⚠ needs lab confirmation: these are starting values from the published
/// range for cosine similarity (about 0.45–0.5), not measured on Persian
/// meeting audio. Phase 0 (an evaluation set) has not been run.
class MatchThresholds {
  const MatchThresholds({
    this.accept = 0.50,
    this.margin = 0.06,
    this.unknownJoin = 0.55,
    this.lowConfidenceCap = 55,
  });

  /// Cosine score a person needs to be named.
  final double accept;

  /// How far the best person must lead the runner-up (when someone else is
  /// enrolled), so two similar voices are not guessed between.
  final double margin;

  /// Cosine score two unknown voices need to count as the same "Unknown".
  final double unknownJoin;

  /// Highest confidence for a match made from contaminated or too little
  /// audio.
  final int lowConfidenceCap;
}

/// Matches voice embeddings to the people enrolled on this phone and keeps
/// track of unknown voices heard in the current meeting.
class SpeakerMatcher {
  SpeakerMatcher(
    List<EnrolledVoice> enrolled, {
    this.thresholds = const MatchThresholds(),
  }) : _enrolled = [
         for (final e in enrolled)
           if (e.centroid.isNotEmpty) e,
       ];

  final List<EnrolledVoice> _enrolled;
  final MatchThresholds thresholds;
  final List<(String, Float32List)> _unknown = [];

  bool get hasEnrolled => _enrolled.isNotEmpty;

  /// Names the voice, or hands out a stable "Unknown N" label. [reliable] is
  /// false when the audio mixed in another speaker or was very short; such a
  /// match never gets a high confidence.
  SpeakerIdentity identify(Float32List embedding, {bool reliable = true}) {
    if (embedding.isEmpty) return const SpeakerIdentity(name: 'ناشناس');
    EnrolledVoice? best;
    var bestScore = -2.0;
    var secondScore = -2.0;
    for (final voice in _enrolled) {
      final score = cosine(embedding, voice.centroid);
      if (score > bestScore) {
        secondScore = bestScore;
        bestScore = score;
        best = voice;
      } else if (score > secondScore) {
        secondScore = score;
      }
    }
    final leads =
        _enrolled.length < 2 || bestScore - secondScore >= thresholds.margin;
    if (best != null && bestScore >= thresholds.accept && leads) {
      var confidence = _confidence(bestScore, secondScore);
      if (!reliable && confidence > thresholds.lowConfidenceCap) {
        confidence = thresholds.lowConfidenceCap;
      }
      return SpeakerIdentity(
        name: best.name,
        personId: best.personId,
        confidence: confidence,
      );
    }
    return _unknownVoice(embedding, reliable: reliable);
  }

  /// 0..100 from the score and the lead over the runner-up.
  int _confidence(double best, double second) {
    final fromScore = ((best - 0.30) / 0.45).clamp(0.0, 1.0);
    final fromLead = second < -1
        ? 1.0
        : ((best - second) / 0.25).clamp(0.0, 1.0);
    return (100 * (0.7 * fromScore + 0.3 * fromLead)).round().clamp(0, 100);
  }

  SpeakerIdentity _unknownVoice(
    Float32List embedding, {
    required bool reliable,
  }) {
    var bestIndex = -1;
    var bestScore = -2.0;
    for (var i = 0; i < _unknown.length; i++) {
      final score = cosine(embedding, _unknown[i].$2);
      if (score > bestScore) {
        bestScore = score;
        bestIndex = i;
      }
    }
    if (bestIndex >= 0 && bestScore >= thresholds.unknownJoin) {
      // Drift the representative slowly so the label follows the voice.
      final merged = centroid([_unknown[bestIndex].$2, embedding]);
      _unknown[bestIndex] = (_unknown[bestIndex].$1, merged);
      return SpeakerIdentity(
        name: _unknown[bestIndex].$1,
        confidence: reliable ? 40 : 20,
      );
    }
    final label = 'ناشناس ${_unknown.length + 1}';
    _unknown.add((label, normalized(embedding)));
    return SpeakerIdentity(name: label, confidence: reliable ? 40 : 20);
  }
}
