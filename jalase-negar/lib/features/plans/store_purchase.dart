import '../../core/platform/api_client.dart';
import 'store_purchase_store.dart';

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
  PendingPurchaseStore? pending,
  String? sku,
  String? planCode,
  String? packageId,
}) async {
  final skus = await api.storeSkus(store);
  if (sku == null) {
    // Find the store product that sells this plan or token pack.
    final map = planCode != null ? skus.skuToPlan : skus.skuToPack;
    final wanted = planCode ?? packageId;
    for (final entry in map.entries) {
      if (entry.value == wanted) sku = entry.key;
    }
  }
  if (sku == null ||
      (!skus.skuToPlan.containsKey(sku) && !skus.skuToPack.containsKey(sku))) {
    throw StateError('این محصول در مارکت برای فروش فعال نیست.');
  }
  final token = await sdk.purchase(sku, skus.payload);
  if (token == null) return const StorePurchaseResult(activated: false);
  // Remember the paid token before the network call: if the server cannot be
  // reached, the app retries it on the next start instead of asking the
  // person to pay again.
  final purchase = PendingStorePurchase(store: store, sku: sku, token: token);
  await pending?.save(purchase);
  await api.verifyStorePurchase(store: store, sku: sku, purchaseToken: token);
  await sdk.consume(token);
  await pending?.clear();
  return const StorePurchaseResult(activated: true);
}

/// Confirms a purchase that was paid earlier but never reached the server.
/// Returns true when one was waiting and is now activated.
Future<bool> retryPendingPurchase({
  required ApiClient api,
  required StoreBillingSdk sdk,
  required PendingPurchaseStore pending,
}) async {
  final purchase = await pending.load();
  if (purchase == null) return false;
  await api.verifyStorePurchase(
    store: purchase.store,
    sku: purchase.sku,
    purchaseToken: purchase.token,
  );
  await sdk.consume(purchase.token);
  await pending.clear();
  return true;
}
