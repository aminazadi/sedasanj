import 'dart:convert';

import 'package:dio/dio.dart';

import '../../../core/db/app_database.dart';
import '../../../core/platform/api_client.dart';
import '../../plans/data/billing_models.dart';

/// A catalogue value and whether it was read from this device's cache.
class CatalogValue<T> {
  const CatalogValue({
    required this.value,
    required this.fromCache,
    this.fetchedAt,
  });

  final T value;
  final bool fromCache;
  final DateTime? fetchedAt;
}

/// Public catalogue (categories, plans, token packs) with a device cache.
///
/// Cache first: the last good copy is yielded at once, then a fresh copy replaces it. The
/// server's ETag keeps unchanged responses cheap. Nothing here needs a signed-in account.
class CatalogRepository {
  CatalogRepository({required this.db, required String serverUrl, Dio? dio})
    : _dio =
          dio ??
          Dio(
            BaseOptions(
              baseUrl: serverUrl,
              connectTimeout: const Duration(seconds: 10),
              receiveTimeout: const Duration(seconds: 15),
            ),
          ),
      _serverUrl = serverUrl;

  final AppDatabase db;
  final Dio _dio;
  final String _serverUrl;

  static const _outputTypesPath = '/v1/jalase-negar/catalog/output-types';
  static const _plansPath = '/v1/jalase-negar/catalog/plans';
  static const _packsPath = '/v1/jalase-negar/catalog/token-packages';

  Stream<CatalogValue<List<OutputTypeInfo>>> outputTypes() {
    return _stream(
      'output-types',
      _outputTypesPath,
      (body) => parseOutputTypes(body, _serverUrl),
    );
  }

  Stream<CatalogValue<PlansResult>> plans() {
    return _stream('plans', _plansPath, PlansResult.fromJson);
  }

  Stream<CatalogValue<List<PackInfo>>> tokenPackages() {
    return _stream(
      'token-packages',
      _packsPath,
      (body) => [
        for (final raw in (body['items'] as List? ?? const []))
          PackInfo.fromJson(raw as Map<String, dynamic>),
      ],
    );
  }

  Stream<CatalogValue<T>> _stream<T>(
    String name,
    String path,
    T Function(Map<String, dynamic> body) parse,
  ) async* {
    final key = 'catalog:$name';
    final cached = await _readCache(key);
    if (cached != null) {
      yield CatalogValue(
        value: parse(cached.body),
        fromCache: true,
        fetchedAt: cached.fetchedAt,
      );
    }
    try {
      final response = await _dio.get<Map<String, dynamic>>(
        path,
        options: Options(
          headers: {if (cached?.etag != null) 'If-None-Match': cached!.etag},
          validateStatus: (s) => s != null && (s == 200 || s == 304),
        ),
      );
      if (response.statusCode == 304 && cached != null) {
        return;
      }
      final body = response.data!;
      final etag = response.headers.value('etag');
      await _writeCache(key, etag, body);
      yield CatalogValue(
        value: parse(body),
        fromCache: false,
        fetchedAt: DateTime.now(),
      );
    } on Object {
      // Offline or server down: keep what the cache already showed. With no cache there is
      // nothing to show, so the error reaches the screen with a retry.
      if (cached == null) {
        throw const ApiException(
          message:
              'فهرست دریافت نشد؛ اینترنت را بررسی کنید و دوباره تلاش کنید.',
          code: 'catalog_unavailable',
        );
      }
    }
  }

  Future<_CachedBody?> _readCache(String key) async {
    final raw = await db.getSetting(key);
    if (raw == null) return null;
    try {
      final decoded = jsonDecode(raw) as Map<String, dynamic>;
      return _CachedBody(
        body: decoded['body'] as Map<String, dynamic>,
        etag: decoded['etag'] as String?,
        fetchedAt: DateTime.fromMillisecondsSinceEpoch(decoded['at'] as int),
      );
    } on Object {
      return null;
    }
  }

  Future<void> _writeCache(
    String key,
    String? etag,
    Map<String, dynamic> body,
  ) {
    return db.setSetting(
      key,
      jsonEncode({
        'etag': etag,
        'at': DateTime.now().millisecondsSinceEpoch,
        'body': body,
      }),
    );
  }
}

class _CachedBody {
  const _CachedBody({
    required this.body,
    required this.etag,
    required this.fetchedAt,
  });

  final Map<String, dynamic> body;
  final String? etag;
  final DateTime fetchedAt;
}
