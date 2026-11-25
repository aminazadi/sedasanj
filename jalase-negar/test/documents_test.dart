import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/features/catalog/application/catalog_providers.dart';
import 'package:jalase_negar/core/platform/api_client.dart';
import 'package:jalase_negar/features/documents/presentation/documents_tab.dart';
import 'package:jalase_negar/features/settings/application/connection_controller.dart';

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

const _catalog = {
  'items': [
    {
      'code': 'minutes',
      'title': 'صورت‌جلسه',
      'description': '',
      'automatic': true,
      'thumbnail_url': null,
      'input_fields': <Object>[],
    },
    {
      'code': 'university_notes',
      'title': 'جزوهٔ کلاس',
      'description': 'جزوهٔ مرتب',
      'automatic': false,
      'thumbnail_url': '/v1/help/media/abc',
      'input_fields': [
        {
          'key': 'course',
          'label_fa': 'نام درس',
          'type': 'text',
          'required': true,
        },
        {
          'key': 'level',
          'label_fa': 'سطح',
          'type': 'select',
          'required': false,
          'options': ['ارشد', 'دکتری'],
        },
      ],
    },
  ],
};

ApiClient _client(List<RequestOptions> seen) {
  final dio = Dio(BaseOptions(baseUrl: 'https://example.test/'));
  dio.httpClientAdapter = _Adapter((o) {
    seen.add(o);
    if (o.path.endsWith('/output-types')) return _json(_catalog);
    if (o.method == 'POST' && o.path.endsWith('/documents')) {
      return _json({
        'items': [
          {
            'id': 'd1',
            'output_type': 'university_notes',
            'status': 'queued',
            'progress_pct': 0,
            'error_code': null,
            'selected_version': null,
          },
        ],
      }, status: 201);
    }
    return _json({'items': <Object>[]});
  });
  return ApiClient(serverUrl: 'https://example.test', dio: dio);
}

void main() {
  test(
    'export returns the file bytes and decodes a JSON error sent as bytes',
    () async {
      final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
      dio.httpClientAdapter = _Adapter((o) {
        if (o.queryParameters['format'] == 'pdf') {
          return ResponseBody.fromBytes([0x25, 0x50, 0x44, 0x46], 200);
        }
        return ResponseBody.fromBytes(
          utf8.encode(
            jsonEncode({
              'error': {
                'code': 'document_not_found',
                'message': 'سند هنوز آماده نیست.',
              },
            }),
          ),
          404,
          headers: {
            Headers.contentTypeHeader: ['application/json'],
          },
        );
      });
      final api = ApiClient(serverUrl: 'https://example.test', dio: dio);
      expect(await api.exportDocument('d1', 'pdf'), [0x25, 0x50, 0x44, 0x46]);
      await expectLater(
        api.exportDocument('d1', 'docx'),
        throwsA(
          isA<ApiException>().having(
            (e) => e.message,
            'message',
            'سند هنوز آماده نیست.',
          ),
        ),
      );
    },
  );

  test('the catalog keeps thumbnails absolute and fields typed', () async {
    final types = await _client([]).outputTypes();
    expect(types.first.automatic, isTrue);
    final notes = types.last;
    expect(notes.thumbnailUrl, 'https://example.test/v1/help/media/abc');
    expect(notes.fields.first.required, isTrue);
    expect(notes.fields.last.options, ['ارشد', 'دکتری']);
  });

  test('a 422 keeps the server message and a 401 asks to reconnect', () {
    ApiException map(int status, Map<String, Object?> body) => mapMessageError(
      DioException(
        requestOptions: RequestOptions(path: '/'),
        response: Response(
          requestOptions: RequestOptions(path: '/'),
          statusCode: status,
          data: body,
        ),
      ),
    );
    final invalid = map(422, {
      'error': {
        'code': 'document_input_invalid',
        'message': 'نام درس را وارد کنید.',
      },
    });
    expect(invalid.message, 'نام درس را وارد کنید.');
    expect(invalid.requiresReconnect, isFalse);
    expect(
      map(401, {
        'error': {'code': 'unauthorized'},
      }).requiresReconnect,
      isTrue,
    );
  });

  testWidgets(
    'the picker hides nothing it was given, asks required fields, sends values',
    (tester) async {
      final fake = _FakeClient();
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            outputTypesProvider.overrideWith(
              (ref) => Stream.value(const [
                OutputTypeInfo(
                  code: 'university_notes',
                  title: 'جزوهٔ کلاس',
                  description: 'جزوهٔ مرتب',
                  automatic: false,
                  fields: [
                    OutputField(
                      key: 'course',
                      label: 'نام درس',
                      type: 'text',
                      required: true,
                    ),
                  ],
                ),
              ]),
            ),
            personalClientProvider.overrideWith((ref) async => fake),
          ],
          child: const MaterialApp(
            home: Scaffold(body: CategoryPickerSheet(remoteMeetingId: 'm1')),
          ),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('جزوهٔ کلاس'), findsOneWidget);
      // Nothing chosen: the button is disabled.
      expect(
        tester.widget<FilledButton>(find.byType(FilledButton)).onPressed,
        isNull,
      );

      await tester.tap(find.text('جزوهٔ کلاس'));
      await tester.pump();
      expect(find.text('نام درس *'), findsOneWidget);

      // The required field is empty: the sheet explains instead of calling the server.
      await tester.tap(find.byType(FilledButton));
      await tester.pump();
      expect(find.textContaining('فیلدهای اجباری'), findsOneWidget);
      expect(fake.sent, isEmpty);

      await tester.enterText(
        find.widgetWithText(TextFormField, 'نام درس *'),
        'آمار',
      );
      await tester.tap(find.byType(FilledButton));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      expect(fake.sent, hasLength(1));
      expect(fake.sent.single.$1, 'm1');
      expect(fake.sent.single.$2.single.code, 'university_notes');
      expect(fake.sent.single.$2.single.values, {'course': 'آمار'});
    },
  );
}

class _FakeClient extends ApiClient {
  _FakeClient() : super(serverUrl: 'https://example.test');

  final sent = <(String, List<({String code, Map<String, String> values})>)>[];

  @override
  Future<List<DocumentInfo>> createDocuments(
    String remoteMeetingId,
    List<({String code, Map<String, String> values})> items,
  ) async {
    sent.add((remoteMeetingId, items));
    return const [];
  }
}
