import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/platform/api_client.dart';
import 'package:jalase_negar/features/plans/store_purchase.dart';

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

void main() {
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
