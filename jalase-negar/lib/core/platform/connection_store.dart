import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../db/app_database.dart';
import 'platform_config.dart';

const _kServerUrl = 'platform_server_url';
const _kUserName = 'platform_user_name';
const _kTenantName = 'platform_tenant_name';
const _kTokenPrefix = 'platform_token_prefix';
const _kTokenKey = 'platform_token';

/// Persists the SedaSanj connection: metadata in the app DB, the token only
/// in the platform secure storage (Keystore / Keychain).
class ConnectionStore {
  ConnectionStore(this._db, {FlutterSecureStorage? secure})
    : _secure = secure ?? const FlutterSecureStorage();

  final AppDatabase _db;
  final FlutterSecureStorage _secure;

  Future<PlatformConnection?> load() async {
    final url = await _db.getSetting(_kServerUrl);
    if (url == null) return null;
    return PlatformConnection(
      serverUrl: url,
      userName: await _db.getSetting(_kUserName) ?? '',
      tenantName: await _db.getSetting(_kTenantName) ?? '',
      tokenPrefix: await _db.getSetting(_kTokenPrefix) ?? '',
    );
  }

  Future<String?> token() => _secure.read(key: _kTokenKey);

  Future<void> save(PlatformConnection connection, String token) async {
    await _secure.write(key: _kTokenKey, value: token);
    await _db.setSetting(_kServerUrl, connection.serverUrl);
    await _db.setSetting(_kUserName, connection.userName);
    await _db.setSetting(_kTenantName, connection.tenantName);
    await _db.setSetting(_kTokenPrefix, connection.tokenPrefix);
  }

  Future<void> clear() async {
    await _secure.delete(key: _kTokenKey);
    await _db.db.delete(
      'settings',
      where: 'key IN (?, ?, ?, ?)',
      whereArgs: [_kServerUrl, _kUserName, _kTenantName, _kTokenPrefix],
    );
  }
}
