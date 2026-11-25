import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:package_info_plus/package_info_plus.dart';

import '../../../core/db/document_cache.dart';
import '../../../core/platform/api_client.dart';
import '../../../core/platform/connection_store.dart';
import '../../../core/platform/platform_config.dart';
import '../../../core/providers.dart';
import '../../meetings/application/meeting_providers.dart';
import '../../meetings/data/meeting.dart';
import '../../plans/data/billing_models.dart';
import '../../recording/application/live_engine_provider.dart';
import '../../upload/upload_controller.dart';

/// The running app's version name, read from the installed package so it can
/// never drift from pubspec.yaml.
final appVersionProvider = FutureProvider<String>((ref) async {
  final info = await PackageInfo.fromPlatform();
  return info.version;
});

final connectionStoreProvider = FutureProvider<ConnectionStore>((ref) async {
  final db = await ref.watch(appDatabaseProvider.future);
  return ConnectionStore(db);
});

class ConnectionState {
  const ConnectionState({this.connection, this.busy = false, this.error});

  final PlatformConnection? connection;
  final bool busy;
  final String? error;
}

class ConnectionController extends AsyncNotifier<ConnectionState> {
  @override
  Future<ConnectionState> build() async {
    final store = await ref.watch(connectionStoreProvider.future);
    await store.preparePushBinding();
    return ConnectionState(connection: await store.load());
  }

  /// Accepts the raw JSON text of the QR code or config file.
  Future<void> connectFromText(String raw) async {
    final current = state.value ?? const ConnectionState();
    state = AsyncData(
      ConnectionState(connection: current.connection, busy: true),
    );
    try {
      final Object? decoded;
      try {
        decoded = jsonDecode(raw.trim());
      } on FormatException {
        throw const ConfigParseException(
          'متن واردشده JSON معتبر نیست؛ فایل یا QR را از پنل دوباره بگیرید.',
        );
      }
      final payload = parsePairingPayload(decoded);
      final client = ApiClient(serverUrl: payload.serverUrl);
      final paired = await client.pair(
        pairingCode: payload.pairingCode,
        deviceLabel: _deviceLabel(),
        appVersion: await ref.read(appVersionProvider.future),
        platform: _serverPlatform(),
      );
      final info = await ApiClient(
        serverUrl: payload.serverUrl,
        token: paired.token,
      ).validate();
      final connection = PlatformConnection(
        serverUrl: payload.serverUrl,
        userName: info.userName.isEmpty ? paired.userName : info.userName,
        tenantName: info.tenantName.isEmpty
            ? paired.tenantName
            : info.tenantName,
        tokenPrefix: paired.tokenPrefix,
      );
      final store = await ref.read(connectionStoreProvider.future);
      await store.save(connection, paired.token);
      state = AsyncData(ConnectionState(connection: connection));
      // Auto-send: as soon as SedaSanj is connected, everything waiting goes
      // out (when the settings switch is on).
      if (await ref.read(sendTranscriptEnabledProvider.future)) {
        final repo = await ref.read(meetingRepositoryProvider.future);
        await repo.enableSendForUnsent();
        ref.invalidate(meetingsProvider);
      }
      ref.read(uploadQueueProvider.notifier).kick();
    } on ConfigParseException catch (e) {
      state = AsyncData(
        ConnectionState(connection: current.connection, error: e.message),
      );
    } on ApiException catch (e) {
      state = AsyncData(
        ConnectionState(connection: current.connection, error: e.message),
      );
    } on Object catch (e, st) {
      debugPrint('JN-CONNECT: saving the connection failed: $e\n$st');
      // Never leave the screen on the loading mark (e.g. a keychain failure).
      state = AsyncData(
        ConnectionState(
          connection: current.connection,
          error:
              'ذخیرهٔ اتصال روی این دستگاه ناموفق بود؛ برنامه را ببندید و دوباره باز کنید، سپس دوباره امتحان کنید.',
        ),
      );
    }
  }

  /// Stores the device token of a phone-number (personal) sign-in. The upload
  /// queue then sends meetings with it exactly like a paired organization.
  Future<void> savePersonal({
    required String serverUrl,
    required PersonalLoginResult login,
  }) async {
    final connection = PlatformConnection(
      serverUrl: serverUrl,
      userName: login.userName,
      tenantName: 'حساب شخصی',
      tokenPrefix: login.tokenPrefix,
      personal: true,
    );
    final store = await ref.read(connectionStoreProvider.future);
    await store.save(connection, login.token);
    state = AsyncData(ConnectionState(connection: connection));
    if (await ref.read(sendTranscriptEnabledProvider.future)) {
      final repo = await ref.read(meetingRepositoryProvider.future);
      await repo.enableSendForUnsent();
      ref.invalidate(meetingsProvider);
    }
    ref.read(uploadQueueProvider.notifier).kick();
  }

  /// Links the signed-in personal account to a SedaSanj organization with the
  /// organization's pairing code. Returns a Persian error that names the next
  /// step, or null on success.
  Future<String?> linkOrganization(String pairingCode) async {
    final connection = state.value?.connection;
    final store = await ref.read(connectionStoreProvider.future);
    final token = await store.token();
    if (connection == null || !connection.personal || token == null) {
      return 'اتصال به سازمان فقط با حساب شخصی ممکن است؛ ابتدا با شمارهٔ موبایل وارد شوید.';
    }
    try {
      final result =
          await ApiClient(
            serverUrl: connection.serverUrl,
            token: token,
          ).linkOrganization(
            pairingCode: pairingCode.trim(),
            deviceLabel: _deviceLabel(),
            appVersion: await ref.read(appVersionProvider.future),
            platform: _serverPlatform(),
          );
      await store.saveOrg(
        OrgLink(
          linkId: result.linkId,
          organization: result.organization,
          userName: result.userName,
        ),
        result.token,
      );
      ref.invalidate(orgLinkProvider);
      return null;
    } on ApiException catch (e) {
      return e.message;
    } on Object catch (e, st) {
      debugPrint('JN-LINK: saving the organization link failed: $e\n$st');
      return 'ذخیرهٔ اتصال سازمان روی این دستگاه ناموفق بود؛ دوباره امتحان کنید.';
    }
  }

  /// Forgets everything on this device after the server deleted the account.
  Future<void> forgetAfterDeletion() async {
    final store = await ref.read(connectionStoreProvider.future);
    await store.clear();
    ref.invalidate(orgLinkProvider);
    ref.invalidate(meetingsProvider);
    state = const AsyncData(ConnectionState());
  }

  /// Copies the chosen finished meetings into the linked organization.
  /// Returns a Persian message (success or the next step).
  Future<String> importMeetings(List<String> remoteMeetingIds) async {
    final connection = state.value?.connection;
    final store = await ref.read(connectionStoreProvider.future);
    final token = await store.token();
    final link = await store.loadOrg();
    if (connection == null || token == null || link == null) {
      return 'ابتدا به یک سازمان وصل شوید.';
    }
    try {
      final result = await ApiClient(
        serverUrl: connection.serverUrl,
        token: token,
      ).importToOrganization(link.linkId, remoteMeetingIds);
      return '${result.imported} جلسه به سازمان کپی شد'
          '${result.existing > 0 ? ' (${result.existing} جلسه از قبل آنجا بود)' : ''}.';
    } on ApiException catch (e) {
      return e.message;
    } on Object {
      return 'کپی انجام نشد؛ اینترنت را بررسی کنید و دوباره تلاش کنید.';
    }
  }

  /// Revokes the organization key (best effort) and forgets it on this device.
  /// Meetings already sent stay in the organization; unsent ones go back to
  /// the own account.
  Future<void> unlinkOrganization() async {
    final store = await ref.read(connectionStoreProvider.future);
    final link = await store.loadOrg();
    final connection = state.value?.connection;
    final token = await store.token();
    if (link != null && connection != null && token != null) {
      try {
        await ApiClient(
          serverUrl: connection.serverUrl,
          token: token,
        ).unlinkOrganization(link.linkId);
      } on Object catch (e) {
        debugPrint('JN-LINK: server unlink failed: $e');
      }
    }
    final repo = await ref.read(meetingRepositoryProvider.future);
    await repo.moveUnsentToWorkspace(kWorkspacePrimary);
    await store.clearOrg();
    ref.invalidate(orgLinkProvider);
    ref.invalidate(meetingsProvider);
  }

  Future<void> setDefaultWorkspace(String workspace) async {
    final store = await ref.read(connectionStoreProvider.future);
    await store.setDefaultWorkspace(workspace);
    ref.invalidate(orgLinkProvider);
  }

  /// The stand-alone sign-in knows every desktop platform (the pairing API does not).
  String loginPlatform() => Platform.operatingSystem;

  String deviceLabel() => _deviceLabel();

  /// Re-checks the stored token against the server.
  Future<void> recheck() async {
    final current = state.value;
    final connection = current?.connection;
    if (connection == null) return;
    final store = await ref.read(connectionStoreProvider.future);
    final token = await store.token();
    if (token == null) return;
    state = AsyncData(ConnectionState(connection: connection, busy: true));
    try {
      await ApiClient(serverUrl: connection.serverUrl, token: token).validate();
      state = AsyncData(ConnectionState(connection: connection));
    } on ApiException catch (e) {
      state = AsyncData(
        ConnectionState(connection: connection, error: e.message),
      );
    }
  }

  Future<void> disconnect() async {
    final store = await ref.read(connectionStoreProvider.future);
    if (await store.loadOrg() != null) await unlinkOrganization();
    final connection = state.value?.connection;
    if (connection != null && connection.personal) {
      // Best effort: a token that cannot be revoked now (offline) is still
      // forgotten on this device and can be revoked later from the account.
      final token = await store.token();
      if (token != null) {
        try {
          await ApiClient(
            serverUrl: connection.serverUrl,
            token: token,
          ).logout();
        } on Object catch (e) {
          debugPrint('JN-CONNECT: server logout failed: $e');
        }
      }
    }
    await store.clear();
    state = const AsyncData(ConnectionState());
  }

  String _deviceLabel() => 'Jalase-Negar (${Platform.operatingSystem})';
}

/// The linked organization and the workspace new meetings go to.
final orgLinkProvider = FutureProvider<({OrgLink? link, String workspace})>((
  ref,
) async {
  final store = await ref.watch(connectionStoreProvider.future);
  return (
    link: await store.loadOrg(),
    workspace: await store.defaultWorkspace(),
  );
});

final connectionControllerProvider =
    AsyncNotifierProvider<ConnectionController, ConnectionState>(
      ConnectionController.new,
    );

/// The panel API only accepts `android` or `ios` for `platform`
/// (`MeetingPairIn`), so desktop builds report `ios` until the server
/// accepts more values.
String _serverPlatform() => Platform.isAndroid ? 'android' : 'ios';

/// Minutes the server built for a meeting of a personal account.
final meetingMinutesProvider = FutureProvider.autoDispose
    .family<MinutesResult, String>((ref, remoteMeetingId) async {
      final connection = (await ref.watch(
        connectionControllerProvider.future,
      )).connection;
      final store = await ref.watch(connectionStoreProvider.future);
      final token = await store.token();
      if (connection == null || token == null) {
        throw const ApiException(
          message: 'ابتدا با شماره موبایل وارد شوید.',
          requiresReconnect: true,
        );
      }
      return ApiClient(
        serverUrl: connection.serverUrl,
        token: token,
      ).minutes(remoteMeetingId);
    });

/// Plan and remaining minutes of the signed-in personal account.
final personalProfileProvider = FutureProvider.autoDispose<PersonalProfile>((
  ref,
) async {
  final connection = (await ref.watch(
    connectionControllerProvider.future,
  )).connection;
  final token = await (await ref.watch(connectionStoreProvider.future)).token();
  if (connection == null || !connection.personal || token == null) {
    throw const ApiException(message: 'حساب شخصی متصل نیست.');
  }
  // A stalled request must end in an error (shown with a retry), not an endless "…".
  return ApiClient(
    serverUrl: connection.serverUrl,
    token: token,
  ).personalProfile().timeout(
    const Duration(seconds: 20),
    onTimeout: () => throw const ApiException(
      message: 'اطلاعات حساب دریافت نشد. «بررسی اتصال» را بزنید و دوباره تلاش کنید.',
    ),
  );
});

/// An API client signed in as the personal account, for the documents features.
final personalClientProvider = FutureProvider.autoDispose<ApiClient>((
  ref,
) async {
  final connection = (await ref.watch(
    connectionControllerProvider.future,
  )).connection;
  final token = await (await ref.watch(connectionStoreProvider.future)).token();
  if (connection == null || !connection.personal || token == null) {
    throw const ApiException(
      message: 'ابتدا با شماره موبایل وارد شوید.',
      requiresReconnect: true,
    );
  }
  return ApiClient(serverUrl: connection.serverUrl, token: token);
});

final meetingDocumentsProvider = FutureProvider.autoDispose
    .family<List<DocumentInfo>, String>((ref, remoteMeetingId) async {
      final db = DocumentCache(await ref.watch(appDatabaseProvider.future));
      try {
        final client = await ref.watch(personalClientProvider.future);
        final docs = await client.listDocuments(remoteMeetingId);
        for (final d in docs) {
          final old = await db.cachedDocument(d.id);
          await db.cacheDocument(
            documentId: d.id,
            remoteMeetingId: remoteMeetingId,
            outputType: d.outputType,
            status: d.status,
            progressPct: d.progressPct,
            selectedVersion: d.selectedVersion,
            // Keep the text of a version already downloaded.
            markdown: old?['selected_version'] == d.selectedVersion
                ? (old?['markdown'] as String?)
                : null,
          );
        }
        return docs;
      } on Object catch (e) {
        final rows = await db.cachedDocuments(remoteMeetingId);
        if (rows.isEmpty || !_isOffline(e)) rethrow;
        return [for (final r in rows) _cachedInfo(r)];
      }
    });

/// An error that only means "no connection right now" (not a refusal by the
/// server), so a cached copy may be shown instead.
bool _isOffline(Object e) =>
    e is! ApiException ||
    (!e.requiresReconnect && (e.statusCode == null || e.statusCode! >= 500));

final documentDetailProvider = FutureProvider.autoDispose
    .family<DocumentDetail, String>((ref, documentId) async {
      final db = DocumentCache(await ref.watch(appDatabaseProvider.future));
      try {
        final client = await ref.watch(personalClientProvider.future);
        final detail = await client.getDocument(documentId);
        final old = await db.cachedDocument(documentId);
        await db.cacheDocument(
          documentId: documentId,
          remoteMeetingId: old?['remote_meeting_id'] as String?,
          outputType: detail.info.outputType,
          status: detail.info.status,
          progressPct: detail.info.progressPct,
          selectedVersion: detail.info.selectedVersion,
          markdown: detail.markdown,
        );
        return detail;
      } on Object catch (e) {
        final cached = await db.cachedDocument(documentId);
        if (cached == null || !_isOffline(e)) rethrow;
        return _cachedDetail(cached);
      }
    });

DocumentDetail _cachedDetail(Map<String, Object?> row) => DocumentDetail(
  info: _cachedInfo(row),
  markdown: row['markdown'] as String?,
);

DocumentInfo _cachedInfo(Map<String, Object?> row) => DocumentInfo(
  id: row['document_id'] as String,
  outputType: row['output_type'] as String,
  status: row['status'] as String,
  progressPct: (row['progress_pct'] as int?) ?? 0,
  selectedVersion: row['selected_version'] as int?,
);

/// Hours left, plans and token packs of the personal account.
final usageProvider = FutureProvider.autoDispose<UsageInfo>((ref) async {
  return (await ref.watch(personalClientProvider.future)).usage();
});


final progressProvider = FutureProvider.autoDispose<ProgressInfo>((ref) async {
  return (await ref.watch(personalClientProvider.future)).progress();
});

final inviteProvider = FutureProvider.autoDispose<InviteInfo>((ref) async {
  return (await ref.watch(personalClientProvider.future)).invite();
});
