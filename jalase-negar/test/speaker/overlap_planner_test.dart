import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/speaker/overlap_planner.dart';

SpeakerTurn t(int from, int to, int speaker) =>
    SpeakerTurn(startMs: from, endMs: to, speaker: speaker);

List<String> flat(List<PlannedPart> parts) => [
  for (final p in parts) '${p.startMs}-${p.endMs}:${p.speakers.join('+')}',
];

void main() {
  group('planParts', () {
    test('one speaker is one part', () {
      expect(flat(planParts([t(0, 4000, 0)])), ['0-4000:0']);
    });

    test('a speaker change splits the utterance at the change', () {
      final parts = planParts([t(0, 3000, 0), t(3000, 7000, 1)]);
      expect(flat(parts), ['0-3000:0', '3000-7000:1']);
    });

    test('overlap of at least half a second becomes its own two-speaker part', () {
      final parts = planParts([t(0, 4000, 0), t(3000, 7000, 1)]);
      expect(flat(parts), [
        '0-3000:0',
        '3000-4000:0+1',
        '4000-7000:1',
      ]);
      expect(parts[1].overlap, isTrue);
      expect(parts[0].overlap, isFalse);
    });

    test('a brief overlap goes to the speaker who keeps talking', () {
      // 300 ms of cross-talk at the hand-over: not worth a mixed line.
      final parts = planParts([t(0, 3300, 0), t(3000, 7000, 1)]);
      expect(parts.every((p) => !p.overlap), isTrue);
      expect(parts, hasLength(2));
      expect(parts.first.speakers, [0]);
      expect(parts.last.speakers, [1]);
    });

    test('a very short interjection is folded into the surrounding speaker', () {
      final parts = planParts([
        t(0, 4000, 0),
        t(4000, 4500, 1),
        t(4500, 9000, 0),
      ]);
      expect(flat(parts), ['0-9000:0']);
      expect(parts.single.shaky, isTrue);
    });

    test('silence between turns is not part of any part', () {
      final parts = planParts([t(0, 2000, 0), t(5000, 8000, 1)]);
      expect(flat(parts), ['0-2000:0', '5000-8000:1']);
    });

    test('three simultaneous speakers are reduced to two', () {
      final parts = planParts([t(0, 3000, 0), t(0, 3000, 1), t(0, 3000, 2)]);
      expect(parts.single.speakers, [0, 1]);
    });

    test('no turns, no parts', () {
      expect(planParts(const []), isEmpty);
      expect(planParts([t(1000, 1000, 0)]), isEmpty);
    });

    test('parts stay in time order and do not overlap each other', () {
      final parts = planParts([
        t(0, 5000, 0),
        t(2500, 9000, 1),
        t(8000, 12000, 0),
      ]);
      for (var i = 1; i < parts.length; i++) {
        expect(parts[i].startMs, greaterThanOrEqualTo(parts[i - 1].endMs));
      }
    });
  });

  group('cleanSpans', () {
    test('excludes the time the other speaker talks over', () {
      final turns = [t(0, 4000, 0), t(3000, 7000, 1)];
      expect(cleanSpans(turns, 0), [(0, 3000)]);
      expect(cleanSpans(turns, 1), [(4000, 7000)]);
    });

    test('joins adjacent clean stretches', () {
      expect(cleanSpans([t(0, 2000, 0), t(2000, 5000, 0)], 0), [(0, 5000)]);
    });
  });
}
