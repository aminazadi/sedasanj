import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../application/app_lock_providers.dart';
import '../application/app_lock_service.dart';

/// Settings toggle for the OS-level app lock: entirely the device's own
/// fingerprint/Face ID with an automatic fallback to its PIN/pattern/
/// password — this app never builds its own PIN screen.
class AppLockSettingsCard extends ConsumerWidget {
  const AppLockSettingsCard({super.key});

  Future<void> _toggle(BuildContext context, WidgetRef ref, bool want) async {
    if (!want) {
      await ref.read(appLockEnabledProvider.notifier).set(false);
      ref.read(appLockRuntimeProvider).unlock();
      return;
    }
    // Turning the lock on must prove it actually works on this device first,
    // so the user is never locked out of their own app right after enabling it.
    final result = await ref.read(appLockServiceProvider).authenticate();
    switch (result) {
      case AppLockSuccess():
        await ref.read(appLockEnabledProvider.notifier).set(true);
      case AppLockFailed(message: final message):
        if (context.mounted && message.isNotEmpty) {
          await SsToastHost.show(context, message);
        }
      case AppLockUnsupported(message: final message):
        if (context.mounted) await SsToastHost.show(context, message);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final enabled = ref.watch(appLockEnabledProvider).value ?? false;
    final supportedAsync = ref.watch(appLockDeviceSupportedProvider);
    final supported = supportedAsync.value ?? false;
    const title = 'قفل امنیتی برنامه';
    final canToggle = supportedAsync.hasValue && supported;
    return SsCard(
      title: title,
      trailing: Semantics(
        label: title,
        toggled: enabled,
        child: SsSwitch(
          value: enabled,
          onChanged: canToggle ? (v) => _toggle(context, ref, v) : null,
        ),
      ),
      child: Text(
        canToggle
            ? 'با روشن‌کردن این گزینه، هر بار که برنامه از پس‌زمینه برمی‌گردد '
                  'باید با اثر انگشت، چهره یا رمز/الگوی صفحه‌قفل گوشی باز شود.'
            : 'برای فعال‌سازی قفل، گوشی باید اثر انگشت، Face ID یا رمز/الگوی '
                  'صفحه‌قفل داشته باشد. از تنظیمات گوشی یکی را فعال کنید.',
        style: Theme.of(
          context,
        ).textTheme.bodySmall?.copyWith(color: SsColors.of(context).ink),
      ),
    );
  }
}
