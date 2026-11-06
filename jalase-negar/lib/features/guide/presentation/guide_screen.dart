import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/widgets/ss_widgets.dart';
import '../../onboarding/tour_step.dart';

/// Help hub: the interactive tour, the intro slides and shortcuts to the
/// things a new user is most often looking for.
class GuideScreen extends StatelessWidget {
  const GuideScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: EdgeInsets.fromLTRB(
        16,
        16,
        16,
        24 + MediaQuery.paddingOf(context).bottom,
      ),
      children: [
        _GuideTile(
          icon: Icons.help_outline,
          title: 'راهنمای تعاملی',
          subtitle: 'قدم‌به‌قدم: ضبط، متن زنده، مدل‌ها و اتصال به صداسنج',
          onTap: () =>
              context.go(TourStep.welcome.location(fromSettings: true)),
        ),
        const SizedBox(height: 8),
        _GuideTile(
          icon: Icons.slideshow_outlined,
          title: 'معرفی جلسه‌نگار',
          subtitle: 'اسلایدهای معرفی اپ را دوباره ببینید',
          onTap: () => context.go('/intro?replay=1'),
        ),
        const SizedBox(height: 8),
        _GuideTile(
          icon: Icons.download_outlined,
          title: 'دانلود مدل‌ها',
          subtitle: 'برای رونویسی فارسی و تشخیص گوینده روی گوشی',
          onTap: () => context.push('/models'),
        ),
        const SizedBox(height: 8),
        _GuideTile(
          icon: Icons.record_voice_over_outlined,
          title: 'تشخیص گویندگان',
          subtitle:
              'در صفحهٔ هر جلسه گوینده‌ها را استخراج کنید؛ درصد پیشرفت در تب گوینده‌ها و کارت جلسه نمایش داده می‌شود',
          onTap: () => context.go('/people'),
        ),
      ],
    );
  }
}

class _GuideTile extends StatelessWidget {
  const _GuideTile({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return SsCard(
      child: ListTile(
        contentPadding: EdgeInsets.zero,
        leading: Icon(icon),
        title: Text(title),
        subtitle: Text(subtitle),
        // chevron_right mirrors to point left in RTL.
        trailing: const Icon(Icons.chevron_right),
        onTap: onTap,
      ),
    );
  }
}
