import 'package:flutter_foreground_task/flutter_foreground_task.dart';

/// No-op task handler: audio capture runs in the main isolate through the
/// `record` plugin. The foreground service exists only to keep the process
/// (and the microphone) alive while the screen is off.
@pragma('vm:entry-point')
void recordingServiceCallback() {
  FlutterForegroundTask.setTaskHandler(_KeepAliveHandler());
}

class _KeepAliveHandler extends TaskHandler {
  @override
  Future<void> onStart(DateTime timestamp, TaskStarter starter) async {}

  @override
  void onRepeatEvent(DateTime timestamp) {}

  @override
  Future<void> onDestroy(DateTime timestamp, bool isTimeout) async {}
}

/// Android foreground service (microphone type) held for the duration of a
/// recording; a no-op where the plugin has nothing to do.
class RecordingService {
  RecordingService._();

  static bool _initialized = false;

  static void _init() {
    if (_initialized) return;
    FlutterForegroundTask.init(
      androidNotificationOptions: AndroidNotificationOptions(
        channelId: 'jalase_negar_recording',
        channelName: 'ضبط جلسه',
        channelDescription: 'این اعلان تا پایان ضبط جلسه نمایش داده می‌شود.',
        onlyAlertOnce: true,
      ),
      iosNotificationOptions: const IOSNotificationOptions(
        showNotification: false,
        playSound: false,
      ),
      foregroundTaskOptions: ForegroundTaskOptions(
        eventAction: ForegroundTaskEventAction.nothing(),
        allowWakeLock: true,
      ),
    );
    _initialized = true;
  }

  /// Returns a Persian warning when the notification permission is denied
  /// (recording still works, but Android may stop it in the background).
  static Future<String?> start() async {
    _init();
    String? warning;
    final permission =
        await FlutterForegroundTask.checkNotificationPermission();
    if (permission != NotificationPermission.granted) {
      final result =
          await FlutterForegroundTask.requestNotificationPermission();
      if (result != NotificationPermission.granted) {
        warning =
            'اجازه‌ی اعلان داده نشد؛ برای ضبط پایدار با صفحه‌ی خاموش، اجازه‌ی اعلان را در تنظیمات گوشی فعال کنید.';
      }
    }
    final result = await FlutterForegroundTask.startService(
      serviceId: 4201,
      serviceTypes: [ForegroundServiceTypes.microphone],
      notificationTitle: 'جلسه‌نگار در حال ضبط است',
      notificationText: 'برای بازگشت به برنامه ضربه بزنید',
      callback: recordingServiceCallback,
    );
    if (result is ServiceRequestFailure) {
      warning ??=
          'سرویس ضبط پس‌زمینه شروع نشد؛ صفحه را روشن نگه دارید یا برنامه را دوباره باز کنید.';
    }
    return warning;
  }

  static Future<void> stop() async {
    if (await FlutterForegroundTask.isRunningService) {
      await FlutterForegroundTask.stopService();
    }
  }
}
