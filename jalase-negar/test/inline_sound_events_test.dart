import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/asr/inline_sound_events.dart';
import 'package:jalase_negar/core/asr/live_pipeline.dart';

SoundMark mark(int from, int to, String text) =>
    SoundMark(startMs: from, endMs: to, marker: text);

void main() {
  const words = [
    TimedWord('یک', 0),
    TimedWord('دو', 1000),
    TimedWord('سه', 2000),
    TimedWord('چهار', 3000),
  ];
  const span = SpeechSpan(
    startMs: 0,
    endMs: 4000,
    text: 'یک دو سه چهار',
    words: words,
  );

  test('a sound during speech goes before the next word', () {
    final result = placeSoundMarks([span], [mark(1500, 1800, '[سرفه]')]);
    expect(result.texts, ['یک دو [سرفه] سه چهار']);
    expect(result.loose, isEmpty);
  });

  test('a sound at the very start of a line goes before the first word', () {
    final result = placeSoundMarks([span], [mark(0, 500, '[خنده]')]);
    expect(result.texts, ['[خنده] یک دو سه چهار']);
  });

  test('a sound after the last word goes at the end', () {
    final result = placeSoundMarks([span], [mark(3500, 3900, '[خنده]')]);
    expect(result.texts, ['یک دو سه چهار [خنده]']);
  });

  test('several sounds keep their time order inside one gap', () {
    final result = placeSoundMarks(
      [span],
      [mark(1600, 1700, '[عطسه]'), mark(1400, 1500, '[سرفه]')],
    );
    expect(result.texts, ['یک دو [سرفه] [عطسه] سه چهار']);
  });

  test('without word times the place is estimated from the time', () {
    const plain = SpeechSpan(startMs: 0, endMs: 4000, text: 'یک دو سه چهار');
    final result = placeSoundMarks([plain], [mark(2100, 2300, '[خنده]')]);
    expect(result.texts, ['یک دو سه [خنده] چهار']);
  });

  test('word times that do not spell the text are ignored', () {
    const odd = SpeechSpan(
      startMs: 0,
      endMs: 4000,
      text: 'یک دو سه چهار',
      words: [TimedWord('x', 0)],
    );
    final result = placeSoundMarks([odd], [mark(2100, 2300, '[خنده]')]);
    expect(result.texts, ['یک دو سه [خنده] چهار']);
  });

  test(
    'a sound just after a line joins its end, just before joins its start',
    () {
      const next = SpeechSpan(startMs: 10000, endMs: 12000, text: 'بعدی');
      final after = placeSoundMarks([span, next], [mark(5000, 6000, '[خنده]')]);
      expect(after.texts, ['یک دو سه چهار [خنده]', 'بعدی']);
      final before = placeSoundMarks(
        [span, next],
        [mark(8500, 9500, '[خنده]')],
      );
      expect(before.texts, ['یک دو سه چهار', '[خنده] بعدی']);
    },
  );

  test('a sound far from any speech stands alone, close ones share a line', () {
    final result = placeSoundMarks(
      [span],
      [
        mark(20000, 21000, '[خنده]'),
        mark(22000, 23000, '[سرفه]'),
        mark(40000, 41000, '[عطسه]'),
      ],
    );
    expect(result.texts, ['یک دو سه چهار']);
    expect(result.loose.map((l) => l.text), ['[خنده] [سرفه]', '[عطسه]']);
    expect(result.loose.first.startMs, 20000);
    expect(result.loose.first.endMs, 23000);
  });

  test('a line that overlaps the sound wins over a nearer earlier line', () {
    const a = SpeechSpan(startMs: 0, endMs: 2000, text: 'اول');
    const b = SpeechSpan(startMs: 2100, endMs: 5000, text: 'دوم سوم');
    final result = placeSoundMarks([a, b], [mark(2150, 2400, '[سرفه]')]);
    // Estimated word times: «دوم» starts at 2100 ms, before the sound.
    expect(result.texts, ['اول', 'دوم [سرفه] سوم']);
  });

  group('wordsFromTokens', () {
    String same(String s) => s.trim();

    test('groups tokens into words with absolute times', () {
      final words = wordsFromTokens(
        const TimedDecode(
          ' ببریمش چیه',
          [' بب', 'ر', 'یم', 'ش', ' چیه'],
          [1.0, 1.2, 1.3, 1.4, 2.0],
        ),
        16000, // the audio starts at 1 s
        same,
      );
      expect(words!.map((w) => w.text), ['ببریمش', 'چیه']);
      expect(words.map((w) => w.startMs), [2000, 3000]);
    });

    test('a negative origin (young recording) still gives true times', () {
      final words = wordsFromTokens(
        const TimedDecode('x', [' و'], [1.0]),
        -12000, // 0.75 s of padding before the recording began
        same,
      );
      expect(words!.single.startMs, 250);
    });

    test('mismatched counts give null', () {
      expect(
        wordsFromTokens(const TimedDecode('x', [' و'], []), 0, same),
        isNull,
      );
    });
  });
}
