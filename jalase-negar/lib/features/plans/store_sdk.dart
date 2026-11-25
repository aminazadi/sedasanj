import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter_poolakey/flutter_poolakey.dart';
import 'package:myket_iap/myket_iap.dart';
import 'package:myket_iap/util/constants.dart';
import 'package:myket_iap/util/inventory.dart';
import 'package:myket_iap/util/purchase.dart';

import '../../core/platform/distribution.dart';
import 'store_purchase.dart';

/// Myket's RSA key from its developer console, passed at build time
/// (`--dart-define=MYKET_RSA_KEY=...`). The server still verifies every purchase itself.
const String _myketRsaKey = String.fromEnvironment('MYKET_RSA_KEY');

/// The billing SDK of this build's store, or null for builds that pay through the bank gateway.
StoreBillingSdk? storeSdkForChannel(String channel) {
  switch (channel) {
    case 'bazaar':
      return BazaarBillingSdk();
    case 'myket':
      return MyketBillingSdk();
  }
  return null;
}

StoreBillingSdk? get currentStoreSdk => storeSdkForChannel(kStoreChannel);

/// Cafe Bazaar through `flutter_poolakey`. Official docs:
/// https://github.com/cafebazaar/flutter_poolakey (connect, purchase, consume).
/// The local signature check is disabled (`connect(null)`, allowed by the plugin) because the
/// server verifies the purchase with Bazaar's REST API.
class BazaarBillingSdk implements StoreBillingSdk {
  bool _connected = false;

  Future<void> _connect() async {
    if (_connected) return;
    final done = Completer<void>();
    await FlutterPoolakey.connect(
      null,
      onSucceed: () {
        if (!done.isCompleted) done.complete();
      },
      onFailed: () {
        if (!done.isCompleted) {
          done.completeError(
            StateError('کافه‌بازار روی گوشی نصب یا آماده نیست.'),
          );
        }
      },
      onDisconnected: () => _connected = false,
    );
    await done.future.timeout(const Duration(seconds: 15));
    _connected = true;
  }

  @override
  Future<String?> purchase(String sku, String developerPayload) async {
    await _connect();
    // A purchase that was paid but never consumed (for example the app was closed before the
    // server answered) is picked up again instead of asking the person to pay twice.
    for (final owned in await FlutterPoolakey.getAllPurchasedProducts()) {
      if (owned.productId == sku &&
          owned.purchaseState == PurchaseState.PURCHASED) {
        return owned.purchaseToken;
      }
    }
    try {
      final info = await FlutterPoolakey.purchase(
        sku,
        payload: developerPayload,
      );
      return info.purchaseToken;
    } on PlatformException {
      // The plugin reports a cancelled sheet and a failure the same way (⚠ needs lab
      // confirmation); nothing was charged in either case, so the person can try again.
      return null;
    }
  }

  @override
  Future<void> consume(String purchaseToken) async {
    await _connect();
    await FlutterPoolakey.consume(purchaseToken);
  }
}

/// Myket through `myket_iap`. Official docs: https://github.com/myketstore/billing-sample-flutter
class MyketBillingSdk implements StoreBillingSdk {
  bool _ready = false;
  final _owned = <String, Purchase>{};

  Future<void> _init() async {
    if (_ready) return;
    if (_myketRsaKey.isEmpty) {
      throw StateError('کلید پرداخت مایکت در این نسخه تنظیم نشده است.');
    }
    final result = await MyketIAP.init(rsaKey: _myketRsaKey);
    if (result == null || !result.isSuccess()) {
      throw StateError('مایکت روی گوشی نصب یا آماده نیست.');
    }
    _ready = true;
  }

  @override
  Future<String?> purchase(String sku, String developerPayload) async {
    await _init();
    final inventory = await MyketIAP.queryInventory(
      querySkuDetails: false,
      skus: [sku],
    );
    final existing =
        (inventory[MyketIAP.INVENTORY] as Inventory?)?.mPurchaseMap[sku];
    if (existing != null) {
      _owned[existing.mToken] = existing;
      return existing.mToken;
    }
    final response = await MyketIAP.launchPurchaseFlow(
      sku: sku,
      payload: developerPayload,
    );
    final result = response[MyketIAP.RESULT];
    final purchase = response[MyketIAP.PURCHASE] as Purchase?;
    if (result != null && result.isSuccess() && purchase != null) {
      _owned[purchase.mToken] = purchase;
      return purchase.mToken;
    }
    final code = result?.mResponse;
    if (code == Constants.BILLING_RESPONSE_RESULT_USER_CANCELED ||
        code == Constants.IABHELPER_USER_CANCELLED) {
      return null;
    }
    throw StateError('خرید در مایکت انجام نشد؛ دوباره تلاش کنید.');
  }

  @override
  Future<void> consume(String purchaseToken) async {
    var purchase = _owned.remove(purchaseToken);
    if (purchase == null) {
      // A retry after an app restart has a fresh SDK instance and no memory
      // of the purchase, so look it up in the store's inventory.
      await _init();
      final inventory = await MyketIAP.queryInventory(
        querySkuDetails: false,
        skus: <String>[],
      );
      final owned = (inventory[MyketIAP.INVENTORY] as Inventory?)?.mPurchaseMap;
      for (final candidate in owned?.values ?? const <Purchase>[]) {
        if (candidate.mToken == purchaseToken) {
          purchase = candidate;
          break;
        }
      }
    }
    if (purchase == null) {
      throw StateError(
        'خرید تأییدشده در مایکت پیدا نشد؛ اپ را دوباره باز کنید تا دوباره بررسی شود.',
      );
    }
    await MyketIAP.consume(purchase: purchase);
  }
}
