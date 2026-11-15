import 'dart:convert';

import 'package:dio/dio.dart';

import '../../features/meetings/data/attendee.dart';
import '../../features/meetings/data/meeting.dart';
import '../../features/people/data/speaker_payload.dart';
import 'speaker_api.dart';

/// Typed API failure with a Persian message that names the next action.
class ApiException implements Exception {
  const ApiException({
    required this.message,
    this.code,
    this.statusCode,
    this.requiresReconnect = false,
    this.missingSeqs = const [],
    this.details = const {},
  });

  final String message;
  final String? code;
  final int? statusCode;

  /// The token is no longer valid; the user must pair the app again.
  final bool requiresReconnect;

  /// Chunk numbers the server is still missing (`meeting_incomplete_chunks`).
  final List<int> missingSeqs;

  /// Extra fields of the server's error body (e.g. `current` of a speaker
  /// profile conflict).
  final Map<String, Object?> details;

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

/// Result of the first sign-in step: where to enter the code and how long to wait.
class OtpRequestResult {
  const OtpRequestResult({required this.otpId, required this.resendAfter});

  final String otpId;
  final Duration resendAfter;
}

/// A signed-in stand-alone (personal) account.
class PersonalLoginResult {
  const PersonalLoginResult({
    required this.token,
    required this.tokenPrefix,
    required this.userName,
    required this.created,
  });

  final String token;
  final String tokenPrefix;
  final String userName;
  final bool created;
}

/// Sign-in errors carry a Persian message that already names the next action;
/// show it as is. 401/403 here mean a wrong code or a closed sign-up, never a
/// revoked token, so they must not trigger the reconnect flow.
ApiException mapLoginError(DioException e) {
  final data = e.response?.data;
  final status = e.response?.statusCode;
  if (status != null && data is Map && data['error'] is Map) {
    final error = data['error'] as Map;
    final message = error['message']?.toString();
    if (message != null && message.trim().isNotEmpty) {
      return ApiException(
        message: message,
        code: error['code']?.toString(),
        statusCode: status,
      );
    }
  }
  return mapDioError(e);
}

/// The selected minutes of a meeting; `markdown` is null until they are ready.
class MinutesResult {
  const MinutesResult({required this.status, this.markdown});

  final String status;
  final String? markdown;
}

/// Plan and remaining allowance of a personal account.
class PersonalProfile {
  const PersonalProfile({
    required this.remainingSeconds,
    this.planName,
    this.monthlyMinutes,
  });

  final int remainingSeconds;
  final String? planName;
  final int? monthlyMinutes;
}

/// One input the admin asked for in a category (shown as a form field).
class OutputField {
  const OutputField({
    required this.key,
    required this.label,
    required this.type,
    required this.required,
    this.options = const [],
  });

  final String key;
  final String label;

  /// `text`, `select` or `number`.
  final String type;
  final bool required;
  final List<String> options;
}

/// A conversion category the admin published (counseling, lecture notes, ...).
class OutputTypeInfo {
  const OutputTypeInfo({
    required this.code,
    required this.title,
    required this.description,
    required this.automatic,
    required this.fields,
    this.thumbnailUrl,
  });

  final String code;
  final String title;
  final String description;

  /// Made automatically for every meeting (the minutes); not offered in the picker.
  final bool automatic;
  final List<OutputField> fields;
  final String? thumbnailUrl;
}

class DocumentInfo {
  const DocumentInfo({
    required this.id,
    required this.outputType,
    required this.status,
    required this.progressPct,
    this.errorCode,
    this.selectedVersion,
  });

  final String id;
  final String outputType;

  /// `queued`, `running`, `done` or `failed`.
  final String status;
  final int progressPct;
  final String? errorCode;
  final int? selectedVersion;

  bool get inProgress => status == 'queued' || status == 'running';
}

class DocumentDetail {
  const DocumentDetail({required this.info, this.markdown});

  final DocumentInfo info;
  final String? markdown;
}

/// Server messages of these calls already name the next action; keep them, except for a
/// revoked token (401), which must trigger the reconnect flow.
ApiException mapMessageError(DioException e) =>
    e.response?.statusCode == 401 ? mapDioError(e) : mapLoginError(e);

/// A failed download has a byte body; decode the JSON error inside it when there is one.
ApiException _bytesError(DioException e) {
  final raw = e.response?.data;
  if (raw is List<int>) {
    try {
      final decoded = jsonDecode(utf8.decode(raw));
      return mapMessageError(
        DioException(
          requestOptions: e.requestOptions,
          response: Response(
            requestOptions: e.requestOptions,
            statusCode: e.response?.statusCode,
            data: decoded,
          ),
        ),
      );
    } on Object {
      // Not JSON: fall through to the generic mapping.
    }
  }
  return mapMessageError(e);
}

DocumentInfo parseDocumentInfo(Map<String, dynamic> body) => DocumentInfo(
  id: body['id'] as String,
  outputType: body['output_type'] as String,
  status: body['status'] as String,
  progressPct: (body['progress_pct'] as num?)?.toInt() ?? 0,
  errorCode: body['error_code'] as String?,
  selectedVersion: (body['selected_version'] as num?)?.toInt(),
);

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
    List<Attendee> attendees = const [],
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
  var details = const <String, Object?>{};
  final data = e.response?.data;
  if (data is Map && data['error'] is Map) {
    final error = data['error'] as Map;
    code = error['code']?.toString();
    details = {for (final e in error.entries) e.key.toString(): e.value};
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
  final speaker = _speakerError(status, code, details);
  if (speaker != null) return speaker;
  return ApiException(
    message: 'خطای سرور (${status.toString()})؛ کمی بعد دوباره تلاش کنید.',
    code: code,
    statusCode: status,
    details: details,
  );
}

/// Persian explanations of the speaker-profile errors, each naming the next
/// action (see the `speaker_*` help articles).
ApiException? _speakerError(
  int status,
  String? code,
  Map<String, Object?> details,
) {
  final message = switch (code) {
    'speaker_profile_conflict' =>
      'این فرد روی دستگاه دیگری تغییر کرده است؛ اپ تغییرات را ادغام می‌کند و دوباره می‌فرستد.',
    'speaker_profile_not_found' =>
      'این فرد روی سرور پیدا نشد؛ فهرست افراد را تازه کنید.',
    'speaker_profile_limit' =>
      'تعداد افراد یا نمونه‌های صدا به سقف رسیده است؛ مواردِ بی‌استفاده را حذف کنید.',
    'speaker_consent_required' =>
      'برای ذخیره‌ی ردصدا باید رضایت همان فرد ثبت شود؛ مرحله‌ی رضایت‌نامه را کامل کنید و تاریخ و ساعت گوشی را بررسی کنید.',
    'speaker_voiceprint_invalid' =>
      'ردصدای ارسالی معتبر نیست؛ نمونه‌ی صدا را دوباره ضبط کنید.',
    'speaker_storage_unavailable' =>
      'ذخیره‌ی امن ردصدا روی سرور آماده نیست؛ چند دقیقه بعد دوباره تلاش می‌شود، و اگر ادامه داشت به مدیر صداسنج اطلاع دهید.',
    _ => null,
  };
  if (message == null) return null;
  return ApiException(
    message: message,
    code: code,
    statusCode: status,
    details: details,
  );
}

/// Thin SedaSanj API client. It never logs headers or bodies.
class ApiClient implements MeetingUploadApi, SpeakerSyncApi {
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

  /// Step 1 of phone sign-in: sends the SMS code.
  Future<OtpRequestResult> requestOtp(String mobile) async {
    try {
      final res = await _dio.post<Map<String, dynamic>>(
        '/v1/jalase-negar/auth/request',
        data: {'mobile': mobile},
      );
      final body = res.data!;
      return OtpRequestResult(
        otpId: body['otp_id'] as String,
        resendAfter: Duration(
          seconds: (body['resend_after'] as num?)?.toInt() ?? 60,
        ),
      );
    } on DioException catch (e) {
      throw mapLoginError(e);
    }
  }

  /// Step 2: checks the code; returns the short-lived token for step 3.
  Future<({String token, bool hasAccount})> verifyOtp({
    required String otpId,
    required String code,
  }) async {
    try {
      final res = await _dio.post<Map<String, dynamic>>(
        '/v1/jalase-negar/auth/verify',
        data: {'otp_id': otpId, 'code': code},
      );
      final body = res.data!;
      return (
        token: body['verified_token'] as String,
        hasAccount: body['has_account'] == true,
      );
    } on DioException catch (e) {
      throw mapLoginError(e);
    }
  }

  /// Step 3: signs in (or signs up) and returns the device token.
  Future<PersonalLoginResult> completeLogin({
    required String verifiedToken,
    required String deviceName,
    required String platform,
    required String appVersion,
    String? displayName,
  }) async {
    try {
      final res = await _dio.post<Map<String, dynamic>>(
        '/v1/jalase-negar/auth/complete',
        data: {
          'verified_token': verifiedToken,
          if (displayName != null && displayName.trim().isNotEmpty)
            'display_name': displayName.trim(),
          'device_name': deviceName,
          'platform': platform,
          'app_version': appVersion,
        },
      );
      final body = res.data!;
      return PersonalLoginResult(
        token: body['token'] as String,
        tokenPrefix: (body['token_prefix'] ?? '') as String,
        userName: ((body['user'] as Map?)?['display_name'] ?? '') as String,
        created: body['created'] == true,
      );
    } on DioException catch (e) {
      throw mapLoginError(e);
    }
  }

  /// Minutes of one of the signed-in user's meetings (personal accounts only).
  Future<MinutesResult> minutes(String remoteMeetingId) async {
    try {
      final res = await _dio.get<Map<String, dynamic>>(
        '/v1/jalase-negar/meetings/$remoteMeetingId/minutes',
      );
      final body = res.data!;
      return MinutesResult(
        status: (body['status'] ?? '') as String,
        markdown: body['markdown'] as String?,
      );
    } on DioException catch (e) {
      throw mapDioError(e);
    }
  }

  Future<PersonalProfile> personalProfile() async {
    try {
      final res = await _dio.get<Map<String, dynamic>>('/v1/jalase-negar/me');
      final body = res.data!;
      final plan = body['plan'] as Map?;
      return PersonalProfile(
        remainingSeconds: (body['remaining_seconds'] as num?)?.toInt() ?? 0,
        planName: plan?['name'] as String?,
        monthlyMinutes: (plan?['monthly_minutes'] as num?)?.toInt(),
      );
    } on DioException catch (e) {
      throw mapDioError(e);
    }
  }

  /// Revokes the device token on the server.
  Future<void> logout() async {
    try {
      await _dio.post<Object?>('/v1/jalase-negar/auth/logout');
    } on DioException catch (e) {
      throw mapDioError(e);
    }
  }

  Future<List<OutputTypeInfo>> outputTypes() async {
    try {
      final res = await _dio.get<Map<String, dynamic>>(
        '/v1/jalase-negar/output-types',
      );
      final base = _dio.options.baseUrl.replaceAll(RegExp(r'/+$'), '');
      return [
        for (final raw in (res.data!['items'] as List))
          () {
            final item = raw as Map<String, dynamic>;
            final thumb = item['thumbnail_url'] as String?;
            return OutputTypeInfo(
              code: item['code'] as String,
              title: item['title'] as String,
              description: (item['description'] ?? '') as String,
              automatic: item['automatic'] == true,
              thumbnailUrl: thumb == null ? null : '$base$thumb',
              fields: [
                for (final f in (item['input_fields'] as List? ?? const []))
                  OutputField(
                    key: (f as Map)['key'] as String,
                    label: f['label_fa'] as String,
                    type: (f['type'] ?? 'text') as String,
                    required: f['required'] == true,
                    options: [
                      for (final o in (f['options'] as List? ?? const []))
                        o as String,
                    ],
                  ),
              ],
            );
          }(),
      ];
    } on DioException catch (e) {
      throw mapMessageError(e);
    }
  }

  Future<List<DocumentInfo>> createDocuments(
    String remoteMeetingId,
    List<({String code, Map<String, String> values})> items,
  ) async {
    try {
      final res = await _dio.post<Map<String, dynamic>>(
        '/v1/jalase-negar/meetings/$remoteMeetingId/documents',
        data: {
          'items': [
            for (final i in items)
              {'output_type': i.code, 'input_values': i.values},
          ],
        },
      );
      return [
        for (final d in (res.data!['items'] as List))
          parseDocumentInfo(d as Map<String, dynamic>),
      ];
    } on DioException catch (e) {
      throw mapMessageError(e);
    }
  }

  Future<List<DocumentInfo>> listDocuments(String remoteMeetingId) async {
    try {
      final res = await _dio.get<Map<String, dynamic>>(
        '/v1/jalase-negar/meetings/$remoteMeetingId/documents',
      );
      return [
        for (final d in (res.data!['items'] as List))
          parseDocumentInfo(d as Map<String, dynamic>),
      ];
    } on DioException catch (e) {
      throw mapMessageError(e);
    }
  }

  Future<DocumentDetail> getDocument(String documentId) async {
    try {
      final res = await _dio.get<Map<String, dynamic>>(
        '/v1/jalase-negar/documents/$documentId',
      );
      final body = res.data!;
      return DocumentDetail(
        info: parseDocumentInfo(body),
        markdown: body['markdown'] as String?,
      );
    } on DioException catch (e) {
      throw mapMessageError(e);
    }
  }

  Future<void> editDocument(String documentId, String markdown) async {
    try {
      await _dio.patch<Object?>(
        '/v1/jalase-negar/documents/$documentId',
        data: {'markdown': markdown},
      );
    } on DioException catch (e) {
      throw mapMessageError(e);
    }
  }

  /// The selected version as a `pdf` or `docx` file's bytes.
  Future<List<int>> exportDocument(String documentId, String format) async {
    try {
      final res = await _dio.get<List<int>>(
        '/v1/jalase-negar/documents/$documentId/export',
        queryParameters: {'format': format},
        options: Options(
          responseType: ResponseType.bytes,
          receiveTimeout: const Duration(minutes: 2),
        ),
      );
      return res.data!;
    } on DioException catch (e) {
      throw _bytesError(e);
    }
  }

  Future<void> regenerateDocument(String documentId) async {
    try {
      await _dio.post<Object?>(
        '/v1/jalase-negar/documents/$documentId/regenerate',
        data: <String, Object?>{},
      );
    } on DioException catch (e) {
      throw mapMessageError(e);
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
    List<Attendee> attendees = const [],
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
          if (attendees.isNotEmpty)
            'attendees': [
              for (final a in attendees)
                {'profile_client_id': a.personId, 'name': a.name},
            ],
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
      final payload = buildTranscriptPayload(segments);
      await _dio.put<Object?>(
        '/v1/meetings/$meetingId/transcript',
        data: {
          'segments': payload.segments,
          'asr_identity': ?asrIdentity,
          if (payload.speakers.isNotEmpty) 'speakers': payload.speakers,
        },
        options: Options(sendTimeout: const Duration(minutes: 2)),
      );
    } on DioException catch (e) {
      throw mapDioError(e);
    }
  }

  @override
  Future<RemoteChanges> changes({required int cursor, int? limit}) async {
    try {
      final res = await _dio.get<Map<String, dynamic>>(
        '/v1/meetings/speaker-profiles/changes',
        queryParameters: {'cursor': cursor, 'limit': ?limit},
      );
      final body = res.data!;
      return RemoteChanges(
        items: [
          for (final item in (body['items'] as List? ?? const []))
            RemoteProfile.fromJson(item as Map<String, dynamic>),
        ],
        nextCursor: (body['next_cursor'] as num).toInt(),
        hasMore: body['has_more'] == true,
      );
    } on DioException catch (e) {
      throw mapDioError(e);
    }
  }

  @override
  Future<RemoteProfile> putProfile(
    String clientId,
    ProfilePutRequest request,
  ) async {
    try {
      final res = await _dio.put<Map<String, dynamic>>(
        '/v1/meetings/speaker-profiles/$clientId',
        data: request.toJson(),
        options: Options(sendTimeout: const Duration(minutes: 2)),
      );
      return RemoteProfile.fromJson(res.data!);
    } on DioException catch (e) {
      throw mapDioError(e);
    }
  }

  @override
  Future<RemoteProfile> deleteProfile(String clientId) async {
    try {
      final res = await _dio.delete<Map<String, dynamic>>(
        '/v1/meetings/speaker-profiles/$clientId',
      );
      return RemoteProfile.fromJson(res.data!);
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
