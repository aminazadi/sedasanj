import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/platform/api_client.dart';
import 'package:jalase_negar/core/platform/platform_config.dart';

Map<String, Object?> payload({
  String url = 'https://panel.example.com/',
  String? expires,
}) => {
  'schema': kConfigSchema,
  'version': 1,
  'server_url': url,
  'pairing_code': ' ABCD2345 ',
  if (expires != null) 'expires_at': expires,
};

void main() {
  final now = DateTime.utc(2026, 11, 1, 12);

  test('parses a valid payload and normalizes the url', () {
    final p = parsePairingPayload(
      payload(expires: '2026-11-01T12:15:00Z'),
      now: now,
      allowInsecure: false,
    );
    expect(p.serverUrl, 'https://panel.example.com');
    expect(p.pairingCode, 'ABCD2345');
  });

  test('rejects expired codes, foreign schemas and wrong versions', () {
    expect(
      () => parsePairingPayload(
        payload(expires: '2026-11-01T11:00:00Z'),
        now: now,
      ),
      throwsA(isA<ConfigParseException>()),
    );
    expect(
      () => parsePairingPayload({'schema': 'x'}),
      throwsA(isA<ConfigParseException>()),
    );
    expect(
      () => parsePairingPayload({...payload(), 'version': 2}),
      throwsA(isA<ConfigParseException>()),
    );
  });

  test('http is rejected outside local hosts when insecure is off', () {
    expect(
      () =>
          normalizeServerUrl('http://panel.example.com', allowInsecure: false),
      throwsA(isA<ConfigParseException>()),
    );
    expect(
      normalizeServerUrl('http://10.0.2.2:8000', allowInsecure: false),
      'http://10.0.2.2:8000',
    );
  });

  test('maps API errors to actionable messages', () {
    DioException err(int status, [String? code]) => DioException(
      requestOptions: RequestOptions(),
      response: Response(
        requestOptions: RequestOptions(),
        statusCode: status,
        data: code == null
            ? null
            : {
                'error': {'code': code},
              },
      ),
    );
    expect(mapDioError(err(401)).requiresReconnect, isTrue);
    expect(mapDioError(err(402)).message, contains('شارژ'));
    expect(
      mapDioError(err(400, 'meeting_pairing_invalid')).code,
      'meeting_pairing_invalid',
    );
    expect(
      mapDioError(DioException(requestOptions: RequestOptions())).statusCode,
      isNull,
    );
  });
}
