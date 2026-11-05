import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/asr/asr_common.dart';
import 'package:jalase_negar/core/speaker/overlap_planner.dart';
import 'package:jalase_negar/core/speaker/speaker_labeler.dart';
import 'package:jalase_negar/core/speaker/speaker_matcher.dart';
import 'package:jalase_negar/features/people/data/person.dart';

/// Audio where each speaker has its own constant sample value, so a fake
/// embedder can tell who is in a stretch (and a blend of two voices).
const double aliVoice = 0.1;
const double saraVoice = 0.2;

Float32List audio(List<(double, double)> secondsAndValue) {
  final pieces = <double>[];
  for (final (seconds, value) in secondsAndValue) {
    pieces.addAll(List.filled((seconds * kAsrSampleRate).round(), value));
  }
  return Float32List.fromList(pieces);
}

Float32List unit(List<double> v) => Float32List.fromList(v);

class FakeEmbedder implements VoiceEmbedder {
  final List<double> seen = [];

  @override
  Float32List? embed(Float32List samples) {
    if (samples.isEmpty) return null;
    var sum = 0.0;
    for (final s in samples) {
      sum += s;
    }
    final mean = sum / samples.length;
    seen.add(mean);
    // 0.1 -> Ali axis, 0.2 -> Sara axis, a blend sits between them.
    final ali = (0.2 - mean) / 0.1;
    final sara = (mean - 0.1) / 0.1;
    return unit([
      ali.clamp(0, 1).toDouble(),
      sara.clamp(0, 1).toDouble(),
      0.05,
    ]);
  }
}

class FakeDiarizer implements UtteranceDiarizer {
  FakeDiarizer(this.turns);
  final List<SpeakerTurn> turns;
  int calls = 0;

  @override
  List<SpeakerTurn> diarize(Float32List samples) {
    calls++;
    return turns;
  }
}

final enrolled = [
  EnrolledVoice(
    personId: 'ali',
    name: 'علی',
    centroid: unit([1, 0, 0.05]),
    samples: 3,
  ),
  EnrolledVoice(
    personId: 'sara',
    name: 'سارا',
    centroid: unit([0, 1, 0.05]),
    samples: 3,
  ),
];

void main() {
  group('SpeakerMatcher', () {
    test('names an enrolled voice with a confident score', () {
      final id = SpeakerMatcher(enrolled).identify(unit([1, 0.05, 0.05]));
      expect(id.name, 'علی');
      expect(id.personId, 'ali');
      expect(id.confidence, greaterThan(60));
    });

    test('a voice that matches nobody is an unknown, never a guess', () {
      final m = SpeakerMatcher(enrolled);
      final id = m.identify(unit([0, 0, 1]));
      expect(id.known, isFalse);
      expect(id.name, 'ناشناس 1');
      // The same stranger keeps the same label; a different one gets the next.
      expect(m.identify(unit([0.02, 0, 1])).name, 'ناشناس 1');
      expect(m.identify(unit([0, 1, 0.05])).known, isTrue);
      expect(m.identify(unit([-1, 0, 0])).name, 'ناشناس 2');
    });

    test('two similar enrolled voices are not guessed between', () {
      final twins = [
        EnrolledVoice(
          personId: 'a',
          name: 'الف',
          centroid: unit([1, 0.02, 0]),
          samples: 2,
        ),
        EnrolledVoice(
          personId: 'b',
          name: 'ب',
          centroid: unit([1, -0.02, 0]),
          samples: 2,
        ),
      ];
      expect(SpeakerMatcher(twins).identify(unit([1, 0, 0])).known, isFalse);
    });

    test('an unreliable match never gets a high confidence', () {
      final id = SpeakerMatcher(
        enrolled,
      ).identify(unit([1, 0, 0.05]), reliable: false);
      expect(id.known, isTrue);
      expect(id.confidence, lessThanOrEqualTo(55));
    });

    test('with nobody enrolled every voice is an unknown', () {
      final m = SpeakerMatcher(const []);
      expect(m.hasEnrolled, isFalse);
      expect(m.identify(unit([1, 0, 0])).name, 'ناشناس 1');
    });
  });

  group('SpeakerLabeler', () {
    SpeakerLabeler labeler({
      List<SpeakerTurn>? turns,
      FakeEmbedder? embedder,
    }) => SpeakerLabeler(
      diarizer: turns == null ? null : FakeDiarizer(turns),
      embedder: embedder ?? FakeEmbedder(),
      matcher: SpeakerMatcher(enrolled),
    );

    test('a single-speaker utterance becomes one named part', () {
      final parts = labeler().label(audio([(3, aliVoice)]), startMs: 10000);
      expect(parts, hasLength(1));
      expect(parts.single.startMs, 10000);
      expect(parts.single.endMs, 13000);
      expect(parts.single.speakers.single.name, 'علی');
      expect(parts.single.overlap, isFalse);
    });

    test('a speaker change splits the utterance and names both people', () {
      final speech = audio([(3, aliVoice), (4, saraVoice)]);
      final parts = labeler(
        turns: [
          const SpeakerTurn(startMs: 0, endMs: 3000, speaker: 0),
          const SpeakerTurn(startMs: 3000, endMs: 7000, speaker: 1),
        ],
      ).label(speech, startMs: 0);
      expect(parts.map((p) => p.speakers.single.name), ['علی', 'سارا']);
      expect(parts.first.endMs, parts.last.startMs);
      expect(parts.first.startMs, 0);
      expect(parts.last.endMs, 7000);
    });

    test('overlap is labelled with both people and low confidence', () {
      // Ali 0–4 s, Sara 3–7 s; the mixed second sounds like their blend.
      final speech = audio([(3, aliVoice), (1, 0.15), (3, saraVoice)]);
      final embedder = FakeEmbedder();
      final parts = labeler(
        turns: [
          const SpeakerTurn(startMs: 0, endMs: 4000, speaker: 0),
          const SpeakerTurn(startMs: 3000, endMs: 7000, speaker: 1),
        ],
        embedder: embedder,
      ).label(speech, startMs: 0);

      expect(parts, hasLength(3));
      final middle = parts[1];
      expect(middle.overlap, isTrue);
      expect(middle.speakers.map((s) => s.name), ['علی', 'سارا']);
      expect(middle.confidence, lessThanOrEqualTo(45));
      // The embeddings never saw the mixed second: only clean audio was used.
      expect(embedder.seen.any((m) => (m - 0.15).abs() < 0.01), isFalse);
      expect(parts.first.speakers.single.name, 'علی');
      expect(parts.last.speakers.single.name, 'سارا');
    });

    test('two diarization labels for one person become one line', () {
      final speech = audio([(3, aliVoice), (3, aliVoice)]);
      final parts = labeler(
        turns: [
          const SpeakerTurn(startMs: 0, endMs: 3000, speaker: 0),
          const SpeakerTurn(startMs: 3000, endMs: 6000, speaker: 1),
        ],
      ).label(speech, startMs: 0);
      expect(parts, hasLength(1));
      expect(parts.single.speakers.single.name, 'علی');
    });

    test(
      'a very short utterance carries the previous speaker with low confidence',
      () {
        final l = labeler();
        l.label(audio([(3, aliVoice)]), startMs: 0);
        final parts = l.label(audio([(0.4, saraVoice)]), startMs: 5000);
        expect(parts.single.speakers.single.name, 'علی');
        expect(parts.single.confidence, lessThanOrEqualTo(25));
      },
    );

    test('a short utterance is never segmented', () {
      final diarizer = FakeDiarizer(const []);
      final l = SpeakerLabeler(
        diarizer: diarizer,
        embedder: FakeEmbedder(),
        matcher: SpeakerMatcher(enrolled),
      );
      l.label(audio([(1.0, aliVoice)]), startMs: 0);
      expect(diarizer.calls, 0);
    });

    test('a failing segmentation model falls back to one speaker', () {
      final l = SpeakerLabeler(
        diarizer: _ThrowingDiarizer(),
        embedder: FakeEmbedder(),
        matcher: SpeakerMatcher(enrolled),
      );
      final parts = l.label(audio([(4, saraVoice)]), startMs: 0);
      expect(parts.single.speakers.single.name, 'سارا');
    });

    test('an unusable embedding gives an unknown, not a crash', () {
      final l = SpeakerLabeler(
        diarizer: null,
        embedder: _NullEmbedder(),
        matcher: SpeakerMatcher(enrolled),
      );
      final parts = l.label(audio([(3, aliVoice)]), startMs: 0);
      expect(parts.single.speakers.single.known, isFalse);
    });
  });
}

class _ThrowingDiarizer implements UtteranceDiarizer {
  @override
  List<SpeakerTurn> diarize(Float32List samples) => throw StateError('boom');
}

class _NullEmbedder implements VoiceEmbedder {
  @override
  Float32List? embed(Float32List samples) => null;
}
