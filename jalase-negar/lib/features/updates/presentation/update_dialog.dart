import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_toast.dart';
import '../application/update_controller.dart';

/// Shows the update offer. "بعداً" and the system back gesture both set the
/// offer aside until the next cold start; "دریافت نسخه" opens the browser and
/// keeps the dialog so the user can retry after coming back.
Future<void> showUpdateDialog(BuildContext context) async {
  // The prompt host and the settings button can both ask: only one dialog may
  // be up per navigator.
  final navigator = Navigator.of(context);
  if (_open[navigator] == true) return;
  _open[navigator] = true;
  try {
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (_) => const UpdateDialog(),
    );
  } finally {
    _open[navigator] = false;
  }
}

final _open = Expando<bool>('update dialog open');

class UpdateDialog extends ConsumerWidget {
  const UpdateDialog({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(updateControllerProvider);
    final offer = state.offer;
    final installed = state.installed;
    if (offer == null || installed == null) {
      // The offer vanished (for example a newer manual check found nothing).
      return const SizedBox.shrink();
    }
    final controller = ref.read(updateControllerProvider.notifier);

    void later() {
      controller.postpone();
      Navigator.of(context).pop();
    }

    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) later();
      },
      child: Directionality(
        textDirection: TextDirection.rtl,
        child: AlertDialog(
          shape: const RoundedRectangleBorder(
            borderRadius: BorderRadius.zero,
            side: BorderSide(color: SsColors.lineStrong),
          ),
          title: const Text('نسخه‌ی جدید جلسه‌نگار'),
          content: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420, maxHeight: 360),
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _VersionRow(
                    label: 'نسخه‌ی نصب‌شده',
                    value: '${installed.versionName} (${installed.versionCode})',
                  ),
                  _VersionRow(
                    label: 'نسخه‌ی پیشنهادی',
                    value: '${offer.version} (${offer.versionCode})',
                    strong: true,
                  ),
                  if (offer.notes.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    const Text(
                      'تغییرات',
                      style: TextStyle(
                        fontFamily: 'Vazirmatn',
                        fontWeight: FontWeight.w600,
                        color: SsColors.primaryDark,
                      ),
                    ),
                    const SizedBox(height: 4),
                    // Plain text on purpose: release notes are never markup.
                    Text(offer.notes),
                  ],
                  const SizedBox(height: 12),
                  const Text(
                    'جلسه‌ها، فایل‌های صدا و مدل‌های دانلودشده با به‌روزرسانی پاک نمی‌شوند.',
                    style: TextStyle(fontSize: 12.5, color: SsColors.neutral),
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(onPressed: later, child: const Text('بعداً')),
            FilledButton(
              onPressed: () async {
                final problem = await controller.download();
                if (problem != null && context.mounted) {
                  SsToastHost.show(context, problem);
                }
              },
              child: const Text('دریافت نسخه'),
            ),
          ],
        ),
      ),
    );
  }
}

class _VersionRow extends StatelessWidget {
  const _VersionRow({
    required this.label,
    required this.value,
    this.strong = false,
  });

  final String label;
  final String value;
  final bool strong;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 3),
    child: Row(
      children: [
        Text(label),
        const Spacer(),
        // Versions are Latin digits and read left to right inside Persian text.
        Directionality(
          textDirection: TextDirection.ltr,
          child: Text(
            value,
            style: TextStyle(
              fontFamily: 'Vazirmatn',
              fontWeight: strong ? FontWeight.w600 : FontWeight.w400,
              color: strong ? SsColors.primary : SsColors.ink,
            ),
          ),
        ),
      ],
    ),
  );
}

