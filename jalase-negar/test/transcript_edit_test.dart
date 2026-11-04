import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';
import 'package:jalase_negar/features/meetings/data/transcript_edit.dart';

Segment _seg(int start, int end, String text, {double? confidence}) => Segment(
  channel: 0,
  startMs: start,
  endMs: end,
  text: text,
  confidence: confidence,
);

final _base = [
  _seg(0, 1000, 'یک', confidence: 0.9),
  _seg(1000, 2000, 'دو', confidence: 0.8),
  _seg(2000, 3000, 'سه', confidence: 0.7),
  _seg(3000, 4000, 'چهار', confidence: 0.6),
];

void _expectValid(List<Segment> segments) {
  var previous = 0;
  for (final s in segments) {
    expect(s.startMs, greaterThanOrEqualTo(previous));
    expect(s.endMs, greaterThanOrEqualTo(s.startMs));
    expect(s.text.length, lessThanOrEqualTo(kMaxSegmentChars));
    expect(s.text, isNotEmpty);
    previous = s.startMs;
  }
}

void main() {
  group('transcriptEditorText', () {
    test('orders by time, drops blanks and keeps one segment per line', () {
      final text = transcriptEditorText([
        _seg(500, 600, 'پایان'),
        _seg(0, 400, ' سلام\nدنیا '),
        _seg(450, 480, '   '),
      ]);
      expect(text, 'سلام دنیا\nپایان');
    });
  });

  group('canonicalTranscriptLines', () {
    test('trims, drops blank lines and accepts any line ending', () {
      expect(canonicalTranscriptLines(' الف \r\n\r\n ب\rج\n\n'), [
        'الف',
        'ب',
        'ج',
      ]);
    });

    test('splits an over-long line at a space', () {
      final word = 'کلمه ' * 1500; // 7500 characters
      final lines = canonicalTranscriptLines(word);
      expect(lines.length, 2);
      for (final line in lines) {
        expect(line.length, lessThanOrEqualTo(kMaxSegmentChars));
      }
      expect(lines.join(' '), word.trim());
    });

    test('splits a line with no space at the limit', () {
      final lines = canonicalTranscriptLines('ا' * 4500);
      expect(lines.map((l) => l.length), [4000, 500]);
    });
  });

  group('applyTranscriptEdit', () {
    test('unchanged text keeps every segment as is', () {
      final result = applyTranscriptEdit(_base, 'یک\nدو\nسه\nچهار');
      expect(result.length, 4);
      for (var i = 0; i < 4; i++) {
        expect(identical(result[i], _base[i]), isTrue);
      }
    });

    test('an edited line keeps its time and drops the old confidence', () {
      final result = applyTranscriptEdit(_base, 'یک\nدوم\nسه\nچهار');
      expect(result[1].text, 'دوم');
      expect(result[1].startMs, 1000);
      expect(result[1].endMs, 2000);
      expect(result[1].confidence, isNull);
      expect(result[0].confidence, 0.9);
    });

    test('a deleted line disappears and the others keep their times', () {
      final result = applyTranscriptEdit(_base, 'یک\nسه\nچهار');
      expect(result.map((s) => s.text), ['یک', 'سه', 'چهار']);
      expect(result[1].startMs, 2000);
    });

    test('an inserted line is placed between its neighbours', () {
      final result = applyTranscriptEdit(_base, 'یک\nدو\nنو\nسه\nچهار');
      expect(result.map((s) => s.text), ['یک', 'دو', 'نو', 'سه', 'چهار']);
      expect(result[2].startMs, greaterThanOrEqualTo(2000));
      expect(result[2].startMs, lessThanOrEqualTo(2000));
      _expectValid(result);
    });

    test('inserted lines at the start and end are valid', () {
      final result = applyTranscriptEdit(_base, 'اول\nیک\nدو\nسه\nچهار\nآخر');
      expect(result.first.text, 'اول');
      expect(result.last.text, 'آخر');
      expect(result.last.startMs, greaterThanOrEqualTo(4000));
      _expectValid(result);
    });

    test('joined lines cover the time of both', () {
      final result = applyTranscriptEdit(_base, 'یک دو\nسه\nچهار');
      expect(result[0].text, 'یک دو');
      expect(result[0].startMs, 0);
      expect(result[0].endMs, 2000);
      expect(result[1].startMs, 2000);
    });

    test('a split line divides the time of the original', () {
      final result = applyTranscriptEdit(_base, 'ی\nک\nدو\nسه\nچهار');
      expect(result.map((s) => s.text), ['ی', 'ک', 'دو', 'سه', 'چهار']);
      expect(result[0].startMs, 0);
      expect(result[0].endMs, 500);
      expect(result[1].startMs, 500);
      expect(result[1].endMs, 1000);
      _expectValid(result);
    });

    test('rewriting everything keeps timing line by line', () {
      final result = applyTranscriptEdit(_base, 'الف\nب\nپ\nت');
      expect(result.map((s) => s.startMs), [0, 1000, 2000, 3000]);
      expect(result.map((s) => s.text), ['الف', 'ب', 'پ', 'ت']);
    });

    test('clearing the text leaves no segments', () {
      expect(applyTranscriptEdit(_base, '  \n\n'), isEmpty);
    });

    test('an over-long line is stored as several valid segments', () {
      final result = applyTranscriptEdit(_base, 'یک\n${'کلمه ' * 1500}\nچهار');
      _expectValid(result);
      expect(result.length, 4);
    });

    test('overlapping channels still give non-decreasing starts', () {
      final overlapping = [
        const Segment(channel: 0, startMs: 0, endMs: 3000, text: 'الف'),
        const Segment(channel: 1, startMs: 1000, endMs: 2000, text: 'ب'),
        const Segment(channel: 0, startMs: 4000, endMs: 5000, text: 'پ'),
      ];
      final result = applyTranscriptEdit(overlapping, 'الف\nب\nنو\nپ');
      _expectValid(result);
      expect(result.map((s) => s.text), ['الف', 'ب', 'نو', 'پ']);
    });

    test('an empty original takes inserted lines at time zero', () {
      final result = applyTranscriptEdit(const [], 'الف\nب');
      expect(result.map((s) => s.text), ['الف', 'ب']);
      _expectValid(result);
    });

    test('a large transcript with a few edits stays fast and exact', () {
      final big = [
        for (var i = 0; i < 5000; i++) _seg(i * 10, i * 10 + 9, 'خط $i'),
      ];
      final lines = [for (final s in big) s.text]
        ..[2500] = 'تغییر'
        ..removeAt(100)
        ..insert(4000, 'جدید');
      final watch = Stopwatch()..start();
      final result = applyTranscriptEdit(big, lines.join('\n'));
      watch.stop();
      expect(result.map((s) => s.text), lines);
      _expectValid(result);
      expect(watch.elapsed.inSeconds, lessThan(5));
    });
  });

  group('find and replace', () {
    test('matches ignore Latin case and Arabic letter variants', () {
      expect(findTranscriptMatches('Hello hello كتاب کتاب', 'HELLO'), [0, 6]);
      expect(findTranscriptMatches('كتاب کتاب', 'کتاب'), [0, 5]);
      expect(findTranscriptMatches('عدد ٣ و ۳', '۳'), [4, 8]);
    });

    test('empty and missing queries find nothing', () {
      expect(findTranscriptMatches('abc', ''), isEmpty);
      expect(findTranscriptMatches('abc', 'z'), isEmpty);
    });

    test('matches do not overlap', () {
      expect(findTranscriptMatches('aaaa', 'aa'), [0, 2]);
    });

    test('replace swaps every match, also with an empty replacement', () {
      const text = 'سلام دنیا سلام';
      final matches = findTranscriptMatches(text, 'سلام');
      expect(
        replaceTranscriptMatches(text, matches, 4, 'درود'),
        'درود دنیا درود',
      );
      expect(replaceTranscriptMatches(text, matches, 4, ''), ' دنیا ');
    });
  });
}
