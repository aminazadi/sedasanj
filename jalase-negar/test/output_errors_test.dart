import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/platform/api_client.dart';

class _Adapter implements HttpClientAdapter {
  _Adapter(this.handler);
  final ResponseBody Function(RequestOptions) handler;
  @override
  void close({bool force = false}) {}
  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<List<int>>? requestStream,
    Future<void>? cancelFuture,
  ) async => handler(options);
}

ResponseBody _json(Object body, {int status = 200}) => ResponseBody.fromString(
  jsonEncode(body),
  status,
  headers: {
    Headers.contentTypeHeader: ['application/json'],
  },
);

ApiClient _client(ResponseBody Function(RequestOptions) handler) {
  final dio = Dio(BaseOptions(baseUrl: 'https://example.test'))
    ..httpClientAdapter = _Adapter(handler);
  return ApiClient(serverUrl: 'https://example.test', token: 't', dio: dio);
}

DioException _error(int status, Map<String, Object?> body) => DioException(
  requestOptions: RequestOptions(path: '/'),
  response: Response(
    requestOptions: RequestOptions(path: '/'),
    statusCode: status,
    data: body,
  ),
);

Map<String, Object?> _envelope(String code, String message) => {
  'error': {'code': code, 'message': message},
};

void main() {
  group('outputTypes', () {
    test('skips one malformed category and keeps the others', () async {
      final client = _client(
        (_) => _json({
          'items': [
            {
              'code': 'minutes',
              'title': 'صورت‌جلسه',
              'automatic': true,
              'input_fields': <Object>[],
            },
            {
              'code': 'broken',
              'title': 'خراب',
              // A field without `label_fa` cannot be parsed.
              'input_fields': [
                {'key': 'course'},
              ],
            },
            {
              'code': 'interview',
              'title': 'مصاحبه',
              'automatic': false,
              'input_fields': <Object>[],
            },
          ],
        }),
      );
      final types = await client.outputTypes();
      expect([for (final t in types) t.code], ['minutes', 'interview']);
    });

    test('an unreadable body is reported with its own code', () async {
      final client = _client((_) => _json({'unexpected': true}));
      await expectLater(
        client.outputTypes(),
        throwsA(
          isA<ApiException>().having(
            (e) => e.code,
            'code',
            'output_types_parse_failed',
          ),
        ),
      );
    });
  });

  group('mapSessionError', () {
    test('an exhausted token budget names the plan screen, not the panel', () {
      final e = mapSessionError(
        _error(402, _envelope('token_quota_exceeded', 'monthly budget ended')),
      );
      expect(e.statusCode, 402);
      expect(e.message, contains('پلن و مصرف'));
      expect(e.message, isNot(contains('پنل')));
    });

    test('keeps the server message for a category that is not published', () {
      final e = mapSessionError(
        _error(
          404,
          _envelope(
            'output_type_not_found',
            'این دسته وجود ندارد یا منتشر نشده است.',
          ),
        ),
      );
      expect(e.message, 'این دسته وجود ندارد یا منتشر نشده است.');
      expect(e.statusCode, 404);
      expect(e.requiresReconnect, isFalse);
    });

    test('401 and 403 still ask to reconnect', () {
      for (final status in [401, 403]) {
        expect(
          mapSessionError(
            _error(status, _envelope('x', 'y')),
          ).requiresReconnect,
          isTrue,
          reason: 'HTTP $status',
        );
      }
    });
  });

  group('usage', () {
    test('a null body is reported as usage_parse_failed', () async {
      final client = _client(
        (_) => ResponseBody.fromString(
          'null',
          200,
          headers: {
            Headers.contentTypeHeader: ['application/json'],
          },
        ),
      );
      await expectLater(
        client.usage(),
        throwsA(
          isA<ApiException>().having(
            (e) => e.code,
            'code',
            'usage_parse_failed',
          ),
        ),
      );
    });
  });
}
