import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/platform/api_client.dart';

DioException _error(int status, Map<String, Object?> body) => DioException(
  requestOptions: RequestOptions(path: '/v1/jalase-negar/auth/complete'),
  response: Response(
    requestOptions: RequestOptions(path: '/'),
    statusCode: status,
    data: body,
  ),
);

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

ResponseBody _json(String body, {int status = 200}) => ResponseBody.fromString(
  body,
  status,
  headers: {
    Headers.contentTypeHeader: ['application/json'],
  },
);

void main() {
  test('a closed sign-up shows the server message, not the reconnect flow', () {
    final e = mapLoginError(
      _error(403, {
        'error': {
          'code': 'jalase_signup_disabled',
          'message': 'ثبت‌نام مستقل هنوز فعال نشده است.',
        },
      }),
    );
    expect(e.message, 'ثبت‌نام مستقل هنوز فعال نشده است.');
    expect(e.code, 'jalase_signup_disabled');
    expect(e.requiresReconnect, isFalse);
  });

  test('a wrong code (401) keeps the server message', () {
    final e = mapLoginError(
      _error(401, {
        'error': {'code': 'unauthorized', 'message': 'کد تأیید نادرست است.'},
      }),
    );
    expect(e.message, 'کد تأیید نادرست است.');
    expect(e.requiresReconnect, isFalse);
  });

  test('without a body the generic mapping applies', () {
    final e = mapLoginError(
      DioException(requestOptions: RequestOptions(path: '/')),
    );
    expect(e.message, contains('ارتباط با سرور'));
  });

  test('sign-in steps parse the server responses', () async {
    final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
    dio.httpClientAdapter = _Adapter((o) {
      switch (o.path) {
        case '/v1/jalase-negar/auth/request':
          return _json('{"otp_id":"abc","expires_in":300,"resend_after":45}');
        case '/v1/jalase-negar/auth/verify':
          return _json('{"verified_token":"vt","has_account":false}');
        default:
          return _json(
            '{"token":"tok","token_prefix":"jn_ab","created":true,'
            '"user":{"display_name":"علی"}}',
            status: 201,
          );
      }
    });
    final api = ApiClient(serverUrl: 'https://example.test', dio: dio);
    final otp = await api.requestOtp('09120000000');
    expect(otp.otpId, 'abc');
    expect(otp.resendAfter, const Duration(seconds: 45));
    final verified = await api.verifyOtp(otpId: 'abc', code: '123456');
    expect(verified.token, 'vt');
    expect(verified.hasAccount, isFalse);
    final login = await api.completeLogin(
      verifiedToken: 'vt',
      deviceName: 'd',
      platform: 'macos',
      appVersion: '1.0.0',
      displayName: 'علی',
    );
    expect(login.token, 'tok');
    expect(login.created, isTrue);
    expect(login.userName, 'علی');
  });
}
