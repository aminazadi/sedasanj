import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../core/platform/secure_storage.dart';

/// A store purchase whose server confirmation has not succeeded yet. It is
/// kept in secure storage until the server accepts it and the store consumes
/// it, so money paid is never lost when the app is closed or the network
/// fails between the payment sheet and the confirmation.
class PendingStorePurchase {
  const PendingStorePurchase({
    required this.store,
    required this.sku,
    required this.token,
  });

  final String store;
  final String sku;
  final String token;

  Map<String, String> toJson() => {'store': store, 'sku': sku, 'token': token};

  static PendingStorePurchase? fromJson(Object? raw) {
    if (raw is! Map) return null;
    final store = raw['store'];
    final sku = raw['sku'];
    final token = raw['token'];
    if (store is! String || sku is! String || token is! String) return null;
    return PendingStorePurchase(store: store, sku: sku, token: token);
  }
}

abstract class PendingPurchaseStore {
  Future<void> save(PendingStorePurchase purchase);
  Future<PendingStorePurchase?> load();
  Future<void> clear();
}

class SecurePendingPurchaseStore implements PendingPurchaseStore {
  SecurePendingPurchaseStore({FlutterSecureStorage? storage})
    : _storage = storage ?? appSecureStorage;

  static const _key = 'pending_store_purchase';
  final FlutterSecureStorage _storage;

  @override
  Future<void> save(PendingStorePurchase purchase) =>
      _storage.write(key: _key, value: jsonEncode(purchase.toJson()));

  @override
  Future<PendingStorePurchase?> load() async {
    final raw = await _storage.read(key: _key);
    if (raw == null) return null;
    try {
      return PendingStorePurchase.fromJson(jsonDecode(raw));
    } on FormatException {
      return null;
    }
  }

  @override
  Future<void> clear() => _storage.delete(key: _key);
}
