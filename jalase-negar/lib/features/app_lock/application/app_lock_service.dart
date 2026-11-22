import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:local_auth/local_auth.dart';

/// Result of one [AppLockService.authenticate] attempt.
sealed class AppLockAuthResult {
  const AppLockAuthResult();
}

class AppLockSuccess extends AppLockAuthResult {
  const AppLockSuccess();
}

/// A failed attempt the user can retry (wrong finger, cancelled, lockout…).
class AppLockFailed extends AppLockAuthResult {
  const AppLockFailed(this.message, {this.canRetry = true});

  final String message;
  final bool canRetry;
}

/// The device itself can no longer authenticate the user at all (no
/// biometric and no PIN/pattern/password set up, or the hardware is gone) —
/// the caller should stop depending on the lock rather than keep retrying.
class AppLockUnsupported extends AppLockAuthResult {
  const AppLockUnsupported(this.message);

  final String message;
}

/// Wraps the device's own authentication (fingerprint/Face ID, falling back
/// to the phone's PIN/pattern/password) — the app never shows its own PIN UI.
abstract class AppLockService {
  /// Whether the device has at least one authentication method configured
  /// (biometric enrolled, or a screen lock/passcode set).
  Future<bool> isSupported();

  Future<AppLockAuthResult> authenticate();
}

/// Persian message shown for a given `local_auth` `PlatformException` code.
/// Pulled out as a pure function so it can be unit-tested without touching
/// the plugin.
AppLockAuthResult mapAuthException(PlatformException e) {
  switch (e.code) {
    case 'NotAvailable':
      return const AppLockUnsupported(
        'قابلیت احراز هویت در این دستگاه موجود نیست.',
      );
    case 'NotEnrolled':
      return const AppLockUnsupported(
        'هیچ اثر انگشت، چهره یا رمز/الگوی صفحه‌قفلی ثبت نشده است. '
        'از تنظیمات گوشی یکی اضافه کنید.',
      );
    case 'PasscodeNotSet':
      return const AppLockUnsupported(
        'رمز یا الگوی صفحه‌قفل گوشی تنظیم نشده است.',
      );
    case 'LockedOut':
      return const AppLockFailed(
        'به دلیل تلاش‌های ناموفق زیاد، چند لحظه صبر کنید و دوباره تلاش کنید.',
      );
    case 'PermanentlyLockedOut':
      return const AppLockFailed(
        'احراز هویت بیومتریک قفل شده است؛ به‌جای آن از رمز یا الگوی '
        'صفحه‌قفل گوشی استفاده کنید.',
      );
    default:
      return const AppLockFailed('خطا در تأیید هویت. دوباره تلاش کنید.');
  }
}

class LocalAuthAppLockService implements AppLockService {
  final LocalAuthentication _auth = LocalAuthentication();

  @override
  Future<bool> isSupported() async {
    try {
      return await _auth.isDeviceSupported();
    } catch (_) {
      return false;
    }
  }

  @override
  Future<AppLockAuthResult> authenticate() async {
    try {
      final ok = await _auth.authenticate(
        localizedReason: 'برای باز کردن جلسه‌نگار هویت خود را تأیید کنید',
        options: const AuthenticationOptions(
          biometricOnly: false,
          stickyAuth: true,
        ),
      );
      // A plain `false` with no exception means the user cancelled or backed
      // out of the system prompt — not an error, just stay locked and let
      // them tap "باز کردن قفل" again.
      return ok ? const AppLockSuccess() : const AppLockFailed('', canRetry: true);
    } on PlatformException catch (e) {
      return mapAuthException(e);
    }
  }
}

final appLockServiceProvider = Provider<AppLockService>(
  (ref) => LocalAuthAppLockService(),
);
