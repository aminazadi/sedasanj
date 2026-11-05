import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../data/update_native.dart';

/// One-time explanation shown before sending the user to the Android screen
/// that allows this app to install updates. Declining changes nothing: the
/// app keeps offering updates by hand, as before.
Future<void> showUpdatePermissionDialog(
  BuildContext context,
  UpdateNative native,
) async {
  if (await native.canInstallPackages()) {
    await native.markExplainerShown();
    return;
  }
  if (!context.mounted) return;
  final allow = await showDialog<bool>(
    context: context,
    barrierDismissible: false,
    builder: (_) => const _PermissionDialog(),
  );
  // Asked exactly once, whatever the answer.
  await native.markExplainerShown();
  if (allow == true) await native.openInstallSettings();
}

class _PermissionDialog extends StatelessWidget {
  const _PermissionDialog();

  @override
  Widget build(BuildContext context) {
    return Directionality(
      textDirection: TextDirection.rtl,
      child: AlertDialog(
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.zero,
          side: BorderSide(color: SsColors.lineStrong),
        ),
        title: const Text('به‌روزرسانی بی‌صدا'),
        content: const SingleChildScrollView(
          child: Text(
            'برای اینکه جلسه‌نگار نسخه‌های جدید را خودش و در لحظه‌ی آرام نصب کند، '
            'اندروید باید یک‌بار اجازه بدهد. در صفحه‌ی بعد گزینه‌ی «اجازه‌ی نصب از این منبع» '
            'را روشن کنید.\n\n'
            'نصب فقط وقتی انجام می‌شود که ضبط فعال نیست، ارسال‌ها تمام شده‌اند و اپ بسته است؛ '
            'جلسه‌ها و فایل‌های شما پاک نمی‌شوند. اگر اجازه ندهید، همه‌چیز مثل قبل می‌ماند '
            'و نسخه‌ی جدید را دستی دریافت می‌کنید.',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('الان نه'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('باز کردن تنظیمات'),
          ),
        ],
      ),
    );
  }
}
