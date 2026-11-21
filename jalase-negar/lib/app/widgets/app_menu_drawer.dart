import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import '../theme.dart';
import 'brand_logo.dart';

/// Side menu reachable from the hamburger button next to the logo, and from
/// the edge-swipe gesture Scaffold already attaches to any `drawer`.
class AppMenuDrawer extends StatelessWidget {
  const AppMenuDrawer({super.key});

  Future<void> _openWebPage(BuildContext context, Uri uri) async {
    Navigator.of(context).pop();
    try {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    } catch (_) {
      if (!context.mounted) return;
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        SnackBar(
          content: Text(
            'باز کردن لینک ممکن نشد؛ نشانی ${uri.host} را در مرورگر باز کنید.',
          ),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Drawer(
      backgroundColor: SsColors.of(context).canvas,
      shape: const RoundedRectangleBorder(),
      child: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 24, 20, 16),
              child: SsBrandLogo(
                width: 104,
                animated: false,
                color: ssBrandLogoColor(context),
              ),
            ),
            Divider(height: 1, color: SsColors.of(context).line),
            ListTile(
              leading: const Icon(Icons.info_outline),
              title: const Text('درباره ما'),
              onTap: () => _openWebPage(context, Uri.parse('https://sedasanj.ir/about')),
            ),
            ListTile(
              leading: const Icon(Icons.support_agent_outlined),
              title: const Text('تماس با پشتیبانی'),
              onTap: () => _openWebPage(context, Uri.parse('https://sedasanj.ir/contact')),
            ),
            ListTile(
              leading: const Icon(Icons.share_outlined),
              title: const Text('اشتراک‌گذاری اپ'),
              onTap: () {
                Navigator.of(context).pop();
                SharePlus.instance.share(
                  ShareParams(
                    text:
                        'جلسه‌نگار؛ برنامه‌ای برای ضبط و پیاده‌سازی متن '
                        'جلسات.',
                  ),
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}
