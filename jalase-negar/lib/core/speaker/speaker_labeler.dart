import 'dart:math' as math;
import 'dart:typed_data';

import '../asr/asr_common.dart';
import 'overlap_planner.dart';
import 'speaker_matcher.dart';

/// Splits one utterance into speaker turns (a pyannote-style segmentation).
abstract interface class UtteranceDiarizer {
  /// Turns in milliseconds from the start of [samples] (16 kHz mono).
  List<SpeakerTurn> diarize(Float32List samples);
}

/// Turns audio into a voice embedding (null when the audio is unusable).
abstract interface class VoiceEmbedder {
  Float32List? embed(Float32List samples);
}

/// Who spoke during a stretch of an utterance, on the recording's timeline.
class LabeledPart {
  const LabeledPart({
    required this.startMs,
    required this.endMs,
    required this.speakers,
    this.overlap = false,
    this.confidence,
  });

  final int startMs;
  final int endMs;

  /// One speaker, or two when [overlap] is set.
  final List<SpeakerIdentity> speakers;
  final bool overlap;

  /// 0..100; null when no match was attempted.
  final int? confidence;
}

/// What the live pipeline needs to name the speakers of one utterance.
abstract interface class UtteranceLabeler {
  /// Parts of the utterance whose samples are [speech] and which starts at
  /// [startMs] on the recording timeline. Never returns an empty list.
  List<LabeledPart> label(Float32List speech, {required int startMs});
}

/// Tunables of live identification.
///
/// ⚠ needs lab confirmation: the durations are starting values from the
/// published ranges (embeddings get unstable below roughly 1–1.5 s of clean
/// speech); the evaluation on Persian meeting audio (plan phase 0) has not run.
class LabelerSettings {
  const LabelerSettings({
    this.minDiarizeMs = 1500,
    this.minCleanMs = 1000,
    this.minAnyMs = 600,
    this.carryOverConfidence = 25,
    this.overlapConfidenceCap = 45,
    this.maxEmbedMs = 20000,
  });

  /// Shorter utterances are not segmented (one speaker is assumed).
  final int minDiarizeMs;

  /// Clean (non-overlapping) speech a voice needs for a trusted match.
  final int minCleanMs;

  /// Below this much audio the previous speaker is carried over instead of
  /// guessing from an unstable embedding.
  final int minAnyMs;
  final int carryOverConfidence;
  final int overlapConfidenceCap;
  final int maxEmbedMs;
}

/// The live "who is speaking" layer (overlap handling layer A).
///
/// For each utterance: segment it into speaker turns; embed every local
/// speaker from the stretches where only that speaker talks; match the
/// embeddings to the enrolled people; and describe the utterance as parts with
/// one speaker, or two speakers and low confidence where voices overlap. A
/// wrong name shown with confidence is worse than "ناشناس" or a low-confidence
/// label, so short or contaminated audio is never matched with high
/// confidence.
class SpeakerLabeler implements UtteranceLabeler {
  SpeakerLabeler({
    required this.diarizer,
    required this.embedder,
    required this.matcher,
    this.settings = const LabelerSettings(),
  });

  final UtteranceDiarizer? diarizer;
  final VoiceEmbedder embedder;
  final SpeakerMatcher matcher;
  final LabelerSettings settings;

  SpeakerIdentity? _previous;

  @override
  List<LabeledPart> label(Float32List speech, {required int startMs}) {
    final durationMs = speech.length * 1000 ~/ kAsrSampleRate;
    final endMs = startMs + durationMs;

    var turns = const <SpeakerTurn>[];
    final segmenter = diarizer;
    if (segmenter != null && durationMs >= settings.minDiarizeMs) {
      try {
        turns = segmenter.diarize(speech);
      } catch (_) {
        // Fall back to treating the utterance as one speaker.
        turns = const [];
      }
    }
    final planned = planParts(turns);

    if (planned.length <= 1 && (planned.isEmpty || !planned.first.overlap)) {
      final identity = _identifyWhole(speech, durationMs);
      _previous = identity;
      return [
        LabeledPart(
          startMs: startMs,
          endMs: endMs,
          speakers: [identity],
          confidence: identity.confidence,
        ),
      ];
    }

    final local = <int, SpeakerIdentity>{};
    for (final id in {for (final p in planned) ...p.speakers}) {
      local[id] = _identifyLocal(speech, turns, id);
    }

    final parts = <LabeledPart>[];
    for (final p in planned) {
      final identities = <SpeakerIdentity>[];
      for (final id in p.speakers) {
        final identity = local[id]!;
        if (identities.every((i) => i.key != identity.key)) {
          identities.add(identity);
        }
      }
      final overlap = identities.length > 1;
      var confidence = identities
          .map((i) => i.confidence)
          .reduce(math.min);
      if (overlap) confidence = math.min(confidence, settings.overlapConfidenceCap);
      if (p.shaky) confidence = math.min(confidence, settings.carryOverConfidence + 15);
      final from = startMs + p.startMs;
      final to = startMs + p.endMs;
      final last = parts.isEmpty ? null : parts.last;
      // Two diarization labels that resolved to the same person are one voice.
      if (last != null &&
          !last.overlap &&
          !overlap &&
          last.speakers.single.key == identities.single.key) {
        parts[parts.length - 1] = LabeledPart(
          startMs: last.startMs,
          endMs: to,
          speakers: last.speakers,
          confidence: math.min(last.confidence ?? 100, confidence),
        );
        continue;
      }
      parts.add(
        LabeledPart(
          startMs: from,
          endMs: to,
          speakers: identities,
          overlap: overlap,
          confidence: confidence,
        ),
      );
    }
    // Cover the whole utterance: the first part starts where speech starts and
    // the last one ends where it ends, so no words fall between parts.
    parts[0] = _withRange(parts.first, startMs: startMs);
    parts[parts.length - 1] = _withRange(parts.last, endMs: endMs);
    _previous = parts.last.speakers.last;
    return parts;
  }

  LabeledPart _withRange(LabeledPart p, {int? startMs, int? endMs}) =>
      LabeledPart(
        startMs: startMs ?? p.startMs,
        endMs: endMs ?? p.endMs,
        speakers: p.speakers,
        overlap: p.overlap,
        confidence: p.confidence,
      );

  SpeakerIdentity _identifyWhole(Float32List speech, int durationMs) {
    if (durationMs < settings.minAnyMs) return _carryOver();
    final embedding = embedder.embed(_cap(speech));
    if (embedding == null) return _carryOver();
    return matcher.identify(
      embedding,
      reliable: durationMs >= settings.minCleanMs,
    );
  }

  SpeakerIdentity _identifyLocal(
    Float32List speech,
    List<SpeakerTurn> turns,
    int speaker,
  ) {
    final clean = _gather(speech, cleanSpans(turns, speaker));
    final cleanMs = clean.length * 1000 ~/ kAsrSampleRate;
    if (cleanMs >= settings.minCleanMs) {
      final embedding = embedder.embed(_cap(clean));
      if (embedding != null) return matcher.identify(embedding);
    }
    // Not enough clean speech: use everything this speaker said, but never
    // trust the match (other voices are mixed in).
    final all = _gather(speech, [
      for (final t in turns)
        if (t.speaker == speaker) (t.startMs, t.endMs),
    ]);
    final allMs = all.length * 1000 ~/ kAsrSampleRate;
    if (allMs >= settings.minAnyMs) {
      final embedding = embedder.embed(_cap(all));
      if (embedding != null) return matcher.identify(embedding, reliable: false);
    }
    return _carryOver();
  }

  SpeakerIdentity _carryOver() {
    final previous = _previous;
    if (previous == null) {
      return const SpeakerIdentity(name: 'ناشناس', confidence: 0);
    }
    return previous.withConfidence(
      math.min(previous.confidence, settings.carryOverConfidence),
    );
  }

  Float32List _cap(Float32List samples) {
    final max = settings.maxEmbedMs * kAsrSampleRate ~/ 1000;
    return samples.length <= max ? samples : Float32List.sublistView(samples, 0, max);
  }

  Float32List _gather(Float32List speech, List<(int, int)> spans) {
    final pieces = <Float32List>[];
    var total = 0;
    for (final (from, to) in spans) {
      final a = (from * kAsrSampleRate ~/ 1000).clamp(0, speech.length);
      final b = (to * kAsrSampleRate ~/ 1000).clamp(0, speech.length);
      if (b <= a) continue;
      pieces.add(Float32List.sublistView(speech, a, b));
      total += b - a;
    }
    final out = Float32List(total);
    var at = 0;
    for (final piece in pieces) {
      out.setRange(at, at + piece.length, piece);
      at += piece.length;
    }
    return out;
  }
}
