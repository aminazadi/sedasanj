import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';

import '../theme.dart';
import 'brand_logo.dart';

/// Side menu reachable from the hamburger button next to the logo, and from
/// the edge-swipe gesture Scaffold already attaches to any `drawer`.
class AppMenuDrawer extends StatelessWidget {
  const AppMenuDrawer({super.key});

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
