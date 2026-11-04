import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/asr/transcriber.dart';

/// App half of the ASR parity contract. The vectors are shared with the server
/// (`sedasanj/tests/fixtures/asr_parity/normalization.json`). Cases where the
/// app differs from the server carry an `app_today` value: this test pins the
/// app's current behaviour so the gap is visible, and must be updated together
/// with the contract when the divergence is closed.
void main() {
  final fixture = File(
    '../sedasanj/tests/fixtures/asr_parity/normalization.json',
  );

  test('shared normalization vectors are available', () {
    expect(fixture.existsSync(), isTrue, reason: fixture.path);
  });

  test('normalizePersianAsrText matches the contract vectors', () {
    final cases =
        (jsonDecode(fixture.readAsStringSync())
                as Map<String, dynamic>)['cases']
            as List<dynamic>;
    expect(cases.length, greaterThan(5));
    for (final raw in cases) {
      final c = raw as Map<String, dynamic>;
      final expected = (c['app_today'] ?? c['server']) as String;
      expect(
        normalizePersianAsrText(c['input'] as String),
        expected,
        reason: c['name'] as String,
      );
    }
  });

  test(
    'app output equals server output wherever no divergence is recorded',
    () {
      final cases =
          (jsonDecode(fixture.readAsStringSync())
                  as Map<String, dynamic>)['cases']
              as List<dynamic>;
      final agreeing = cases.where(
        (c) => (c as Map).containsKey('app_today') == false,
      );
      expect(agreeing, isNotEmpty);
      for (final raw in agreeing) {
        final c = raw as Map<String, dynamic>;
        expect(
          normalizePersianAsrText(c['input'] as String),
          c['server'],
          reason: c['name'] as String,
        );
      }
    },
  );
}
