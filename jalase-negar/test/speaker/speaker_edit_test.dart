import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/speaker/overlap_planner.dart';
import 'package:jalase_negar/core/speaker/speaker_matcher.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';
import 'package:jalase_negar/features/meetings/data/precise_labels.dart';
import 'package:jalase_negar/features/meetings/data/speaker_edit.dart';
import 'package:jalase_negar/features/people/data/enrollment_quality.dart';

Segment seg(
  int a,
  int b,
  String text, {
  String? speaker,
  String? pid,
  bool manual = false,
}) => Segment(
  channel: 0,
  startMs: a,
  endMs: b,
  text: text,
  speaker: speaker,
  speakerPersonId: pid,
  speakerManual: manual,
  speakerConfidence: speaker == null ? null : 70,
);

void main() {
  group('speaker edit', () {
    test('assign marks the line manual with full confidence', () {
      final out = assignSpeaker(
        [seg(0, 1000, 'سلام', speaker: 'ناشناس 1')],
        0,
        const SpeakerChoice(name: 'علی', personId: 'p1'),
      );
      expect(out.single.speaker, 'علی');
      expect(out.single.speakerPersonId, 'p1');
      expect(out.single.speakerManual, isTrue);
      expect(out.single.speakerConfidence, 100);
    });

    test('naming an unknown renames every line of that speaker', () {
      final out = assignSpeaker(
        [
          seg(0, 1000, 'الف', speaker: 'ناشناس 1'),
          seg(1000, 2000, 'ب', speaker: 'ناشناس 2'),
          seg(2000, 3000, 'ج', speaker: 'ناشناس 1'),
        ],
        0,
        const SpeakerChoice(name: 'سارا'),
        allWithSameLabel: true,
      );
      expect(out.map((s) => s.speaker), ['سارا', 'ناشناس 2', 'سارا']);
    });

    test('removing the speaker clears it', () {
      final out = assignSpeaker([seg(0, 1000, 'x', speaker: 'علی')], 0, null);
      expect(out.single.speaker, isNull);
      expect(out.single.speakerManual, isTrue);
    });

    test('split cuts text, shares time, both lines manual', () {
      final out = splitToTwoSpeakers(
        [seg(0, 4000, 'سلام خوبی من خوبم', speaker: 'ناشناس 1')],
        0,
        offset: suggestSplitOffset('سلام خوبی من خوبم'),
        first: const SpeakerChoice(name: 'علی', personId: 'a'),
        second: const SpeakerChoice(name: 'سارا', personId: 'b'),
      );
      expect(out, hasLength(2));
      expect(out[0].speaker, 'علی');
      expect(out[1].speaker, 'سارا');
      expect(out[0].endMs, out[1].startMs);
      expect(out.first.startMs, 0);
      expect(out.last.endMs, 4000);
      expect(out.every((s) => s.speakerManual), isTrue);
      expect('${out[0].text} ${out[1].text}', 'سلام خوبی من خوبم');
    });

    test('split of a one-word line is a no-op', () {
      final input = [seg(0, 1000, 'سلام')];
      final out = splitToTwoSpeakers(
        input,
        0,
        offset: 0,
        first: const SpeakerChoice(name: 'a'),
        second: const SpeakerChoice(name: 'b'),
      );
      expect(out, same(input));
    });

    test('labelled text and speakers list', () {
      final segs = [
        seg(0, 1000, 'سلام', speaker: 'علی', pid: 'a'),
        seg(1000, 2000, 'درود', speaker: 'ناشناس 1'),
        seg(2000, 3000, 'باز', speaker: 'علی', pid: 'a'),
      ];
      expect(
        labeledTranscriptText(segs),
        'علی: سلام\nناشناس 1: درود\nعلی: باز',
      );
      expect(speakersIn(segs).map((c) => c.name), ['علی', 'ناشناس 1']);
    });

    test('overlap share', () {
      final segs = [
        seg(0, 3000, 'a'),
        Segment(
          channel: 0,
          startMs: 3000,
          endMs: 4000,
          text: 'b',
          overlap: true,
        ),
      ];
      expect(overlapShare(segs), closeTo(0.25, 1e-9));
    });
  });

  group('precise labels', () {
    const ali = SpeakerIdentity(name: 'علی', personId: 'a', confidence: 90);
    const sara = SpeakerIdentity(name: 'سارا', personId: 'b', confidence: 80);
    const analysis = PreciseAnalysis(
      turns: [
        SpeakerTurn(startMs: 0, endMs: 3000, speaker: 0),
        SpeakerTurn(startMs: 3000, endMs: 6000, speaker: 1),
      ],
      identities: {0: ali, 1: sara},
    );

    test('relabels by dominant cluster', () {
      final out = applyPreciseLabels([
        seg(0, 2900, 'یک', speaker: 'ناشناس 1'),
        seg(3100, 5900, 'دو', speaker: 'ناشناس 1'),
      ], analysis);
      expect(out.map((s) => s.speaker), ['علی', 'سارا']);
      expect(out.map((s) => s.speakerPersonId), ['a', 'b']);
    });

    test('manual lines are never touched', () {
      final manual = seg(0, 2900, 'یک', speaker: 'X', manual: true);
      final out = applyPreciseLabels([manual], analysis);
      expect(out.single.speaker, 'X');
      expect(out.single.speakerManual, isTrue);
    });

    test('a second voice heard long enough makes an overlap line', () {
      final out = applyPreciseLabels([seg(2000, 4500, 'همزمان')], analysis);
      expect(out.single.overlap, isTrue);
      expect({out.single.speaker, out.single.speaker2}, {'علی', 'سارا'});
      expect(out.single.speakerConfidence, lessThanOrEqualTo(45));
    });

    test('a line outside the analysis keeps its label', () {
      final out = applyPreciseLabels([
        seg(9000, 9500, 'دیر', speaker: 'ناشناس 3'),
      ], analysis);
      expect(out.single.speaker, 'ناشناس 3');
    });
  });

  group('enrollment quality', () {
    Float32List tone(double seconds, double amp, {double noise = 0.0005}) {
      final n = (16000 * seconds).round();
      final rnd = math.Random(1);
      return Float32List.fromList([
        for (var i = 0; i < n; i++)
          // Syllable-like bursts so the energy detector finds speech.
          ((i ~/ 4000) % 2 == 0
                  ? amp * math.sin(2 * math.pi * 200 * i / 16000)
                  : 0.0) +
              (rnd.nextDouble() - 0.5) * noise,
      ]);
    }

    test('silence is too quiet', () {
      final r = assessEnrollmentSample(Float32List(16000 * 12));
      expect(r.ok, isFalse);
      expect(r.issue, EnrollmentIssue.tooQuiet);
      expect(r.messageFa, isNotEmpty);
    });

    test('a short clip is too short', () {
      final r = assessEnrollmentSample(tone(3, 0.3));
      expect(r.issue, EnrollmentIssue.tooShort);
    });

    test('clipping is rejected', () {
      final s = tone(30, 0.3);
      for (var i = 0; i < s.length; i += 20) {
        s[i] = 1.0;
      }
      expect(assessEnrollmentSample(s).issue, EnrollmentIssue.clipped);
    });

    test('a long clean clip passes with a quality score', () {
      final r = assessEnrollmentSample(tone(30, 0.3));
      expect(
        r.issue,
        EnrollmentIssue.ok,
        reason: '${r.speechMs}ms ${r.snrDb}dB',
      );
      expect(r.quality, inInclusiveRange(1, 100));
    });
  });
}
