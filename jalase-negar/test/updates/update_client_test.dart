import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/features/updates/data/app_update.dart';
import 'package:jalase_negar/features/updates/data/update_client.dart';

import 'update_test_support.dart';

UpdateClient clientWith(FakeAdapter adapter, {Duration? timeout}) {
  final dio = Dio(BaseOptions(baseUrl: kUpdateOrigin))
    ..httpClientAdapter = adapter;
  return UpdateClient(dio: dio, timeout: timeout ?? const Duration(seconds: 5));
}

void main() {
  test('sends only the compatibility fields to the fixed origin', () async {
    final adapter = FakeAdapter(body: {'update': null});
    final offer = await clientWith(adapter).check(installedApp);
    expect(offer, isNull);
    final request = adapter.requests.single;
    expect(request.uri.origin, 'https://api.sedasanj.ir');
    expect(request.uri.path, '/v1/jalase-negar/android/update');
    expect(request.queryParameters.keys.toSet(), {
      'version_code',
      'sdk_int',
      'abis',
      'cert_sha256',
    });
    expect(request.headers.containsKey('Authorization'), isFalse);
  });

  test('parses an offer and resolves the download link on the origin', () async {
    final offer = await clientWith(
      FakeAdapter(body: offerJson()),
    ).check(installedApp);
    expect(offer!.version, '1.0.2');
    expect(offer.versionCode, 3);
    expect(offer.notes, contains('رفع خطا'));
    expect(
      offer.downloadUri.toString(),
      'https://api.sedasanj.ir/v1/jalase-negar/android/releases/abc/download',
    );
  });

  for (final path in [
    'https://evil.example/v1/jalase-negar/android/releases/abc/download',
    '//evil.example/v1/jalase-negar/android/releases/abc/download',
    '/v1/other/path',
    '/v1/jalase-negar/android/releases/../../admin',
    '/v1/jalase-negar/android/releases/abc/download?next=http://x',
    'javascript:alert(1)',
    '',
  ]) {
    test('rejects a foreign or unsafe download link: $path', () async {
      expect(
        () => clientWith(
          FakeAdapter(body: offerJson(path: path)),
        ).check(installedApp),
        throwsA(isA<UpdateCheckException>()),
      );
    });
  }

  test('an invalid body is a failed check, not a crash', () async {
    for (final body in [<String, Object?>{}, 'nope', {'update': 5}]) {
      expect(
        () => clientWith(FakeAdapter(body: body)).check(installedApp),
        throwsA(isA<UpdateCheckException>()),
      );
    }
  });

  test('server errors and rate limits become a Persian retry message', () async {
    for (final status in [429, 500, 503]) {
      await expectLater(
        clientWith(FakeAdapter(status: status, body: {})).check(installedApp),
        throwsA(
          isA<UpdateCheckException>().having(
            (e) => e.message,
            'message',
            contains('دوباره'),
          ),
        ),
      );
    }
  });

  test('offline maps to a message that names an action', () async {
    await expectLater(
      clientWith(
        FakeAdapter(error: DioExceptionType.connectionError),
      ).check(installedApp),
      throwsA(
        isA<UpdateCheckException>().having(
          (e) => e.message,
          'message',
          contains('اینترنت'),
        ),
      ),
    );
  });

  test('a hung connection is cut off by the overall deadline', () async {
    final stopwatch = Stopwatch()..start();
    await expectLater(
      clientWith(
        FakeAdapter(hang: true),
        timeout: const Duration(milliseconds: 200),
      ).check(installedApp),
      throwsA(isA<UpdateCheckException>()),
    );
    expect(stopwatch.elapsed, lessThan(const Duration(seconds: 2)));
  });
}
