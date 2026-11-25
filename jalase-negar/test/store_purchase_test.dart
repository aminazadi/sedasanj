import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/platform/api_client.dart';
import 'package:jalase_negar/features/plans/store_purchase.dart';
import 'package:jalase_negar/features/plans/store_purchase_store.dart';

class _Api extends ApiClient {
  _Api({this.verifyFails = false}) : super(serverUrl: 'https://example.test');
  final bool verifyFails;
  final verified = <String>[];

  @override
  Future<
    ({
      Map<String, String> skuToPlan,
      Map<String, String> skuToPack,
      String payload,
    })
  >
  storeSkus(String store) async => (
    skuToPlan: {'jn_plus_month': 'jn_plus'},
    skuToPack: <String, String>{},
    payload: 'tenant-1',
  );

  @override
  Future<void> verifyStorePurchase({
    required String store,
    required String sku,
    required String purchaseToken,
  }) async {
    if (verifyFails) throw StateError('server said no');
    verified.add('$store:$sku:$purchaseToken');
  }
}

class _Sdk implements StoreBillingSdk {
  _Sdk(this.token);
  final String? token;
  final payloads = <String>[];
  final consumed = <String>[];

  @override
  Future<String?> purchase(String sku, String developerPayload) async {
    payloads.add(developerPayload);
    return token;
  }

  @override
  Future<void> consume(String purchaseToken) async =>
      consumed.add(purchaseToken);
}

class _Pending implements PendingPurchaseStore {
  PendingStorePurchase? value;

  @override
  Future<void> save(PendingStorePurchase purchase) async => value = purchase;

  @override
  Future<PendingStorePurchase?> load() async => value;

  @override
  Future<void> clear() async => value = null;
}

void main() {
  test('a plan is bought through the store product mapped to it', () async {
    final api = _Api();
    final sdk = _Sdk('tok-4');
    await buyFromStore(
      api: api,
      sdk: sdk,
      store: 'bazaar',
      planCode: 'jn_plus',
    );
    expect(api.verified, ['bazaar:jn_plus_month:tok-4']);
    await expectLater(
      buyFromStore(api: api, sdk: sdk, store: 'bazaar', planCode: 'jn_gold'),
      throwsStateError,
    );
  });

  test(
    'the server confirms first and the purchase is consumed only afterwards',
    () async {
      final api = _Api();
      final sdk = _Sdk('tok-1');
      final result = await buyFromStore(
        api: api,
        sdk: sdk,
        store: 'myket',
        sku: 'jn_plus_month',
      );
      expect(result.activated, isTrue);
      expect(api.verified, ['myket:jn_plus_month:tok-1']);
      expect(sdk.payloads, ['tenant-1']);
      expect(sdk.consumed, ['tok-1']);
    },
  );

  test('a cancelled store sheet changes nothing', () async {
    final api = _Api();
    final sdk = _Sdk(null);
    final result = await buyFromStore(
      api: api,
      sdk: sdk,
      store: 'bazaar',
      sku: 'jn_plus_month',
    );
    expect(result.activated, isFalse);
    expect(api.verified, isEmpty);
    expect(sdk.consumed, isEmpty);
  });

  test(
    'a rejected verification keeps the purchase unconsumed for a retry',
    () async {
      final sdk = _Sdk('tok-2');
      await expectLater(
        buyFromStore(
          api: _Api(verifyFails: true),
          sdk: sdk,
          store: 'bazaar',
          sku: 'jn_plus_month',
        ),
        throwsStateError,
      );
      expect(sdk.consumed, isEmpty);
    },
  );

  test('a paid token survives a failed confirmation and is retried', () async {
    final pending = _Pending();
    final sdk = _Sdk('tok-5');
    await expectLater(
      buyFromStore(
        api: _Api(verifyFails: true),
        sdk: sdk,
        store: 'bazaar',
        sku: 'jn_plus_month',
        pending: pending,
      ),
      throwsStateError,
    );
    expect(pending.value?.token, 'tok-5');
    expect(sdk.consumed, isEmpty);

    final api = _Api();
    final done = await retryPendingPurchase(
      api: api,
      sdk: sdk,
      pending: pending,
    );
    expect(done, isTrue);
    expect(api.verified, ['bazaar:jn_plus_month:tok-5']);
    expect(sdk.consumed, ['tok-5']);
    expect(pending.value, isNull);
  });

  test(
    'a product the server does not sell is refused before any payment',
    () async {
      final sdk = _Sdk('tok-3');
      await expectLater(
        buyFromStore(api: _Api(), sdk: sdk, store: 'myket', sku: 'unknown'),
        throwsStateError,
      );
      expect(sdk.payloads, isEmpty);
    },
  );
}
