import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:uuid/uuid.dart';

import '../../core/platform/connection_store.dart';
import '../../core/platform/distribution.dart';

const _apiKey = String.fromEnvironment('PUSH_FIREBASE_API_KEY');
const _appId = String.fromEnvironment('PUSH_FIREBASE_APP_ID');
const _sender = String.fromEnvironment('PUSH_FIREBASE_SENDER_ID');
const _project = String.fromEnvironment('PUSH_FIREBASE_PROJECT');
const _origin = String.fromEnvironment('PUSH_ORIGIN');
const _storage = FlutterSecureStorage();
const _identityKey = 'jalase_push_identity';
const _enabledKey = 'jalase_push_enabled';
const _latestDataKey = 'jalase_push_latest_data';
const _path = '/v1/jalase-negar/push/installations';
const _uuid = Uuid();
const _channels = {'direct', 'bazaar', 'myket'};

const pushRoutes = {
  'home': '/',
  'settings': '/settings',
  'guide': '/guide',
  'people': '/people',
  'models': '/models',
};

const _sound = AndroidNotificationChannel(
  'jalase_push_sound',
  'پوش جلسه‌نگار',
  importance: Importance.high,
);
const _quiet = AndroidNotificationChannel(
  'jalase_push_quiet',
  'پوش بی‌صدای جلسه‌نگار',
  playSound: false,
  enableVibration: false,
);

bool get pushConfigured =>
    !kIsWeb &&
    Platform.isAndroid &&
    _channels.contains(appFlavor ?? kStoreChannel) &&
    _apiKey.isNotEmpty &&
    _appId.isNotEmpty &&
    _sender.isNotEmpty &&
    _project.isNotEmpty &&
    Uri.tryParse(_origin)?.scheme == 'https' &&
    Uri.tryParse(_origin)?.host.isNotEmpty == true &&
    (kReleaseMode || Uri.tryParse(_origin)?.host != 'api.sedasanj.ir');

Future<bool?> requestPushPermission() =>
    FlutterLocalNotificationsPlugin()
        .resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin
        >()
        ?.requestNotificationsPermission() ??
    Future.value();

Future<void> _firebase() async {
  if (Firebase.apps.isEmpty) {
    await Firebase.initializeApp(
      options: const FirebaseOptions(
        apiKey: _apiKey,
        appId: _appId,
        messagingSenderId: _sender,
        projectId: _project,
      ),
    );
  }
}

class _Identity {
  const _Identity(this.id, this.secret);
  final String id;
  final String secret;

  static Future<_Identity?> load({bool create = false}) async {
    final raw = await _storage.read(key: _identityKey);
    if (raw != null) {
      final parts = raw.split(':');
      if (parts.length == 2) return _Identity(parts.first, parts.last);
    }
    if (!create) return null;
    final random = Random.secure();
    final secret = base64UrlEncode(
      List.generate(32, (_) => random.nextInt(256)),
    );
    final identity = _Identity(_uuid.v4(), secret);
    await _storage.write(
      key: _identityKey,
      value: '${identity.id}:${identity.secret}',
    );
    return identity;
  }

  Future<Options> options() async {
    final mobile = await ConnectionStore.pushToken(_origin);
    return Options(
      followRedirects: false,
      headers: {
        'X-Installation-Secret': secret,
        if (mobile != null) 'X-Api-Key': mobile,
      },
    );
  }
}

Dio _http() => Dio(
  BaseOptions(
    connectTimeout: const Duration(seconds: 4),
    receiveTimeout: const Duration(seconds: 4),
    sendTimeout: const Duration(seconds: 4),
    followRedirects: false,
  ),
);

Future<bool> pushEnabled() async =>
    await _storage.read(key: _enabledKey) != '0';

Future<void> setPushEnabled(bool enabled) async {
  await _storage.write(key: _enabledKey, value: enabled ? '1' : '0');
  if (!enabled) {
    await _storage.delete(key: _latestDataKey);
    await FlutterLocalNotificationsPlugin().cancelAll();
  }
}

Future<void> synchronizePush() async {
  final messaging = FirebaseMessaging.instance;
  final token = await messaging.getToken();
  if (token == null) return;
  final identity = (await _Identity.load(create: true))!;
  final version = await PackageInfo.fromPlatform();
  final client = _http();

  Future<void> register(String token) async {
    await client.put<void>(
      '$_origin$_path/${identity.id}',
      data: {
        'token': token,
        'version': version.version,
        'channel': appFlavor ?? kStoreChannel,
        'enabled': await pushEnabled(),
      },
      options: await identity.options(),
    );
  }

  try {
    try {
      await register(token);
    } on DioException catch (error) {
      if (error.response?.statusCode != 409) rethrow;
      await messaging.deleteToken();
      final renewed = await messaging.getToken();
      if (renewed == null || renewed == token) rethrow;
      await register(renewed);
    }
  } finally {
    client.close(force: true);
  }
}

Future<FlutterLocalNotificationsPlugin> _notifications({
  void Function(NotificationResponse)? onTap,
}) async {
  final plugin = FlutterLocalNotificationsPlugin();
  await plugin.initialize(
    const InitializationSettings(
      android: AndroidInitializationSettings('@mipmap/ic_launcher'),
    ),
    onDidReceiveNotificationResponse: onTap,
  );
  final android = plugin
      .resolvePlatformSpecificImplementation<
        AndroidFlutterLocalNotificationsPlugin
      >();
  await android?.createNotificationChannel(_sound);
  await android?.createNotificationChannel(_quiet);
  return plugin;
}

Future<String?> initializePush(void Function(String?) onTap) async {
  await _firebase();
  FirebaseMessaging.onBackgroundMessage(receiveBackgroundPush);
  final plugin = await _notifications(
    onTap: (response) => onTap(response.payload),
  );
  final launch = await plugin.getNotificationAppLaunchDetails();
  return launch?.didNotificationLaunchApp == true
      ? launch?.notificationResponse?.payload
      : null;
}

@pragma('vm:entry-point')
Future<void> receiveBackgroundPush(RemoteMessage message) async {
  if (!pushConfigured) return;
  try {
    await _firebase();
    await receivePush(message);
  } catch (_) {
    // Do not expose tokens, payloads, or transport diagnostics to device logs.
  }
}

Future<Uint8List?> _image(Object? value) async {
  final uri = value is String ? Uri.tryParse(value) : null;
  if (uri == null ||
      uri.scheme != 'https' ||
      uri.host.isEmpty ||
      uri.userInfo.isNotEmpty) {
    return null;
  }
  final client = _http();
  const limit = 1024 * 1024;
  try {
    final response = await client.get<ResponseBody>(
      uri.toString(),
      options: Options(
        responseType: ResponseType.stream,
        followRedirects: false,
      ),
    );
    final contentType = response.headers.value('content-type') ?? '';
    if (!RegExp(r'^image/(png|jpeg|webp)(;|$)').hasMatch(contentType)) {
      return null;
    }
    final bytes = BytesBuilder(copy: false);
    await for (final chunk in response.data!.stream.timeout(
      const Duration(seconds: 4),
    )) {
      if (bytes.length + chunk.length > limit) return null;
      bytes.add(chunk);
    }
    return bytes.takeBytes();
  } catch (_) {
    return null;
  } finally {
    client.close(force: true);
  }
}

int notificationId(String campaign, bool replace) {
  if (replace) return 1;
  var value = 0;
  for (final byte in campaign.codeUnits) {
    value = (value * 31 + byte) & 0x3fffffff;
  }
  return value + 2;
}

Future<void> receivePush(RemoteMessage incoming) async {
  final campaign = incoming.data['campaign_id'];
  if (campaign is! String ||
      !Uuid.isValidUUID(fromString: campaign) ||
      !await pushEnabled()) {
    return;
  }
  final embedded = incoming.data['payload'];
  final Map<String, dynamic>? payload;
  String? pairedToken;
  if (embedded is String) {
    payload = jsonDecode(embedded) as Map<String, dynamic>?;
  } else {
    final identity = await _Identity.load();
    if (identity == null) return;
    final client = _http();
    try {
      final options = await identity.options();
      pairedToken = options.headers?['X-Api-Key'] as String?;
      final response = await client.get<Map<String, dynamic>>(
        '$_origin$_path/${identity.id}/messages/$campaign',
        options: options,
      );
      payload = response.data;
    } on DioException {
      return;
    } finally {
      client.close(force: true);
    }
  }
  Future<bool> stillEligible() async =>
      await pushEnabled() &&
      (pairedToken == null ||
          pairedToken == await ConnectionStore.pushToken(_origin));

  if (payload == null || !await stillEligible()) return;
  final kind = payload['kind'];
  if ((kind == 'data' || kind == 'combined') && payload['data'] is Map) {
    await _storage.write(
      key: _latestDataKey,
      value: jsonEncode({'campaign_id': campaign, 'data': payload['data']}),
    );
  }
  if (kind != 'notification' && kind != 'combined') return;
  final title = payload['title'];
  final body = payload['body'];
  if (title is! String || body is! String) return;
  final bytes = await _image(payload['image']);
  final plugin = FlutterLocalNotificationsPlugin();
  final channel = payload['sound'] == true ? _sound : _quiet;
  final destination = payload['destination'];
  if (!await stillEligible()) return;
  await plugin.show(
    notificationId(campaign, payload['replace'] == true),
    title,
    body,
    NotificationDetails(
      android: AndroidNotificationDetails(
        channel.id,
        channel.name,
        importance: channel.importance,
        playSound: channel.playSound,
        enableVibration: channel.enableVibration,
        onlyAlertOnce: payload['replace'] != true,
        styleInformation: bytes == null || bytes.isEmpty
            ? BigTextStyleInformation(body)
            : BigPictureStyleInformation(
                ByteArrayAndroidBitmap(bytes),
                summaryText: body,
              ),
      ),
    ),
    payload: destination is String && pushRoutes.containsKey(destination)
        ? destination
        : 'home',
  );
}
