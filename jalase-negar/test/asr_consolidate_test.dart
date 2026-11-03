import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/asr/consolidate.dart';
import 'package:jalase_negar/core/asr/energy_vad.dart';

/// Shared ASR parity vectors (see sedasanj/docs/asr-parity-contract.md). The
/// server side of the same files is checked by
/// sedasanj/tests/test_asr_parity_contract.py.
Map<String, dynamic> _fixture(String name) =>
    jsonDecode(
          File('../sedasanj/tests/fixtures/asr_parity/$name').readAsStringSync(),
        )
        as Map<String, dynamic>;

void main() {
  group('consolidateSegments (contract vectors)', () {
    final cases = (_fixture('consolidation.json')['cases'] as List)
        .cast<Map<String, dynamic>>();

    test('fixture is present', () => expect(cases.length, greaterThan(5)));

    for (final c in cases) {
      test(c['name'] as String, () {
        final rows = [
          for (final item in (c['input'] as List).cast<Map<String, dynamic>>())
            AsrTurn(
              channel: item['channel'] as int,
              startMs: item['start_ms'] as int,
              endMs: item['end_ms'] as int,
              text: item['text'] as String,
              confidence: (item['confidence'] as num?)?.toDouble(),
              timestampSource: item['timestamp_source'] as String?,
            ),
        ];
        final result = consolidateSegments(
          rows,
          mergeGapMs: c['merge_gap_ms'] as int,
        );
        final expected = (c['expected'] as List).cast<Map<String, dynamic>>();
        expect(result.length, expected.length);
        for (var i = 0; i < expected.length; i++) {
          expect(result[i].channel, expected[i]['channel']);
          expect(result[i].startMs, expected[i]['start_ms']);
          expect(result[i].endMs, expected[i]['end_ms']);
          expect(result[i].text, expected[i]['text']);
          expect(result[i].confidence, (expected[i]['confidence'] as num?));
          expect(result[i].timestampSource, expected[i]['timestamp_source']);
        }
      });
    }

    test('default merge gap equals the contract constant', () {
      final merge = _fixture('constants.json')['merge'] as Map<String, dynamic>;
      expect(kTurnMergeGapMs, merge['turn_merge_gap_ms']);
    });
  });

  group('energyVadRegions (contract vectors)', () {
    final doc = _fixture('energy_vad.json');
    final sampleRate = doc['sample_rate'] as int;
    final cases = (doc['cases'] as List).cast<Map<String, dynamic>>();

    Float32List build(Map<String, dynamic> c) {
      final n = ((c['duration_s'] as num) * sampleRate).round();
      final floor = c['floor'] as Map<String, dynamic>;
      final samples = Float32List(n);
      for (var i = 0; i < n; i++) {
        final t = i / sampleRate;
        var x =
            (floor['amp'] as num) *
            math.sin(2 * math.pi * (floor['freq'] as num) * t);
        for (final b in (c['bursts'] as List).cast<Map<String, dynamic>>()) {
          if (t >= (b['start'] as num) && t < (b['end'] as num)) {
            x += (b['amp'] as num) * math.sin(2 * math.pi * (b['freq'] as num) * t);
          }
        }
        samples[i] = x.toDouble();
      }
      return samples;
    }

    for (final c in cases) {
      test(c['name'] as String, () {
        final regions = energyVadRegions(
          build(c),
          sampleRate,
          minSeconds: (doc['min_seconds'] as num).toDouble(),
          paddingSeconds: (doc['padding_seconds'] as num).toDouble(),
        );
        final expected = (c['expected_regions'] as List).cast<List>();
        expect(regions.length, expected.length);
        for (var i = 0; i < expected.length; i++) {
          expect(regions[i].start, closeTo((expected[i][0] as num), 1e-9));
          expect(regions[i].end, closeTo((expected[i][1] as num), 1e-9));
        }
      });
    }
  });
}
