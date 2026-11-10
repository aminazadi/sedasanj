import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Shared secure-storage instance (Keystore on Android, Keychain on Apple).
///
/// macOS uses the data-protection keychain, which needs the
/// `keychain-access-groups` entitlement in `macos/Runner/*.entitlements` and
/// a real signing team; an ad-hoc signed build fails with OSStatus -34018.
const FlutterSecureStorage appSecureStorage = FlutterSecureStorage();
