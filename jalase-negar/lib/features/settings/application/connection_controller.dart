import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:package_info_plus/package_info_plus.dart';

import '../../../core/platform/api_client.dart';
import '../../../core/platform/connection_store.dart';
import '../../../core/platform/platform_config.dart';
import '../../../core/providers.dart';
import '../../meetings/application/meeting_providers.dart';
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
    await store.clear();
    state = const AsyncData(ConnectionState());
  }

  String _deviceLabel() => 'Jalase-Negar (${Platform.operatingSystem})';
}

final connectionControllerProvider =
    AsyncNotifierProvider<ConnectionController, ConnectionState>(
      ConnectionController.new,
    );

/// The panel API only accepts `android` or `ios` for `platform`
/// (`MeetingPairIn`), so desktop builds report `ios` until the server
/// accepts more values.
String _serverPlatform() => Platform.isAndroid ? 'android' : 'ios';
