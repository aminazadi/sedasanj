import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/asr/transcriber.dart';

void main() {
  group('normalizePersianAsrText', () {
    test('normalizes Arabic characters without changing words', () {
      expect(
        normalizePersianAsrText('  اين يك متن فارسي است  '),
        'این یک متن فارسی است',
      );
    });

    test('removes combining marks and collapses noisy whitespace', () {
      expect(
        normalizePersianAsrText('سَلام   دنیا\n\n\n  جلسه'),
        'سلام دنیا\n\nجلسه',
      );
    });

    test('keeps an already clean transcript unchanged', () {
      const clean = 'سلام، جلسه از ساعت ۹ شروع شد.';
      expect(normalizePersianAsrText(clean), clean);
    });
  });

  group('addAsrPreRoll', () {
    test('uses available audio before the detected speech start', () {
      final result = addAsrPreRoll(
        speech: Float32List.fromList([100, 101]),
        speechStartSample: 5,
        availableContext: Float32List.fromList([0, 1, 2, 3, 4, 5, 6]),
        availableContextStartSample: 0,
        preRollSamples: 3,
      );

      expect(result.startSample, 2);
      expect(result.samples.toList(), [2, 3, 4, 100, 101]);
    });

    test('pads with silence when the file starts before pre-roll exists', () {
      final result = addAsrPreRoll(
        speech: Float32List.fromList([10, 11]),
        speechStartSample: 0,
        availableContext: Float32List(0),
        availableContextStartSample: 0,
        preRollSamples: 3,
      );

      expect(result.startSample, 0);
      expect(result.samples.toList(), [0, 0, 0, 10, 11]);
    });

    test('pads only the missing part when bounded history is short', () {
      final result = addAsrPreRoll(
        speech: Float32List.fromList([20, 21]),
        speechStartSample: 7,
        availableContext: Float32List.fromList([4, 5, 6]),
        availableContextStartSample: 4,
        preRollSamples: 5,
      );

      expect(result.startSample, 2);
      expect(result.samples.toList(), [0, 0, 4, 5, 6, 20, 21]);
    });
  });

  test('addAsrContext includes look-ahead audio for full-context CTC', () {
    final result = addAsrContext(
      speech: Float32List.fromList([20, 21]),
      speechStartSample: 3,
      speechEndSample: 5,
      availableContext: Float32List.fromList([0, 1, 2, 3, 4, 5, 6, 7]),
      availableContextStartSample: 0,
      preRollSamples: 2,
      postRollSamples: 2,
    );

    expect(result.startSample, 1);
    expect(result.samples.toList(), [1, 2, 20, 21, 5, 6]);
  });
}
