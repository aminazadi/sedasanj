import 'dart:async';

import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/router.dart';
import '../../app/widgets/ss_widgets.dart';
import '../settings/application/connection_controller.dart';
import 'jalase_push.dart';

final _pushPreference = FutureProvider<bool>((ref) => pushEnabled());

class PushHost extends ConsumerStatefulWidget {
  const PushHost({required this.child, super.key});
  final Widget child;

  @override
  ConsumerState<PushHost> createState() => _PushHostState();
}

class _PushHostState extends ConsumerState<PushHost>
    with WidgetsBindingObserver {
  StreamSubscription<String>? _tokens;
  StreamSubscription<RemoteMessage>? _messages;
  Timer? _retry;
  bool _ready = false;
  bool _syncing = false;
  bool _pending = false;

  @override
  void initState() {
    super.initState();
    if (!pushConfigured) return;
    WidgetsBinding.instance.addObserver(this);
    unawaited(_start());
  }

  Future<void> _start() async {
    try {
      final initial = await initializePush(_open);
      if (!mounted) return;
      _ready = true;
      _tokens = FirebaseMessaging.instance.onTokenRefresh.listen(
        (_) => unawaited(_sync()),
        onError: (Object _) {},
      );
      _messages = FirebaseMessaging.onMessage.listen((message) async {
        try {
          await receivePush(message);
        } catch (_) {
          // Keep notification failures isolated from recording and navigation.
        }
      });
      _open(initial);
      await ref.read(connectionControllerProvider.future);
      if (mounted) await _sync();
    } catch (_) {
      // Firebase is optional on devices without Google Play Services.
    }
  }

  void _open(String? destination) {
    final route = pushRoutes[destination];
    if (route == null || !mounted) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) ref.read(routerProvider).go(route);
    });
    WidgetsBinding.instance.ensureVisualUpdate();
  }

  Future<void> _sync() async {
    if (!_ready || !mounted) return;
    if (_syncing) {
      _pending = true;
      return;
    }
    _syncing = true;
    _retry?.cancel();
    try {
      do {
        _pending = false;
        await synchronizePush();
      } while (_pending && mounted);
    } catch (_) {
      if (mounted) {
        _retry = Timer(const Duration(minutes: 1), () => unawaited(_sync()));
      }
    } finally {
      _syncing = false;
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) unawaited(_sync());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _retry?.cancel();
    unawaited(_tokens?.cancel());
    unawaited(_messages?.cancel());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (pushConfigured) {
      ref.listen(connectionControllerProvider, (previous, next) {
        if (previous?.value?.connection?.tokenPrefix !=
            next.value?.connection?.tokenPrefix) {
          unawaited(_sync());
        }
      });
      ref.listen(_pushPreference, (previous, next) {
        if (next.hasValue && previous?.value != next.value) unawaited(_sync());
      });
    }
    return widget.child;
  }
}

class PushSettingsCard extends ConsumerWidget {
  const PushSettingsCard({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (!pushConfigured) return const SizedBox.shrink();
    final enabled = ref.watch(_pushPreference);
    return SsCard(
      title: 'پوش جلسه‌نگار',
      child: Column(
        children: [
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('دریافت پوش'),
            subtitle: const Text(
              'برای نمایش اعلان‌ها، مجوز اعلان جلسه‌نگار را در Android فعال کنید.',
            ),
            value: enabled.value ?? false,
            onChanged: !enabled.hasValue
                ? null
                : (value) async {
                    try {
                      await setPushEnabled(value);
                      if (value) await requestPushPermission();
                    } finally {
                      ref.invalidate(_pushPreference);
                    }
                  },
          ),
          if (enabled.value == true)
            TextButton(
              onPressed: requestPushPermission,
              child: const Text('درخواست مجوز نمایش اعلان'),
            ),
        ],
      ),
    );
  }
}
