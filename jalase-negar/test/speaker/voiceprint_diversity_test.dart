import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/speaker/voiceprint_diversity.dart';

/// A unit-ish vector pointing mostly along axis [axis], tilted by [tilt]
/// towards axis 7 so samples of one condition are alike but not identical.
Float32List _v(int axis, {double tilt = 0}) {
  final out = Float32List(8);
  out[axis] = 1;
  out[7] += tilt;
  return out;
}

VoiceSample _s(
  String id,
  Float32List e, {
  int day = 1,
  bool protected = false,
  int? quality,
  int? ms,
}) => VoiceSample(
  id: id,
  embedding: e,
  createdAt: DateTime(2026, 11, day),
  protected: protected,
  quality: quality,
  durationMs: ms,
);

void main() {
  const policy = DiversityPolicy(perGroup: 3, maxTotal: 12);

  test('five alike samples keep three: the longest ones', () {
    final samples = [
      for (var i = 0; i < 5; i++)
        _s('a$i', _v(0, tilt: 0.02 * i), ms: 1000 * (i + 1)),
    ];
    final remove = voiceSamplesToRemove(samples, policy);
    expect(remove.toSet(), {'a0', 'a1'});
  });

  test('different conditions are kept even when each has only a few', () {
    final samples = [
      for (var c = 0; c < 4; c++)
        for (var i = 0; i < 3; i++) _s('c$c-$i', _v(c, tilt: 0.01 * i)),
    ];
    // 4 conditions x 3 = 12: nothing to remove.
    expect(voiceSamplesToRemove(samples, policy), isEmpty);
  });

  test('protected samples are never removed and count towards the cap', () {
    final samples = [
      for (var i = 0; i < 4; i++)
        _s('p$i', _v(0, tilt: 0.01 * i), protected: true, quality: 90),
      _s('m0', _v(0, tilt: 0.05), ms: 9000),
    ];
    final remove = voiceSamplesToRemove(samples, policy);
    expect(remove, ['m0']);
    expect(remove.any((id) => id.startsWith('p')), isFalse);
  });

  test('over the person-wide limit the most crowded group shrinks first', () {
    final samples = [
      for (var c = 0; c < 5; c++)
        for (var i = 0; i < 3; i++)
          _s('c$c-$i', _v(c, tilt: 0.01 * i), ms: 1000 * (3 - i)),
    ]; // 15 samples, 5 equally sized groups, limit 12
    final remove = voiceSamplesToRemove(samples, policy);
    expect(remove.length, 3);
    // Every condition still has at least two samples.
    for (var c = 0; c < 5; c++) {
      final left = [
        for (var i = 0; i < 3; i++)
          if (!remove.contains('c$c-$i')) i,
      ];
      expect(left.length, greaterThanOrEqualTo(2));
    }
  });

  test('the result does not depend on the order of the input', () {
    final samples = [
      for (var i = 0; i < 6; i++) _s('a$i', _v(0, tilt: 0.02 * i), ms: 500 * i),
      for (var i = 0; i < 2; i++) _s('b$i', _v(3, tilt: 0.02 * i)),
    ];
    final forward = voiceSamplesToRemove(samples, policy).toSet();
    final backward = voiceSamplesToRemove(
      samples.reversed.toList(),
      policy,
    ).toSet();
    expect(backward, forward);
  });

  test('embeddings of another length never join a group', () {
    final other = Float32List(4)..[0] = 1;
    final groups = groupVoiceSamples([_s('x', _v(0)), _s('y', other)], policy);
    expect(groups.length, 2);
  });

  test('a looser join similarity merges conditions', () {
    final samples = [
      _s('a', _v(0, tilt: 0.9)), // tilted far towards axis 7
      _s('b', _v(1, tilt: 0.9)),
    ];
    expect(groupVoiceSamples(samples, policy).length, 2);
    expect(
      groupVoiceSamples(
        samples,
        const DiversityPolicy(joinSimilarity: 0.3),
      ).length,
      1,
    );
  });
}
