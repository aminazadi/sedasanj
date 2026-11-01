import 'package:flutter/foundation.dart';

const kConfigSchema = 'sedasanj.jalase-negar.config';
const kConfigVersion = 1;

/// Thrown when a scanned/imported config cannot be used; [message] is a
/// Persian text that names the next action for the user.
class ConfigParseException implements Exception {
  const ConfigParseException(this.message);

  final String message;

  @override
  String toString() => message;
}

/// One-time pairing payload carried by the panel QR code / config file.
/// It never contains a long-lived token.
class PairingPayload {
  const PairingPayload({
    required this.serverUrl,
    required this.pairingCode,
    this.expiresAt,
  });

  final String serverUrl;
  final String pairingCode;
  final DateTime? expiresAt;
}

bool _isLocalHost(String host) =>
    host == 'localhost' ||
    host == '127.0.0.1' ||
    host == '10.0.2.2' ||
    host.endsWith('.localhost') ||
    host.endsWith('.test');

/// Normalizes a server URL: https only (http allowed for local development
/// hosts, and anywhere in debug builds), no query/fragment, no trailing slash.
String normalizeServerUrl(String raw, {bool allowInsecure = kDebugMode}) {
  final uri = Uri.tryParse(raw.trim());
  if (uri == null || !uri.hasAuthority || uri.host.isEmpty) {
    throw const ConfigParseException(
      'آدرس سرور نامعتبر است؛ فایل یا QR جدید را از پنل بگیرید.',
    );
  }
  final isHttps = uri.scheme == 'https';
  final isHttp = uri.scheme == 'http';
  if (!isHttps && !isHttp) {
    throw const ConfigParseException(
      'آدرس سرور باید با https شروع شود؛ فایل یا QR جدید را از پنل بگیرید.',
    );
  }
  if (isHttp && !allowInsecure && !_isLocalHost(uri.host)) {
    throw const ConfigParseException(
      'اتصال ناامن (http) پذیرفته نمی‌شود؛ پنل را با آدرس https باز کنید و کانفیگ جدید بگیرید.',
    );
  }
  final path = uri.path.endsWith('/')
      ? uri.path.substring(0, uri.path.length - 1)
      : uri.path;
  return Uri(
    scheme: uri.scheme,
    host: uri.host,
    port: uri.hasPort ? uri.port : null,
    path: path,
  ).toString();
}

PairingPayload parsePairingPayload(
  Object? decoded, {
  DateTime? now,
  bool allowInsecure = kDebugMode,
}) {
  if (decoded is! Map || decoded['schema'] != kConfigSchema) {
    throw const ConfigParseException(
      'این فایل یا QR مربوط به جلسه‌نگار نیست؛ از صفحه‌ی پروفایل پنل، کانفیگ اپ را دوباره بگیرید.',
    );
  }
  if (decoded['version'] != kConfigVersion) {
    throw const ConfigParseException(
      'نسخه‌ی کانفیگ پشتیبانی نمی‌شود؛ اپ را به‌روز کنید یا کانفیگ جدید بگیرید.',
    );
  }
  final serverUrl = decoded['server_url'];
  final code = decoded['pairing_code'];
  if (serverUrl is! String || code is! String || code.trim().isEmpty) {
    throw const ConfigParseException(
      'کانفیگ ناقص است؛ کانفیگ جدید از پنل بگیرید.',
    );
  }
  DateTime? expiresAt;
  final rawExpiry = decoded['expires_at'];
  if (rawExpiry is String) {
    expiresAt = DateTime.tryParse(rawExpiry);
    if (expiresAt != null && expiresAt.isBefore(now ?? DateTime.now())) {
      throw const ConfigParseException(
        'کد جفت‌سازی منقضی شده است؛ در پنل کد جدید بسازید.',
      );
    }
  }
  return PairingPayload(
    serverUrl: normalizeServerUrl(serverUrl, allowInsecure: allowInsecure),
    pairingCode: code.trim(),
    expiresAt: expiresAt,
  );
}

/// Connection to a SedaSanj organization. The token lives only in secure
/// storage and is not part of this value.
class PlatformConnection {
  const PlatformConnection({
    required this.serverUrl,
    required this.userName,
    required this.tenantName,
    required this.tokenPrefix,
  });

  final String serverUrl;
  final String userName;
  final String tenantName;
  final String tokenPrefix;
}
