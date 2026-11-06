import 'dart:io';

/// Which channel this build was made for. Set with `--dart-define=STORE=<name>`:
/// `direct` (default: our own server, with the in-app updater), `bazaar`, `myket`,
/// `sibapp`, `anardooni`, `desktop` (Windows/macOS). Store builds are updated by the store, never by the app itself.
const String kStoreChannel = String.fromEnvironment(
  'STORE',
  defaultValue: 'direct',
);

/// True only for the direct Android build, the one that may download and install its own APK.
bool get selfUpdateEnabled => kStoreChannel == 'direct' && Platform.isAndroid;

/// Whether the Settings "check for update" card is shown (only builds that update themselves).
bool get updateCardVisible => kStoreChannel == 'direct';

/// The Android/iOS foreground service keeps recording alive with the screen off; desktops have none.
bool get hasForegroundService => Platform.isAndroid || Platform.isIOS;

/// `mobile_scanner` has no Windows implementation, so QR scanning is hidden there
/// (config file and pasted text still connect the app).
bool get qrScanSupported => !Platform.isWindows;
