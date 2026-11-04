import 'package:dio/dio.dart';

import '../../features/meetings/data/meeting.dart';

/// Typed API failure with a Persian message that names the next action.
class ApiException implements Exception {
  const ApiException({
    required this.message,
    this.code,
    this.statusCode,
    this.requiresReconnect = false,
    this.missingSeqs = const [],
  });

  final String message;
  final String? code;
  final int? statusCode;

  /// The token is no longer valid; the user must pair the app again.
  final bool requiresReconnect;

  /// Chunk numbers the server is still missing (`meeting_incomplete_chunks`).
  final List<int> missingSeqs;

  /// Worth retrying later without any user action.
  bool get retryable =>
      !requiresReconnect &&
      (statusCode == null ||
          statusCode! >= 500 ||
          statusCode == 408 ||
          statusCode == 429);

  @override
  String toString() => message;
}

class PairResult {
  const PairResult({
    required this.token,
    required this.tokenPrefix,
    required this.userName,
    required this.tenantName,
  });

  final String token;
  final String tokenPrefix;
  final String userName;
  final String tenantName;
}

class RemoteSession {
  const RemoteSession({
    required this.meetingId,
    required this.status,
    required this.receivedSeqs,
    this.inputKind = 'audio',
  });

  final String meetingId;
  final String status;
  final List<int> receivedSeqs;

  /// 'text' for sessions this app creates; 'audio' for sessions an older app
  /// version opened (they cannot take a transcript).
  final String inputKind;
}

class RemoteStatus {
  const RemoteStatus({
    required this.status,
    required this.receivedSeqs,
    required this.progressPct,
    this.progressDetail,
    this.errorCode,
  });

  final String status;
  final List<int> receivedSeqs;
  final int progressPct;
  final String? progressDetail;
  final String? errorCode;

  bool get isComplete => status == 'complete';
  bool get isFailed => status.startsWith('failed') || status == 'canceled';
}

/// Server calls the upload queue needs; faked in tests.
abstract class MeetingUploadApi {
  Future<RemoteSession> createSession({
    required String clientMeetingId,
    required String title,
    required DateTime startedAt,
    required String appVersion,
  });

  Future<void> putChunk({
    required String meetingId,
    required int seq,
    required String filePath,
    required int startMs,
    required int endMs,
    required String sha256,
    String? deviceText,
  });

  /// Replaces the whole transcript of a text session (idempotent).
  Future<void> putTranscript({
    required String meetingId,
    required List<Segment> segments,
    String? asrIdentity,
  });

  Future<RemoteStatus> status(String meetingId);

  Future<void> finish({
    required String meetingId,
    required DateTime endedAt,
    required int totalChunks,
    required int durationMs,
  });
}

class ServerInfo {
  const ServerInfo({required this.userName, required this.tenantName});

  final String userName;
  final String tenantName;
}

ApiException mapDioError(DioException e) {
  final status = e.response?.statusCode;
  String? code;
  var missing = const <int>[];
  final data = e.response?.data;
  if (data is Map && data['error'] is Map) {
    final error = data['error'] as Map;
    code = error['code']?.toString();
    final rawMissing = error['missing_seqs'];
    if (rawMissing is List) {
      missing = [
        for (final v in rawMissing)
          if (v is int) v,
      ];
    }
  }
  if (status == null) {
    return const ApiException(
      message: 'ارتباط با سرور برقرار نشد؛ اینترنت و آدرس سرور را بررسی کنید.',
    );
  }
  switch (status) {
    case 400:
      if (code == 'meeting_pairing_invalid') {
        return ApiException(
          message: 'کد جفت‌سازی نامعتبر یا منقضی است؛ در پنل کد جدید بسازید.',
          code: code,
          statusCode: status,
        );
      }
    case 401:
    case 403:
      return ApiException(
        message: 'توکن ابطال شده است؛ دوباره به صداسنج متصل شوید.',
        code: code,
        statusCode: status,
        requiresReconnect: true,
      );
    case 402:
      return ApiException(
        message: 'اعتبار سازمان تمام شده است؛ در پنل اعتبار را شارژ کنید.',
        code: code,
        statusCode: status,
      );
    case 409:
      if (code == 'meeting_incomplete_chunks') {
        return ApiException(
          message:
              'بعضی تکه‌ها هنوز به سرور نرسیده‌اند؛ ارسال خودکار تکرار می‌شود.',
          code: code,
          statusCode: status,
          missingSeqs: missing,
        );
      }
      if (code == 'meeting_chunk_conflict') {
        return ApiException(
          message: 'این تکه قبلاً با محتوای دیگری ثبت شده است.',
          code: code,
          statusCode: status,
        );
      }
      if (code == 'meeting_transcript_missing') {
        return ApiException(
          message:
              'متنی برای این جلسه به سرور نرسیده است؛ ارسال دوباره انجام می‌شود.',
          code: code,
          statusCode: status,
        );
      }
      if (code == 'meeting_token_limit') {
        return ApiException(
          message:
              'سقف دستگاه‌های متصل پر است؛ در پنل یکی از دستگاه‌ها را ابطال کنید.',
          code: code,
          statusCode: status,
        );
      }
    case 422:
      if (code == 'meeting_transcript_invalid') {
        return ApiException(
          message:
              'متن جلسه برای سرور معتبر نیست (زمان‌ها یا اندازه)؛ اپ را به‌روز کنید یا جلسه را دوباره ضبط کنید.',
          code: code,
          statusCode: status,
        );
      }
    case 429:
      return ApiException(
        message: 'تعداد درخواست‌ها زیاد است؛ چند دقیقه بعد دوباره تلاش کنید.',
        code: code,
        statusCode: status,
      );
  }
  return ApiException(
    message: 'خطای سرور (${status.toString()})؛ کمی بعد دوباره تلاش کنید.',
    code: code,
    statusCode: status,
  );
}

/// Thin SedaSanj API client. It never logs headers or bodies.
class ApiClient implements MeetingUploadApi {
  ApiClient({required String serverUrl, String? token, Dio? dio})
    : _dio =
          dio ??
          Dio(
            BaseOptions(
              baseUrl: serverUrl,
              connectTimeout: const Duration(seconds: 15),
              receiveTimeout: const Duration(seconds: 30),
              sendTimeout: const Duration(seconds: 60),
              headers: {if (token != null) 'Authorization': 'Bearer $token'},
            ),
          );

  final Dio _dio;

  Future<PairResult> pair({
    required String pairingCode,
    required String deviceLabel,
    required String appVersion,
    required String platform,
  }) async {
    try {
      final res = await _dio.post<Map<String, dynamic>>(
        '/v1/meetings/devices/pair',
        data: {
          'pairing_code': pairingCode,
          'device_label': deviceLabel,
          'app_version': appVersion,
          'platform': platform,
        },
      );
      final body = res.data!;
      return PairResult(
        token: body['token'] as String,
        tokenPrefix: (body['token_prefix'] ?? '') as String,
        userName: ((body['user'] as Map?)?['display_name'] ?? '') as String,
        tenantName: ((body['tenant'] as Map?)?['name'] ?? '') as String,
      );
    } on DioException catch (e) {
      throw mapDioError(e);
    }
  }

  Future<ServerInfo> validate() async {
    try {
      final res = await _dio.get<Map<String, dynamic>>(
        '/v1/meetings/config/validate',
      );
      final body = res.data!;
      return ServerInfo(
        userName: ((body['user'] as Map?)?['display_name'] ?? '') as String,
        tenantName: ((body['tenant'] as Map?)?['name'] ?? '') as String,
      );
    } on DioException catch (e) {
      throw mapDioError(e);
    }
  }

  List<int> _ints(Object? raw) => [
    for (final v in (raw as List? ?? const [])) (v as num).toInt(),
  ];

  @override
  Future<RemoteSession> createSession({
    required String clientMeetingId,
    required String title,
    required DateTime startedAt,
    required String appVersion,
  }) async {
    try {
      final res = await _dio.post<Map<String, dynamic>>(
        '/v1/meetings/sessions',
        data: {
          'client_meeting_id': clientMeetingId,
          'title': title,
          'started_at': startedAt.toUtc().toIso8601String(),
          'sample_rate': 16000,
          'channels': 1,
          'app_version': appVersion,
          'input_kind': 'text',
        },
      );
      final body = res.data!;
      return RemoteSession(
        meetingId: body['meeting_id'] as String,
        status: body['status'] as String,
        receivedSeqs: _ints(body['received_seqs']),
        inputKind: (body['input_kind'] as String?) ?? 'audio',
      );
    } on DioException catch (e) {
      throw mapDioError(e);
    }
  }

  @override
  Future<void> putChunk({
    required String meetingId,
    required int seq,
    required String filePath,
    required int startMs,
    required int endMs,
    required String sha256,
    String? deviceText,
  }) async {
    try {
      await _dio.put<Object?>(
        '/v1/meetings/$meetingId/chunks/$seq',
        data: FormData.fromMap({
          'audio': await MultipartFile.fromFile(filePath, filename: '$seq.wav'),
          't_start_ms': startMs,
          't_end_ms': endMs,
          'sha256': sha256,
          if (deviceText != null) 'device_text': deviceText,
        }),
      );
    } on DioException catch (e) {
      throw mapDioError(e);
    }
  }

  @override
  Future<void> putTranscript({
    required String meetingId,
    required List<Segment> segments,
    String? asrIdentity,
  }) async {
    try {
      await _dio.put<Object?>(
        '/v1/meetings/$meetingId/transcript',
        data: {
          'segments': [
            for (final s in segments)
              {
                't_start_ms': s.startMs,
                't_end_ms': s.endMs < s.startMs ? s.startMs : s.endMs,
                'text': s.text.length > 4000
                    ? s.text.substring(0, 4000)
                    : s.text,
              },
          ],
          'asr_identity': ?asrIdentity,
        },
        options: Options(sendTimeout: const Duration(minutes: 2)),
      );
    } on DioException catch (e) {
      throw mapDioError(e);
    }
  }

  @override
  Future<RemoteStatus> status(String meetingId) async {
    try {
      final res = await _dio.get<Map<String, dynamic>>(
        '/v1/meetings/$meetingId/status',
      );
      final body = res.data!;
      return RemoteStatus(
        status: body['status'] as String,
        receivedSeqs: _ints(body['received_seqs']),
        progressPct: (body['progress_pct'] as num?)?.toInt() ?? 0,
        progressDetail: body['progress_detail'] as String?,
        errorCode: body['error_code'] as String?,
      );
    } on DioException catch (e) {
      throw mapDioError(e);
    }
  }

  @override
  Future<void> finish({
    required String meetingId,
    required DateTime endedAt,
    required int totalChunks,
    required int durationMs,
  }) async {
    try {
      await _dio.post<Object?>(
        '/v1/meetings/$meetingId/finish',
        data: {
          'ended_at': endedAt.toUtc().toIso8601String(),
          'total_chunks': totalChunks,
          'duration_ms': durationMs,
        },
      );
    } on DioException catch (e) {
      throw mapDioError(e);
    }
  }
}
