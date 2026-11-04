import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../application/update_controller.dart';
import 'update_dialog.dart';

/// Settings entry for checking by hand, and for trying again after a failure.
class UpdateCheckCard extends ConsumerWidget {
  const UpdateCheckCard({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(updateControllerProvider);
    final installed = state.installed;
    return SsCard(
      title: 'به‌روزرسانی',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            installed == null
                ? 'نسخه‌ی تازه‌ی جلسه‌نگار را از سرور صداسنج بررسی کنید.'
                : 'نسخه‌ی نصب‌شده: ${installed.versionName} (${installed.versionCode})',
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: state.checking
                ? null
                : () async {
                    final result = await ref
                        .read(updateControllerProvider.notifier)
                        .checkManually();
                    if (!context.mounted) return;
                    if (result.offer != null) {
                      await showUpdateDialog(context);
                    } else if (result.message != null) {
                      SsToastHost.show(context, result.message!);
                    }
                  },
            icon: state.checking
                ? const SizedBox.square(
                    dimension: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.system_update_alt),
            label: const Text('بررسی به‌روزرسانی'),
          ),
        ],
      ),
    );
  }
}
