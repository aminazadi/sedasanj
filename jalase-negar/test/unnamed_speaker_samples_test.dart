import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';
import 'package:jalase_negar/features/meetings/data/speaker_discovery.dart';

Segment _s(int a, int b, {String who = 'ناشناس 1', bool overlap = false}) =>
    Segment(
      channel: 0,
      startMs: a,
      endMs: b,
      text: 'x',
      speaker: who,
      overlap: overlap,
    );

void main() {
  test('samples: clean first, longest first, capped, blips skipped', () {
    final out = unnamedSpeakerSamples([
      _s(0, 2000),
      _s(3000, 3300),
      _s(5000, 30000),
      _s(40000, 42000, overlap: true),
      _s(50000, 53000, who: 'ناشناس 2'),
    ], 'ناشناس 1');
    expect(out, [
      [5000, 17000],
      [0, 2000],
      [40000, 42000],
    ]);
  });

  test('sample lines carry the sentence and the overlap flag', () {
    final out = unnamedSpeakerSampleLines([
      Segment(
        channel: 0,
        startMs: 0,
        endMs: 2000,
        text: ' سلام ',
        speaker: 'ناشناس 1',
      ),
      _s(40000, 42000, overlap: true),
    ], 'ناشناس 1');
    expect(out.map((s) => s.text), ['سلام', 'x']);
    expect(out.map((s) => s.overlap), [false, true]);
  });
}
