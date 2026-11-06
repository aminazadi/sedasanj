import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/asr/asr_common.dart';
import 'package:jalase_negar/core/asr/live_asr_engine.dart';
import 'package:jalase_negar/core/asr/live_pipeline.dart';
import 'package:jalase_negar/core/asr/sound_events.dart';

/// Tagger that answers from a script: one list of scores per window, in order.
class ScriptedTagger implements SoundTagger {
  ScriptedTagger(this.script);

  final List<List<SoundScore>> script;
  int calls = 0;

  @override
  List<SoundScore> tag(Float32List samples) {
    final index = calls < script.length ? calls : script.length - 1;
    calls++;
    return script[index];
  }
}

SoundScore s(String name, double p) => SoundScore(name, p);

/// One second of a quiet tone, so the silence gate lets it through.
Float32List loud(int seconds) =>
    Float32List(seconds * kAsrSampleRate)
      ..fillRange(0, seconds * kAsrSampleRate, 0.05);

Float32List silent(int seconds) => Float32List(seconds * kAsrSampleRate);

/// Feeds [seconds] of loud audio one second at a time and collects events.
List<DetectedSoundEvent> run(SoundEventDetector d, int seconds) => [
  for (var i = 0; i < seconds; i++) ...d.accept(loud(1)),
];

void main() {
  group('table', () {
    test('every kind has a Persian label and a bracketed marker', () {
      for (final kind in kSoundEventKinds) {
        expect(kind.labelFa, isNotEmpty);
        expect(kind.marker, '[${kind.labelFa}]');
        expect(kind.threshold, inInclusiveRange(0.05, 0.95));
        expect(kind.minWindows, greaterThanOrEqualTo(1));
      }
      expect(
        kSoundEventKinds.map((k) => k.id).toSet().length,
        kSoundEventKinds.length,
      );
    });

    test('AudioSet names resolve to kinds, speech and music do not', () {
      expect(soundEventKindForName('Laughter')?.labelFa, 'خنده');
      expect(soundEventKindForName('Belly laugh')?.labelFa, 'قهقهه');
      expect(soundEventKindForName('Giggle')?.labelFa, 'ریزخنده');
      expect(soundEventKindForName('Snicker')?.labelFa, 'پوزخند');
      expect(soundEventKindForName('Chuckle, chortle')?.id, 'chuckle');
      expect(soundEventKindForName('Crying, sobbing')?.labelFa, 'گریه');
      expect(soundEventKindForName('Baby cry, infant cry')?.id, 'baby_cry');
      expect(soundEventKindForName('  cough ')?.labelFa, 'سرفه');
      expect(soundEventKindForName('Clapping')?.labelFa, 'تشویق');
      expect(soundEventKindForName('Speech'), isNull);
      expect(soundEventKindForName('Music'), isNull);
      expect(soundEventKindForName('Breathing'), isNull);
    });

    test('no AudioSet name is claimed by two kinds', () {
      final seen = <String>{};
      for (final kind in kSoundEventKinds) {
        for (final name in kind.audioSetNames) {
          expect(seen.add(name.toLowerCase()), isTrue, reason: name);
        }
      }
    });
  });

  group('detector', () {
    test('two agreeing windows make one laughter event with its time', () {
      final tagger = ScriptedTagger([
        [s('Speech', 0.9)],
        [s('Speech', 0.8), s('Laughter', 0.6)],
        [s('Laughter', 0.7)],
        [s('Speech', 0.9)],
        [s('Speech', 0.9)],
        [s('Speech', 0.9)],
      ]);
      final d = SoundEventDetector(tagger: tagger);
      final events = [...run(d, 9), ...d.flush()];
      expect(events, hasLength(1));
      expect(events.single.text, '[خنده]');
      expect(events.single.kind.id, 'laughter');
      expect(events.single.score, closeTo(0.7, 1e-9));
      // Windows end at 3 s (speech), 4 s and 5 s (laughter): their centres are
      // 2.5 s and 3.5 s, one hop of 1 s around each.
      expect(events.single.startMs, 2000);
      expect(events.single.endMs, 4000);
    });

    test('a single noisy window does not write a long sound', () {
      final d = SoundEventDetector(
        tagger: ScriptedTagger([
          [s('Laughter', 0.9)],
          [s('Speech', 0.9)],
        ]),
      );
      expect([...run(d, 8), ...d.flush()], isEmpty);
    });

    test('a short burst needs one window only (cough)', () {
      final d = SoundEventDetector(
        tagger: ScriptedTagger([
          [s('Cough', 0.8)],
          [s('Speech', 0.9)],
        ]),
      );
      final events = [...run(d, 8), ...d.flush()];
      expect(events.map((e) => e.text), ['[سرفه]']);
    });

    test('scores below the threshold are ignored', () {
      final d = SoundEventDetector(
        tagger: ScriptedTagger([
          [s('Laughter', 0.05), s('Cough', 0.19), s('Whispering', 0.29)],
        ]),
      );
      expect([...run(d, 10), ...d.flush()], isEmpty);
    });

    test('Giggle and Laughter together make one event, not two', () {
      final d = SoundEventDetector(
        tagger: ScriptedTagger([
          [s('Laughter', 0.5), s('Giggle', 0.7)],
          [s('Laughter', 0.6), s('Giggle', 0.5)],
          [s('Laughter', 0.6), s('Giggle', 0.55)],
          [s('Speech', 0.9)],
        ]),
      );
      final events = [...run(d, 10), ...d.flush()];
      expect(events, hasLength(1));
      // Per window only the stronger kind votes: Giggle once (0.7), Laughter
      // twice (1.2), so the event is named after Laughter.
      expect(events.single.kind.id, 'laughter');
    });

    test('a weak specific kind is written as the general one', () {
      final d = SoundEventDetector(
        tagger: ScriptedTagger([
          [s('Giggle', 0.12), s('Laughter', 0.09)],
          [s('Giggle', 0.11), s('Laughter', 0.08)],
          [s('Speech', 0.9)],
        ]),
      );
      final events = [...run(d, 10), ...d.flush()];
      // Giggle leads but never reached 0.30, so the word is «خنده».
      expect(events.map((e) => e.text), ['[خنده]']);
    });

    test('a cough read as throat clearing stays a cough unless sure', () {
      List<String> go(double p) {
        final d = SoundEventDetector(
          tagger: ScriptedTagger([
            [s('Throat clearing', p)],
            [s('Speech', 0.9)],
          ]),
        );
        return [...run(d, 8), ...d.flush()].map((e) => e.text).toList();
      }

      expect(go(0.30), ['[سرفه]']);
      expect(go(0.60), ['[صاف کردن گلو]']);
    });

    test('low laughter probability under speech is still written', () {
      // Measured: laughter mixed into speech at equal level scores about
      // 0.06-0.2, far below the 0.30 used before the benchmark.
      final d = SoundEventDetector(
        tagger: ScriptedTagger([
          [s('Speech', 0.95), s('Laughter', 0.07)],
          [s('Speech', 0.95), s('Laughter', 0.09)],
          [s('Speech', 0.95)],
        ]),
      );
      expect([...run(d, 9), ...d.flush()].map((e) => e.text), ['[خنده]']);
    });

    test('gasp is not written (breathing was read as a gasp)', () {
      expect(soundEventKindForName('Gasp'), isNull);
    });

    test('the specific kind names the event when it leads', () {
      final d = SoundEventDetector(
        tagger: ScriptedTagger([
          [s('Laughter', 0.4), s('Belly laugh', 0.8)],
          [s('Laughter', 0.5), s('Belly laugh', 0.7)],
          [s('Speech', 0.9)],
        ]),
      );
      final events = [...run(d, 10), ...d.flush()];
      expect(events.map((e) => e.text), ['[قهقهه]']);
    });

    test('a one-window gap keeps the same event open', () {
      final d = SoundEventDetector(
        tagger: ScriptedTagger([
          [s('Crying, sobbing', 0.6)],
          [s('Speech', 0.9)],
          [s('Crying, sobbing', 0.6)],
          [s('Speech', 0.9)],
          [s('Speech', 0.9)],
        ]),
      );
      final events = [...run(d, 10), ...d.flush()];
      expect(events.map((e) => e.text), ['[گریه]']);
      expect(events.single.endMs - events.single.startMs, 3000);
    });

    test('a two-window gap makes two events', () {
      final d = SoundEventDetector(
        tagger: ScriptedTagger([
          [s('Laughter', 0.6)],
          [s('Laughter', 0.6)],
          [s('Speech', 0.9)],
          [s('Speech', 0.9)],
          [s('Laughter', 0.6)],
          [s('Laughter', 0.6)],
          [s('Speech', 0.9)],
        ]),
      );
      final events = [...run(d, 14), ...d.flush()];
      expect(events.map((e) => e.text), ['[خنده]', '[خنده]']);
    });

    test('different groups at the same time are both written', () {
      final d = SoundEventDetector(
        tagger: ScriptedTagger([
          [s('Laughter', 0.6), s('Applause', 0.7)],
          [s('Laughter', 0.6), s('Applause', 0.7)],
          [s('Speech', 0.9)],
        ]),
      );
      final events = [...run(d, 9), ...d.flush()];
      expect(events.map((e) => e.text).toSet(), {'[خنده]', '[تشویق]'});
    });

    test('silence is never sent to the tagger', () {
      final tagger = ScriptedTagger([
        [s('Laughter', 0.9)],
      ]);
      final d = SoundEventDetector(tagger: tagger);
      expect(d.accept(silent(10)), isEmpty);
      expect(d.flush(), isEmpty);
      expect(tagger.calls, 0);
    });

    test('chunk size does not change the result', () {
      List<DetectedSoundEvent> go(int chunk) {
        final d = SoundEventDetector(
          tagger: ScriptedTagger([
            [s('Speech', 0.9)],
            [s('Laughter', 0.6)],
            [s('Laughter', 0.6)],
            [s('Speech', 0.9)],
          ]),
        );
        final audio = loud(9);
        final out = <DetectedSoundEvent>[];
        for (var i = 0; i < audio.length; i += chunk) {
          out.addAll(
            d.accept(
              Float32List.sublistView(
                audio,
                i,
                i + chunk > audio.length ? audio.length : i + chunk,
              ),
            ),
          );
        }
        return [...out, ...d.flush()];
      }

      final a = go(3200); // 200 ms, like the engine's batches
      final b = go(kAsrSampleRate * 4);
      expect(
        a.map((e) => '${e.text}${e.startMs}-${e.endMs}'),
        b.map((e) => '${e.text}${e.startMs}-${e.endMs}'),
      );
      expect(a, hasLength(1));
    });

    test('skip keeps the timeline and closes open events', () {
      final d = SoundEventDetector(
        tagger: ScriptedTagger([
          [s('Laughter', 0.6)],
        ]),
      );
      expect(run(d, 4), isEmpty); // windows at 3 s and 4 s: run still open
      final closed = d.skip(10 * kAsrSampleRate);
      expect(closed.map((e) => e.text), ['[خنده]']);
      expect(d.fedSamples, 14 * kAsrSampleRate);
    });
  });

  group('live pipeline', () {
    test('sound events arrive as LiveSoundEvent with bracketed text', () {
      final pipeline = LivePipeline(
        vadFactory: () => _NoSpeechVad(),
        decoder: _NoDecoder(),
        soundEvents: SoundEventDetector(
          tagger: ScriptedTagger([
            [s('Laughter', 0.7)],
          ]),
        ),
      );
      final events = <LiveEvent>[];
      for (var i = 0; i < 6; i++) {
        events.addAll(pipeline.feed(_pcm(1)));
      }
      events.addAll(pipeline.flush());
      final sounds = events.whereType<LiveSoundEvent>().toList();
      expect(sounds, hasLength(1));
      expect(sounds.single.text, '[خنده]');
      expect(sounds.single.kindId, 'laughter');
    });

    test('a tagger that throws is dropped and speech keeps working', () {
      final pipeline = LivePipeline(
        vadFactory: () => _NoSpeechVad(),
        decoder: _NoDecoder(),
        soundEvents: SoundEventDetector(tagger: _ThrowingTagger()),
      );
      final events = <LiveEvent>[];
      for (var i = 0; i < 8; i++) {
        events.addAll(pipeline.feed(_pcm(1)));
      }
      expect(events.whereType<LiveSoundEvent>(), isEmpty);
      expect(events.whereType<LiveFailure>(), isEmpty);
    });

    test('audio is not analysed while the phone is behind', () {
      final tagger = ScriptedTagger([
        [s('Laughter', 0.9)],
      ]);
      final pipeline = LivePipeline(
        vadFactory: () => _NoSpeechVad(),
        decoder: _NoDecoder(),
        soundEvents: SoundEventDetector(tagger: tagger),
      );
      for (var i = 0; i < 8; i++) {
        pipeline.feed(_pcm(1), backlogMs: 10000);
      }
      expect(tagger.calls, 0);
    });
  });
}

/// One second of 16-bit PCM at a level the silence gate passes.
Uint8List _pcm(int seconds) {
  final data = ByteData(seconds * kAsrSampleRate * 2);
  for (var i = 0; i < seconds * kAsrSampleRate; i++) {
    data.setInt16(i * 2, 1600, Endian.little);
  }
  return data.buffer.asUint8List();
}

class _NoSpeechVad implements LiveVad {
  @override
  void accept(Float32List samples) {}
  @override
  bool get speechDetected => false;
  @override
  VadSpan? pop() => null;
  @override
  void flush() {}
  @override
  void dispose() {}
}

class _NoDecoder implements LiveDecoder {
  @override
  String decode(Float32List samples) => '';
}

class _ThrowingTagger implements SoundTagger {
  @override
  List<SoundScore> tag(Float32List samples) => throw StateError('boom');
}
