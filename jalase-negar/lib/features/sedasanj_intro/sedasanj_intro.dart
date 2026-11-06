import 'package:dio/dio.dart';

import '../updates/data/app_update.dart';

/// The server-managed text of the "meet SedaSanj" drawer.
class SedasanjIntroContent {
  const SedasanjIntroContent({
    required this.enabled,
    required this.delayDays,
    required this.title,
    required this.body,
    required this.videoUrl,
    required this.buttonLabel,
    required this.buttonUrl,
  });

  final bool enabled;

  /// Days of use before the drawer first appears.
  final int delayDays;
  final String title;
  final String body;

  /// Empty when the admin set no video.
  final Uri? videoUrl;
  final String buttonLabel;
  final Uri buttonUrl;

  /// Throws [FormatException] for a malformed body or any non-https link.
  static SedasanjIntroContent fromJson(Object? json) {
    if (json is! Map) throw const FormatException('intro is not an object');
    String text(String key) {
      final v = json[key];
      if (v is! String) throw FormatException('intro "$key" is not text');
      return v;
    }

    Uri? https(String raw) {
      if (raw.isEmpty) return null;
      final uri = Uri.tryParse(raw);
      if (uri == null || uri.scheme != 'https' || uri.host.isEmpty) {
        throw FormatException('intro link is not https: $raw');
      }
      return uri;
    }

    final days = json['delay_days'];
    final button = https(text('button_url'));
    if (button == null) throw const FormatException('intro has no button link');
    return SedasanjIntroContent(
      enabled: json['enabled'] == true,
      delayDays: days is num ? days.toInt().clamp(0, 365) : 3,
      title: text('title'),
      body: text('body'),
      videoUrl: https(text('video_url')),
      buttonLabel: text('button_label'),
      buttonUrl: button,
    );
  }
}

/// How long after the drawer was closed without "don't show again" it may
/// come back.
const sedasanjIntroRepeatDays = 7;

/// Local rules for showing the drawer. The server content (enabled flag and
/// delay) is applied after it has been fetched.
bool shouldShowSedasanjIntro({
  required DateTime now,
  required DateTime firstUse,
  required DateTime? lastShown,
  required bool dismissedForever,
  required bool connected,
  required int delayDays,
  bool enabled = true,
}) {
  if (!enabled || connected || dismissedForever) return false;
  if (now.difference(firstUse) < Duration(days: delayDays)) return false;
  if (lastShown != null &&
      now.difference(lastShown) <
          const Duration(days: sedasanjIntroRepeatDays)) {
    return false;
  }
  return true;
}

/// Reads the drawer content from the central backend. It needs no token, so it
/// works before the app is connected. Returns null on any failure: the drawer
/// is a courtesy and must never bother the user with errors.
class SedasanjIntroClient {
  SedasanjIntroClient({Dio? dio})
    : _dio =
          dio ??
          Dio(
            BaseOptions(
              baseUrl: kUpdateOrigin,
              connectTimeout: const Duration(seconds: 5),
              receiveTimeout: const Duration(seconds: 5),
              followRedirects: false,
              responseType: ResponseType.json,
            ),
          );

  final Dio _dio;

  Future<SedasanjIntroContent?> fetch() async {
    try {
      final res = await _dio.get<Object?>(
        '/v1/jalase-negar/android/sedasanj-intro',
        options: Options(headers: {'Accept': 'application/json'}),
      );
      return SedasanjIntroContent.fromJson(res.data);
    } on DioException {
      return null;
    } on FormatException {
      return null;
    }
  }
}
