import 'dart:io';

import 'package:flutter/services.dart';
import 'package:package_info_plus/package_info_plus.dart';

import 'app_update.dart';

const _channel = MethodChannel('app.jalasenegar.jalase_negar/update');

/// Reads what the server needs to pick a compatible build. Returns null when
/// the device cannot say (not Android, channel missing): no check is made then.
Future<UpdateEnvironment?> readUpdateEnvironment() async {
  if (!Platform.isAndroid) return null;
  try {
    final info = await PackageInfo.fromPlatform();
    final code = int.tryParse(info.buildNumber);
    final native = await _channel.invokeMapMethod<String, Object?>(
      'environment',
    );
    final sdk = native?['sdkInt'];
    final abis = native?['abis'];
    final cert = native?['certSha256'];
    if (code == null ||
        sdk is! int ||
        abis is! List ||
        cert is! String ||
        cert.isEmpty) {
      return null;
    }
    return UpdateEnvironment(
      versionName: info.version,
      versionCode: code,
      sdkInt: sdk,
      abis: abis.whereType<String>().toList(),
      certSha256: cert.toLowerCase(),
    );
  } on PlatformException {
    return null;
  } on MissingPluginException {
    return null;
  }
}
