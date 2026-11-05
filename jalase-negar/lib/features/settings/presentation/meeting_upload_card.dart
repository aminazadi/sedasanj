import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../onboarding/tour_overlay.dart';
import '../../onboarding/tour_step.dart';

class MeetingUploadCard extends StatelessWidget {
  const MeetingUploadCard({
    super.key,
    required this.enabled,
    required this.onChanged,
  });

  final bool enabled;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    const title = 'ارسال جلسه';
    return SsCard(
      title: title,
      trailing: TourTarget(
        step: TourStep.upload,
        child: Semantics(
          label: title,
          toggled: enabled,
          child: SsSwitch(value: enabled, onChanged: onChanged),
        ),
      ),
      child: Text(
        'با روشن بودن سوییچ، پس از ضبط، صدا برای پخش و متن برای ساخت '
        'صورت‌جلسه به صداسنج ارسال می‌شوند. این تنظیم برای جلسه‌های بعدی است.',
        style: Theme.of(
          context,
        ).textTheme.bodySmall?.copyWith(color: SsColors.ink),
      ),
    );
  }
}
