import 'dart:async';

import 'package:dio/dio.dart';

import 'app_update.dart';

/// Why an update check produced no answer.
class UpdateCheckException implements Exception {
  const UpdateCheckException(this.message);

  /// Persian text that names the next action.
  final String message;

  @override
  String toString() => message;
}

/// Asks the central backend for a newer build. It has no token and no link to
/// the pairing client: the check must work before the app is connected.
class UpdateClient {
  UpdateClient({Dio? dio, this.timeout = const Duration(seconds: 5)})
    : _dio =
          dio ??
          Dio(
            BaseOptions(
              baseUrl: kUpdateOrigin,
              connectTimeout: timeout,
              receiveTimeout: timeout,
              sendTimeout: timeout,
              followRedirects: false,
              responseType: ResponseType.json,
            ),
          );

  final Dio _dio;

  /// Hard ceiling for the whole request, DNS and TLS included.
  final Duration timeout;

  Future<AppUpdateOffer?> check(UpdateEnvironment environment) async {
    final cancel = CancelToken();
    try {
      final response = await _dio
          .get<Object?>(
            '/v1/jalase-negar/android/update',
            queryParameters: environment.toQuery(),
            options: Options(
              headers: {'Accept': 'application/json'},
              validateStatus: (status) => status != null && status < 500,
            ),
            cancelToken: cancel,
          )
          .timeout(
            timeout,
            onTimeout: () {
              cancel.cancel('update check timed out');
              throw const UpdateCheckException(_offline);
            },
          );
      if (response.statusCode != 200) {
        throw const UpdateCheckException(_invalid);
      }
      return AppUpdateOffer.fromResponse(response.data);
    } on UpdateCheckException {
      rethrow;
    } on FormatException {
      throw const UpdateCheckException(_invalid);
    } on DioException catch (e) {
      final status = e.response?.statusCode;
      throw UpdateCheckException(
        status != null && status >= 500 ? _server : _offline,
      );
    } on TimeoutException {
      throw const UpdateCheckException(_offline);
    }
  }
}

const _offline =
    'اتصال به سرور به‌روزرسانی برقرار نشد؛ اینترنت را بررسی کنید و دوباره تلاش کنید.';
const _invalid =
    'پاسخ سرور به‌روزرسانی معتبر نبود؛ چند دقیقه بعد دوباره تلاش کنید.';
const _server =
    'سرور به‌روزرسانی موقتاً در دسترس نیست؛ چند دقیقه بعد دوباره تلاش کنید.';
