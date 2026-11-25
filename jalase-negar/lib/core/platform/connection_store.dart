import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:jalase_negar/core/platform/secure_storage.dart';

import '../db/app_database.dart';
import 'platform_config.dart';

const _kServerUrl = 'platform_server_url';
const _kUserName = 'platform_user_name';
const _kTenantName = 'platform_tenant_name';
const _kTokenPrefix = 'platform_token_prefix';
const _kTokenKey = 'platform_token';
const _kPersonal = 'platform_personal';
const _kPushBinding = 'platform_push_binding';
const _kOrgLinkId = 'org_link_id';
const _kOrgName = 'org_name';
const _kOrgUser = 'org_user';
const _kOrgTokenKey = 'platform_org_token';
const _kWorkspaceDefault = 'workspace_default';

/// A SedaSanj organization linked to a personal account (its own device key).
class OrgLink {
  const OrgLink({
    required this.linkId,
    required this.organization,
    required this.userName,
  });

  final String linkId;
  final String organization;
  final String userName;
}

/// Persists the SedaSanj connection: metadata in the app DB, the token only
/// in the platform secure storage (Keystore / Keychain).
class ConnectionStore {
  ConnectionStore(this._db, {FlutterSecureStorage? secure})
    : _secure = secure ?? appSecureStorage;

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
      personal: await _db.getSetting(_kPersonal) == '1',
    );
  }

  Future<String?> token() => _secure.read(key: _kTokenKey);

  static String _binding(String origin, String token) =>
      '$origin\n${sha256.convert(utf8.encode(token))}';

  Future<void> preparePushBinding() async {
    final connection = await load();
    final secret = await token();
    if (connection == null ||
        connection.tokenPrefix.isEmpty ||
        secret == null ||
        !secret.startsWith(connection.tokenPrefix)) {
      return;
    }
    final binding = _binding(connection.serverUrl, secret);
    if (await _secure.read(key: _kPushBinding) != binding) {
      await _secure.write(key: _kPushBinding, value: binding);
    }
  }

  static Future<String?> pushToken(String origin) async {
    const storage = appSecureStorage;
    final secret = await storage.read(key: _kTokenKey);
    final binding = await storage.read(key: _kPushBinding);
    return secret != null && binding == _binding(origin, secret)
        ? secret
        : null;
  }

  Future<void> save(PlatformConnection connection, String token) async {
    // Best effort: the binding is checked against the token's hash when it is read, so a stale one
    // can never match the new token. On macOS without keychain entitlements the plugin's delete
    // fails with -34018 even for a key that does not exist, and that must not block signing in.
    await _deleteSecret(_kPushBinding);
    await _secure.write(key: _kTokenKey, value: token);
    await _db.setSetting(_kServerUrl, connection.serverUrl);
    await _db.setSetting(_kUserName, connection.userName);
    await _db.setSetting(_kTenantName, connection.tenantName);
    await _db.setSetting(_kTokenPrefix, connection.tokenPrefix);
    await _db.setSetting(_kPersonal, connection.personal ? '1' : '0');
    await _secure.write(
      key: _kPushBinding,
      value: _binding(connection.serverUrl, token),
    );
  }

  Future<OrgLink?> loadOrg() async {
    final id = await _db.getSetting(_kOrgLinkId);
    if (id == null) return null;
    return OrgLink(
      linkId: id,
      organization: await _db.getSetting(_kOrgName) ?? '',
      userName: await _db.getSetting(_kOrgUser) ?? '',
    );
  }

  Future<String?> orgToken() => _secure.read(key: _kOrgTokenKey);

  Future<void> saveOrg(OrgLink link, String token) async {
    await _secure.write(key: _kOrgTokenKey, value: token);
    await _db.setSetting(_kOrgLinkId, link.linkId);
    await _db.setSetting(_kOrgName, link.organization);
    await _db.setSetting(_kOrgUser, link.userName);
  }

  Future<void> clearOrg() async {
    await _deleteSecret(_kOrgTokenKey);
    await _db.db.delete(
      'settings',
      where: 'key IN (?, ?, ?, ?)',
      whereArgs: [_kOrgLinkId, _kOrgName, _kOrgUser, _kWorkspaceDefault],
    );
  }

  /// Workspace new meetings are sent to: [kWorkspaceOrg] only while an
  /// organization is linked, otherwise always the own account.
  Future<String> defaultWorkspace() async {
    if (await _db.getSetting(_kOrgLinkId) == null) return 'primary';
    return await _db.getSetting(_kWorkspaceDefault) == 'org'
        ? 'org'
        : 'primary';
  }

  Future<void> setDefaultWorkspace(String workspace) =>
      _db.setSetting(_kWorkspaceDefault, workspace);

  /// Removing a token must never block disconnecting: when the platform keychain refuses
  /// (for example macOS error -34018 on an unsigned debug build), the connection data in the
  /// app database is still cleared, and the orphaned token is unreachable without it.
  Future<void> _deleteSecret(String key) async {
    try {
      await _secure.delete(key: key);
    } on Object {
      // Ignored on purpose, see above.
    }
  }

  Future<void> clear() async {
    await clearOrg();
    await _deleteSecret(_kTokenKey);
    await _deleteSecret(_kPushBinding);
    await _db.db.delete(
      'settings',
      where: 'key IN (?, ?, ?, ?, ?)',
      whereArgs: [
        _kServerUrl,
        _kUserName,
        _kTenantName,
        _kTokenPrefix,
        _kPersonal,
      ],
    );
  }
}
