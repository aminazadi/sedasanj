import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:jalase_negar/features/updates/data/app_update.dart';

const installedApp = UpdateEnvironment(
  versionName: '1.0.1',
  versionCode: 2,
  sdkInt: 34,
  abis: ['arm64-v8a'],
  certSha256:
      'e7fb6bf31abdfb5d7609bc2149d983ef9b3c161ea19d312a147a8fa196952512',
);

Map<String, Object?> offerJson({
  int code = 3,
  String version = '1.0.2',
  String path = '/v1/jalase-negar/android/releases/abc/download',
  String notes = 'رفع خطا\nسرعت بهتر',
}) => {
  'update': {
    'id': 'abc',
    'version': version,
    'version_code': code,
    'title': 'نسخه $version',
    'notes': notes,
    'size': 1024,
    'sha256': 'f' * 64,
    'min_sdk': 24,
    'published_at': '2026-11-04T00:00:00Z',
    'download_path': path,
  },
};

/// Records requests and answers with a canned response, an error or a hang.
class FakeAdapter implements HttpClientAdapter {
  FakeAdapter({this.status = 200, this.body, this.error, this.hang = false});

  int status;
  Object? body;
  DioExceptionType? error;
  bool hang;
  final requests = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    requests.add(options);
    if (hang) {
      await Completer<void>().future;
    }
    if (error != null) {
      throw DioException(requestOptions: options, type: error!);
    }
    return ResponseBody.fromString(
      jsonEncode(body),
      status,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}
