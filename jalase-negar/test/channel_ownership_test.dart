import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/asr/consolidate.dart';
import 'package:jalase_negar/core/audio/channel_ownership.dart';
import 'package:jalase_negar/core/audio/pcm_channels.dart';
import 'package:jalase_negar/core/speaker/speaker_matcher.dart';

const ali = SpeakerIdentity(name: 'علی', personId: 'p-ali');
const sara = SpeakerIdentity(name: 'سارا', personId: 'p-sara');

Uint8List tone(int samples, int amp) {
  final d = ByteData(samples * 2);
  for (var i = 0; i < samples; i++) {
    d.setInt16(i * 2, i.isEven ? amp : -amp, Endian.little);
  }
  return d.buffer.asUint8List();
}

void main() {
  test('a handover applies from that moment on only', () {
    final a = ChannelAssignments()
      ..assign(0, ali, atMs: 0)
      ..assign(0, sara, atMs: 5000);
    expect(a.ownerAt(0, 1000)?.name, 'علی');
    expect(a.ownerAt(0, 4999)?.name, 'علی');
    expect(a.ownerAt(0, 5000)?.name, 'سارا');
    expect(a.currentOwner(0)?.name, 'سارا');
    expect(a.ownerAt(1, 9000), isNull);
  });

  test('removing the owner brings automatic detection back', () {
    final a = ChannelAssignments()
      ..assign(0, ali, atMs: 0)
      ..assign(0, null, atMs: 3000);
    expect(a.ownerAt(0, 4000), isNull);
    expect(a.isEmpty, isTrue);
  });

  test('one microphone: the owner owns every line, nobody means automatic', () {
    final a = ChannelAssignments();
    final o = ChannelOwnership(assignments: a);
    expect(o.ownersOf(0, 1000), isNull);
    a.assign(0, ali, atMs: 2000);
    expect(o.ownersOf(0, 1000), isNull);
    expect(o.ownersOf(2500, 3500)?.first.name, 'علی');
    expect(o.ownersOf(2500, 3500)?.first.confidence, 100);
  });

  test('a line is named after the channel that carried the voice', () {
    final log = ChannelActivityLog();
    // 0-2 s channel 0, 2-4 s channel 1 (16 kHz).
    log.add(0, 32000, channelMask([0]));
    log.add(32000, 32000, channelMask([1]));
    final a = ChannelAssignments()
      ..assign(0, ali, atMs: 0)
      ..assign(1, sara, atMs: 0);
    final o = ChannelOwnership(assignments: a, log: log);
    expect(o.ownersOf(200, 1800)?.first.name, 'علی');
    expect(o.ownersOf(2200, 3800)?.first.name, 'سارا');
    expect(o.ownersOf(200, 1800)?.second, isNull);
  });

  test('a loud channel nobody holds leaves the automatic label', () {
    final log = ChannelActivityLog()..add(0, 32000, channelMask([1]));
    final a = ChannelAssignments()..assign(0, ali, atMs: 0);
    expect(
      ChannelOwnership(assignments: a, log: log).ownersOf(0, 2000),
      isNull,
    );
  });

  test('two held microphones heard together make an overlap', () {
    final log = ChannelActivityLog()..add(0, 32000, channelMask([0, 1]));
    final a = ChannelAssignments()
      ..assign(0, ali, atMs: 0)
      ..assign(1, sara, atMs: 0);
    final owners = ChannelOwnership(assignments: a, log: log).ownersOf(0, 2000);
    expect(owners?.first.name, 'علی');
    expect(owners?.second?.name, 'سارا');
  });

  test('the mixdown logs which channel carried each block', () {
    final log = ChannelActivityLog();
    final mix = ChannelMixdown(log: log);
    mix.mix([tone(3200, 8000), tone(3200, 0)]);
    mix.mix([tone(3200, 0), tone(3200, 8000)]);
    expect(log.ownedMs(0, 200).keys, [0]);
    expect(log.ownedMs(200, 400).keys, [1]);
  });

  test('a muted channel is not logged as owner', () {
    final log = ChannelActivityLog();
    ChannelMixdown(
      log: log,
    ).mix([tone(3200, 8000), tone(3200, 800)], muted: {0});
    expect(log.ownedMs(0, 200).containsKey(0), isFalse);
  });

  test('owner-named turns are not merged with voice-named ones', () {
    AsrTurn turn(int s, bool manual) => AsrTurn(
      channel: 0,
      startMs: s,
      endMs: s + 500,
      text: 'متن $s',
      speaker: 'علی',
      speakerPersonId: 'p-ali',
      speakerManual: manual,
    );
    final merged = consolidateSegments([turn(0, true), turn(600, false)]);
    expect(merged.length, 2);
    expect(merged.first.speakerManual, isTrue);
    expect(consolidateSegments([turn(0, true), turn(600, true)]).length, 1);
  });
}
