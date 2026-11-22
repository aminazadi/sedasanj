import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers.dart';
import 'app_lock_service.dart';

const String kAppLockEnabledSettingKey = 'app_lock_enabled';

/// The user's choice to require the device's own authentication to open the
/// app. Persisted like every other on/off setting in this app (not secret).
class AppLockEnabled extends AsyncNotifier<bool> {
  @override
  Future<bool> build() async {
    final db = await ref.watch(appDatabaseProvider.future);
    return await db.getSetting(kAppLockEnabledSettingKey) == '1';
  }

  Future<void> set(bool enabled) async {
    final db = await ref.read(appDatabaseProvider.future);
    await db.setSetting(kAppLockEnabledSettingKey, enabled ? '1' : '0');
    state = AsyncData(enabled);
  }
}

final appLockEnabledProvider = AsyncNotifierProvider<AppLockEnabled, bool>(
  AppLockEnabled.new,
);

/// Whether the device currently has any authentication method configured at
/// all. Re-read whenever requested (e.g. every time Settings builds) since
/// the user may add or remove a device PIN while the app is open.
final appLockDeviceSupportedProvider = FutureProvider<bool>(
  (ref) => ref.read(appLockServiceProvider).isSupported(),
);

/// Whether the app is *currently* locked, in memory only — never persisted.
/// A plain [ChangeNotifier] so it can double as GoRouter's
/// `refreshListenable`.
class AppLockRuntime extends ChangeNotifier {
  bool locked = false;

  void lock() {
    if (locked) return;
    locked = true;
    notifyListeners();
  }

  void unlock() {
    if (!locked) return;
    locked = false;
    notifyListeners();
  }
}

// A plain `Provider` is enough: riverpod 3 dropped `ChangeNotifierProvider`,
// and GoRouter's `refreshListenable` only needs the `Listenable` instance
// itself, not provider-managed rebuild-on-change semantics.
final appLockRuntimeProvider = Provider<AppLockRuntime>((ref) {
  final runtime = AppLockRuntime();
  ref.onDispose(runtime.dispose);
  return runtime;
});
