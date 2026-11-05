import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';
import 'package:jalase_negar/features/meetings/data/speaker_discovery.dart';
import 'package:jalase_negar/features/meetings/data/speaker_edit.dart';

Segment seg(String? who, int from, int to, {bool overlap = false, String? id}) =>
    Segment(
      channel: 0,
      startMs: from,
      endMs: to,
      text: 'متن $from',
      speaker: who,
      speakerPersonId: id,
      overlap: overlap,
    );

void main() {
  test('finds numbered unknown voices, most talkative first', () {
    final list = detectUnnamedSpeakers([
      seg('ناشناس 1', 0, 3000),
      seg('ناشناس 2', 3000, 12000),
      seg('ناشناس 1', 12000, 14000),
      seg('علی', 14000, 20000, id: 'p1'),
      seg('ناشناس', 20000, 21000),
      seg('ناشناس 3', 21000, 22000, overlap: true),
    ]);
    expect(list.map((d) => d.label), ['ناشناس 2', 'ناشناس 1', 'ناشناس 3']);
    expect(list[0].usable, isTrue);
    expect(list[1].lineCount, 2);
    expect(list[1].usable, isTrue); // 5 s
    expect(list[2].usable, isFalse); // overlap only
  });

  test('voiceprint groups skip overlaps and spread over the meeting', () {
    final segments = [
      for (var i = 0; i < 10; i++) seg('ناشناس 1', i * 5000, i * 5000 + 4500),
      seg('ناشناس 1', 60000, 70000, overlap: true),
    ];
    final groups = voiceprintGroups(segments, 'ناشناس 1');
    expect(groups.length, 3);
    for (final g in groups) {
      expect(g.fold<int>(0, (a, s) => a + s[1] - s[0]), greaterThanOrEqualTo(8000));
      expect(g.every((s) => s[0] < 60000), isTrue);
    }
    expect(voiceprintGroups(segments, 'ناشناس 9'), isEmpty);
  });

  test('naming gives every line of that voice to the person', () {
    final segments = [
      seg('ناشناس 1', 0, 3000),
      seg('ناشناس 2', 3000, 6000),
      seg('ناشناس 1', 6000, 9000),
    ];
    final named = nameDetectedSpeaker(
      segments,
      'ناشناس 1',
      const SpeakerChoice(name: 'سارا', personId: 'p9'),
    );
    expect(named.map((s) => s.speaker), ['سارا', 'ناشناس 2', 'سارا']);
    expect(named[0].speakerPersonId, 'p9');
    expect(named[0].speakerManual, isTrue);
  });
}
