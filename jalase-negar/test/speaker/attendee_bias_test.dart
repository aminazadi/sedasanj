import 'dart:math' as math;

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/speaker/speaker_matcher.dart';
import 'package:jalase_negar/features/people/data/person.dart';

import 'speaker_labeler_test.dart' show unit;

/// A unit vector at [degrees] from the first axis, so cosine scores are
/// cos(difference of angles) and easy to reason about.
List<double> at(double degrees) {
  final r = degrees * math.pi / 180;
  return [math.cos(r), math.sin(r)];
}

EnrolledVoice voice(String id, double degrees, {bool preferred = false}) =>
    EnrolledVoice(
      personId: id,
      name: id,
      centroid: unit(at(degrees)),
      samples: 3,
      preferred: preferred,
    );

void main() {
  // Ali at 0 degrees, Sara at 70. A voice at 33 degrees scores 0.84 against
  // Ali and 0.80 against Sara: too close to call without more information.
  final ambiguous = unit(at(33));

  test('an ambiguous voice stays unknown when nobody is marked present', () {
    final matcher = SpeakerMatcher([voice('ali', 0), voice('sara', 70)]);
    expect(matcher.identify(ambiguous).personId, isNull);
  });

  test('the same voice goes to the attendee when only they are present', () {
    final matcher = SpeakerMatcher([
      voice('ali', 0, preferred: true),
      voice('sara', 70),
    ]);
    expect(matcher.identify(ambiguous).personId, 'ali');
  });

  test('a non-attendee is still recognised when clearly the best match', () {
    final matcher = SpeakerMatcher([
      voice('ali', 0, preferred: true),
      voice('sara', 70),
    ]);
    expect(matcher.identify(unit(at(70))).personId, 'sara');
  });

  test('the boost never changes the confidence scale', () {
    final plain = SpeakerMatcher([voice('ali', 0), voice('sara', 90)]);
    final boosted = SpeakerMatcher([
      voice('ali', 0, preferred: true),
      voice('sara', 90),
    ]);
    final probe = unit(at(5));
    expect(
      boosted.identify(probe).confidence,
      plain.identify(probe).confidence,
    );
  });

  test('the preferred flag survives the isolate map round trip', () {
    final v = voice('ali', 0, preferred: true);
    expect(EnrolledVoice.fromMap(v.toMap()).preferred, isTrue);
    expect(EnrolledVoice.fromMap(voice('x', 0).toMap()).preferred, isFalse);
    expect(v.asPreferred(false).preferred, isFalse);
  });
}
