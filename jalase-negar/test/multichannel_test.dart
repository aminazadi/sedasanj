import 'dart:typed_data';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/audio/multichannel_capture.dart';
import 'package:jalase_negar/core/asr/channel_gate.dart';
import 'package:jalase_negar/core/audio/pcm_channels.dart';

Uint8List _pcm(List<int> samples) {
  final b = ByteData(samples.length * 2);
  for (var i = 0; i < samples.length; i++) {
    b.setInt16(i * 2, samples[i], Endian.little);
  }
  return b.buffer.asUint8List();
}

List<int> _samples(Uint8List bytes) {
  final v = ByteData.sublistView(bytes);
  return [
    for (var i = 0; i < bytes.length ~/ 2; i++)
      v.getInt16(i * 2, Endian.little),
  ];
}

void main() {
  group('PcmDeinterleaver', () {
    test('splits four channels', () {
      final d = PcmDeinterleaver(4);
      final out = d.split(_pcm([1, 2, 3, 4, 5, 6, 7, 8]));
      expect(out.map(_samples).toList(), [
        [1, 5],
        [2, 6],
        [3, 7],
        [4, 8],
      ]);
    });

    test('keeps a partial frame for the next call', () {
      final d = PcmDeinterleaver(2);
      final all = _pcm([10, 20, 30, 40, 50, 60]);
      final a = d.split(Uint8List.sublistView(all, 0, 5));
      final b = d.split(Uint8List.sublistView(all, 5));
      expect(_samples(a[0]) + _samples(b[0]), [10, 30, 50]);
      expect(_samples(a[1]) + _samples(b[1]), [20, 40, 60]);
    });

    test('mono passes through and zero channels is rejected', () {
      final out = PcmDeinterleaver(1).split(_pcm([7, 8, 9]));
      expect(_samples(out.single), [7, 8, 9]);
      expect(() => PcmDeinterleaver(0), throwsArgumentError);
    });
  });

  group('interleavePcm', () {
    test('is the inverse of the deinterleaver', () {
      final original = _pcm([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
      final split = PcmDeinterleaver(3).split(original);
      expect(interleavePcm(split), original);
    });

    test('silencing one channel keeps the others in place', () {
      final split = PcmDeinterleaver(2).split(_pcm([1, 2, 3, 4, 5, 6]));
      split[1] = Uint8List(split[1].length);
      expect(_samples(interleavePcm(split)), [1, 0, 3, 0, 5, 0]);
    });
  });

  group('ChannelGate', () {
    const gate = ChannelGate();

    test('only the loudest channel owns a window with bleed', () {
      expect(gate.owners([0.20, 0.03, 0.02]), {0});
    });

    test('two close voices are both kept', () {
      expect(gate.owners([0.20, 0.15, 0.01]), {0, 1});
    });

    test('silence owns nothing', () {
      expect(gate.owners([0.001, 0.002]), isEmpty);
    });

    test('pcm16Rms measures level', () {
      expect(pcm16Rms(Uint8List(0)), 0);
      expect(pcm16Rms(_pcm([16384, -16384])), closeTo(0.5, 1e-6));
    });
  });

  group('ChannelMixdown', () {
    final loud = List<int>.filled(640, 8000);
    final bleed = List<int>.filled(640, 500);
    final quiet = List<int>.filled(640, 20);

    test('keeps the speaking channel and drops bleed', () {
      final out = ChannelMixdown().mix([_pcm(loud), _pcm(bleed)]);
      expect(_samples(out).every((x) => x == 8000), isTrue);
    });

    test('two close voices are summed with sqrt scaling', () {
      final out = _samples(ChannelMixdown().mix([_pcm(loud), _pcm(loud)]));
      expect(out.first, closeTo(8000 * 2 / 1.41421356, 2));
    });

    test(
      'the same loud voice on two channels is limited, not hard-clipped',
      () {
        final hot = List<int>.filled(640, 30000);
        final out = _samples(ChannelMixdown().mix([_pcm(hot), _pcm(hot)]));
        // 30000 * sqrt(2) = 42426 would be cut flat at 32767; it is eased.
        expect(out.first, lessThan(32767));
        expect(out.first, greaterThan(30000));
      },
    );

    test('silence falls back to the average of all channels', () {
      final out = _samples(
        ChannelMixdown().mix([_pcm(quiet), _pcm(List<int>.filled(640, 40))]),
      );
      expect(out.first, 30);
    });

    test('a muted channel neither speaks nor dilutes the average', () {
      final mix = ChannelMixdown();
      // Channel 0 is loud but muted: the quiet channel decides alone.
      final out = _samples(mix.mix([_pcm(loud), _pcm(quiet)], muted: {0}));
      expect(out.first, 20);
      // Nothing left to mix: silence of the same length.
      final none = mix.mix([_pcm(loud), _pcm(loud)], muted: {0, 1});
      expect(none.length, 1280);
      expect(_samples(none).every((x) => x == 0), isTrue);
    });

    test('output length matches the input', () {
      expect(ChannelMixdown().mix([_pcm(loud), _pcm(loud)]).length, 1280);
      expect(ChannelMixdown().mix(const []), isEmpty);
    });
  });

  group('softLimit', () {
    test('is transparent below the knee and bounded above it', () {
      expect(softLimit(1000), 1000);
      expect(softLimit(-20000), -20000);
      expect(softLimit(kLimiterKnee), kLimiterKnee.round());
      expect(softLimit(1e9), lessThanOrEqualTo(32767));
      expect(softLimit(-1e9), greaterThanOrEqualTo(-32767));
      // Monotonic through the knee.
      var last = -40000;
      for (var x = 0.0; x < 60000; x += 500) {
        final y = softLimit(x);
        expect(y, greaterThanOrEqualTo(last));
        last = y;
      }
    });
  });

  group('ChannelProbe', () {
    // Two seconds of 16 kHz audio, so one call completes a window.
    const n = 32000;
    List<int> voice(int seed, {double gain = 1}) {
      var x = seed;
      return [
        for (var i = 0; i < n; i++)
          (() {
            x = (x * 1103515245 + 12345) & 0x7fffffff;
            return (((x >> 8) % 2001) - 1000) * gain ~/ 1;
          })(),
      ];
    }

    ChannelProbe probe() => ChannelProbe(2);

    test('independent microphones are both fine', () {
      final p = probe();
      p.add([_pcm(voice(1)), _pcm(voice(2))]);
      expect(p.health, [ChannelHealth.ok, ChannelHealth.ok]);
    });

    test('a copy of the first channel is flagged', () {
      final p = probe();
      final a = voice(3);
      final changed = p.add([_pcm(a), _pcm(a)]);
      expect(changed, isTrue);
      expect(p.health, [ChannelHealth.ok, ChannelHealth.duplicate]);
    });

    test('a quieter copy is still a copy', () {
      final p = probe();
      final a = voice(4);
      p.add([
        _pcm(a),
        _pcm([for (final v in a) v ~/ 2]),
      ]);
      expect(p.health[1], ChannelHealth.duplicate);
    });

    test('digital silence is dead, a noisy quiet room is not', () {
      final p = probe();
      p.add([_pcm(voice(5)), _pcm(List<int>.filled(n, 0))]);
      expect(p.health, [ChannelHealth.ok, ChannelHealth.dead]);
      final q = probe();
      q.add([_pcm(voice(6, gain: 0.02)), _pcm(voice(7, gain: 0.02))]);
      expect(q.health, [ChannelHealth.ok, ChannelHealth.ok]);
    });

    test('a channel recovers when its transmitter is switched on', () {
      final p = probe();
      p.add([_pcm(voice(8)), _pcm(List<int>.filled(n, 0))]);
      expect(p.health[1], ChannelHealth.dead);
      final changed = p.add([_pcm(voice(9)), _pcm(voice(10))]);
      expect(changed, isTrue);
      expect(p.health, [ChannelHealth.ok, ChannelHealth.ok]);
    });

    test('a copy verdict survives a window where nobody spoke', () {
      final p = probe();
      final a = voice(11);
      p.add([_pcm(a), _pcm(a)]);
      p.add([_pcm(voice(12, gain: 0.01)), _pcm(voice(13, gain: 0.01))]);
      expect(p.health[1], ChannelHealth.duplicate);
    });

    test('nothing is decided before a full window', () {
      final p = probe();
      final short = voice(14).sublist(0, 8000);
      expect(p.add([_pcm(short), _pcm(short)]), isFalse);
      expect(p.health, [ChannelHealth.ok, ChannelHealth.ok]);
    });
  });

  group('MultichannelCapture', () {
    TestWidgetsFlutterBinding.ensureInitialized();
    const channel = MethodChannel('jalase/multichannel_capture');

    test('lists sources and starts with the real channel count', () async {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (call) async {
            if (call.method == 'listInputs') {
              return [
                {
                  'uid': 'u1',
                  'name': 'Scarlett 18i20',
                  'channels': 18,
                  'sampleRate': 48000.0,
                },
              ];
            }
            if (call.method == 'start') {
              return {
                'channels': 18,
                'sampleRate': 16000,
                'deviceRate': 48000.0,
              };
            }
            return null;
          });
      final cap = MultichannelCapture(supported: true);
      final sources = await cap.listSources();
      expect(sources.single.channels, 18);
      final info = await cap.start(['u1']);
      expect(info.channels, 18);
      expect(info.sampleRate, 16000);
    });

    test('the phone microphone is flagged so it is never opened alone', () {
      final phone = CaptureSource.fromMap(const {
        'uid': '7',
        'name': 'Phone microphone',
        'channels': 1,
        'sampleRate': 48000.0,
        'builtIn': true,
      });
      final usb = CaptureSource.fromMap(const {
        'uid': '9',
        'name': 'Wireless microphone',
        'channels': 2,
        'sampleRate': 48000.0,
        'builtIn': false,
      });
      expect(phone.builtIn, isTrue);
      expect(usb.builtIn, isFalse);
    });

    test('unsupported platforms list nothing', () async {
      expect(
        await MultichannelCapture(supported: false).listSources(),
        isEmpty,
      );
    });
  });
}
