import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Shared secure-storage instance (Keystore on Android, Keychain on Apple,
/// Credential Manager on Windows).
///
/// macOS uses the legacy (login) keychain: the data-protection keychain needs
/// the `keychain-access-groups` entitlement plus a provisioning profile tied to
/// registered devices, so a build on another Mac failed to save the token
/// (OSStatus -34018) or was killed at launch. The legacy keychain works with
/// the app's own ad-hoc or Developer ID signature.
const FlutterSecureStorage appSecureStorage = FlutterSecureStorage(
  mOptions: MacOsOptions(usesDataProtectionKeychain: false),
);
