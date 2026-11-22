import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/brand_logo.dart';
import '../../../app/widgets/ss_toast.dart';
import '../application/app_lock_providers.dart';
import '../application/app_lock_service.dart';

/// Full-screen gate shown while [AppLockRuntime.locked] is true. No back
/// button, no way to dismiss it except a successful device authentication —
/// the OS owns the actual prompt (fingerprint/Face ID, falling back to the
/// phone's own PIN/pattern/password); this screen never asks for a PIN itself.
class AppLockScreen extends ConsumerStatefulWidget {
  const AppLockScreen({super.key});

  @override
  ConsumerState<AppLockScreen> createState() => _AppLockScreenState();
}

class _AppLockScreenState extends ConsumerState<AppLockScreen>
    with WidgetsBindingObserver {
  bool _busy = false;
  String? _message;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) => _authenticate());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // The lock screen can sit in front across several background/foreground
    // cycles without rebuilding; re-offer the OS prompt on every return.
    if (state == AppLifecycleState.resumed && mounted) _authenticate();
  }

  Future<void> _authenticate() async {
    if (_busy || !mounted) return;
    setState(() {
      _busy = true;
      _message = null;
    });
    final result = await ref.read(appLockServiceProvider).authenticate();
    if (!mounted) return;
    switch (result) {
      case AppLockSuccess():
        ref.read(appLockRuntimeProvider).unlock();
        return;
      case AppLockFailed(message: final message):
        setState(() {
          _busy = false;
          _message = message.isEmpty ? null : message;
        });
      case AppLockUnsupported(message: final message):
        // The device lost its own lock method (e.g. the user removed their
        // PIN) — never trap the user outside their own app over that.
        await ref.read(appLockEnabledProvider.notifier).set(false);
        ref.read(appLockRuntimeProvider).unlock();
        if (mounted) {
          await SsToastHost.show(context, message);
        }
    }
  }

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    return PopScope(
      canPop: false,
      child: Scaffold(
        backgroundColor: SsColors.of(context).canvas,
        body: SafeArea(
          child: Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                SsBrandLogo(
                  width: (width * 0.5).clamp(0, 220),
                  color: ssBrandLogoColor(context),
                  animated: false,
                ),
                const SizedBox(height: 24),
                Icon(
                  Icons.lock_outline,
                  size: 40,
                  color: SsColors.of(context).primary,
                ),
                const SizedBox(height: 12),
                const Text('برنامه قفل است'),
                if (_message != null) ...[
                  const SizedBox(height: 8),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 32),
                    child: Text(
                      _message!,
                      textAlign: TextAlign.center,
                      style: TextStyle(color: SsColors.of(context).danger),
                    ),
                  ),
                ],
                const SizedBox(height: 24),
                FilledButton(
                  onPressed: _busy ? null : _authenticate,
                  child: const Text('باز کردن قفل'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
