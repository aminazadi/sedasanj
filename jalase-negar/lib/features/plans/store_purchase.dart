import '../../core/platform/api_client.dart';

/// What the store's own billing SDK must offer. The Bazaar (Poolakey) and Myket (`myket_iap`)
/// bindings implement this; the flow below is the same for both stores.
abstract class StoreBillingSdk {
  /// Opens the store's payment sheet for [sku]; returns the purchase token, or null when the
  /// person cancelled. [developerPayload] is echoed back by the store and checked by the server.
  Future<String?> purchase(String sku, String developerPayload);

  /// Tells the store the purchase was used, so the same product can be bought again next month.
  Future<void> consume(String purchaseToken);
}

class StorePurchaseResult {
  const StorePurchaseResult({required this.activated});

  /// False when the person cancelled the store sheet.
  final bool activated;
}

/// Buys one product through the store and asks the server to activate it. The purchase is
/// consumed only after the server confirmed it, so a failed or interrupted call can be retried
/// with the same token and the person is never charged without getting the plan.
Future<StorePurchaseResult> buyFromStore({
  required ApiClient api,
  required StoreBillingSdk sdk,
  required String store,
  required String sku,
}) async {
  final skus = await api.storeSkus(store);
  if (!skus.skuToPlan.containsKey(sku) && !skus.skuToPack.containsKey(sku)) {
    throw StateError('محصول در این مارکت برای فروش فعال نیست.');
  }
  final token = await sdk.purchase(sku, skus.payload);
  if (token == null) return const StorePurchaseResult(activated: false);
  await api.verifyStorePurchase(store: store, sku: sku, purchaseToken: token);
  await sdk.consume(token);
  return const StorePurchaseResult(activated: true);
}
