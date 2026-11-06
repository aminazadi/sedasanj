import 'dart:io';

import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:record/record.dart';

/// The permissions the app asks for once, right after the intro slides.
enum AppPermission { microphone, notifications, background }

/// Reads and requests the permissions. A fake replaces it in tests.
abstract class PermissionGateway {
  /// Permissions that exist on this platform, in the order they are asked.
  List<AppPermission> get supported;

  Future<bool> isGranted(AppPermission permission);

  /// Shows the system prompt (or settings page) and returns the new state.
  Future<bool> request(AppPermission permission);
}

/// Microphone on phones; notification and "keep running in the background"
/// (battery-optimisation exemption) on Android, where the recording
/// foreground service needs them to survive a closed app or a dark screen.
class SystemPermissionGateway implements PermissionGateway {
  const SystemPermissionGateway();

  @override
  List<AppPermission> get supported {
    if (Platform.isAndroid) return AppPermission.values;
    if (Platform.isIOS) return const [AppPermission.microphone];
    return const [];
  }

  @override
  Future<bool> isGranted(AppPermission permission) async {
    switch (permission) {
      case AppPermission.microphone:
        final recorder = AudioRecorder();
        try {
          return await recorder.hasPermission(request: false);
        } finally {
          await recorder.dispose();
        }
      case AppPermission.notifications:
        return await FlutterForegroundTask.checkNotificationPermission() ==
            NotificationPermission.granted;
      case AppPermission.background:
        return FlutterForegroundTask.isIgnoringBatteryOptimizations;
    }
  }

  @override
  Future<bool> request(AppPermission permission) async {
    switch (permission) {
      case AppPermission.microphone:
        final recorder = AudioRecorder();
        try {
          return await recorder.hasPermission();
        } finally {
          await recorder.dispose();
        }
      case AppPermission.notifications:
        return await FlutterForegroundTask.requestNotificationPermission() ==
            NotificationPermission.granted;
      case AppPermission.background:
        await FlutterForegroundTask.requestIgnoreBatteryOptimization();
        return FlutterForegroundTask.isIgnoringBatteryOptimizations;
    }
  }
}
