import 'package:flutter/services.dart';

import '../../../core/platform/distribution.dart';

const _channel = MethodChannel('app.jalasenegar.jalase_negar/update');

/// What the native self-updater (WorkManager worker and PackageInstaller)
/// needs from the Dart side, and what it can tell back. Android only; every
/// call degrades to a harmless default elsewhere or when the channel is
/// missing (tests, other platforms).
class UpdateNative {
  const UpdateNative();

  /// Tells the worker whether the app is in a calm moment. Written to native
  /// preferences so the worker can read it while the Dart isolate is gone.
  Future<void> publishCalmState({
    required bool recording,
    required int pendingChunks,
    required int textSyncPending,
  }) => _call<void>('setCalmState', {
    'recording': recording,
    'pendingChunks': pendingChunks,
    'textSyncPending': textSyncPending,
  });

  /// Registers the periodic background check (idempotent).
  Future<void> scheduleBackgroundUpdates() =>
      _call<void>('scheduleUpdates', null);

  /// Runs a check/install pass soon; used when the app goes to the background
  /// in a calm state with a downloaded update waiting.
  Future<void> runUpdatePassSoon() => _call<void>('runUpdatePass', null);

  Future<bool> canInstallPackages() async =>
      (await _call<bool>('canInstallPackages', null)) ?? false;

  /// Opens the system "install unknown apps" screen for this app.
  Future<bool> openInstallSettings() async =>
      (await _call<bool>('openInstallSettings', null)) ?? false;

  /// True once the one-time permission explainer has been answered.
  Future<bool> explainerShown() async =>
      (await _call<bool>('explainerShown', null)) ?? true;

  Future<void> markExplainerShown() => _call<void>('markExplainerShown', null);

  /// The version code the app was on before it was updated, or null when this
  /// launch is not the first one after an update. Reading it clears it.
  Future<int?> consumeUpdatedFrom() => _call<int>('consumeUpdatedFrom', null);

  /// Asks the installer to apply an already downloaded and verified update
  /// (the one-tap path); false when nothing is ready.
  Future<bool> installDownloaded() async =>
      (await _call<bool>('installDownloaded', null)) ?? false;

  Future<T?> _call<T>(String method, Object? arguments) async {
    if (!selfUpdateEnabled) return null;
    try {
      return await _channel.invokeMethod<T>(method, arguments);
    } on PlatformException {
      return null;
    } on MissingPluginException {
      return null;
    }
  }
}
