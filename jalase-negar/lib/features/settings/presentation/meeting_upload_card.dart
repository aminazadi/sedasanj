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
          child: InkWell(
            onTap: () => onChanged(!enabled),
            child: SizedBox(
              width: 48,
              height: 36,
              child: Center(
                child: Ink(
                  width: 40,
                  height: 22,
                  padding: const EdgeInsets.all(3),
                  decoration: BoxDecoration(
                    color: enabled ? SsColors.primary : SsColors.canvas,
                    border: Border.all(
                      color: enabled ? SsColors.primary : SsColors.neutral,
                    ),
                  ),
                  child: Align(
                    alignment: enabled
                        ? AlignmentDirectional.centerEnd
                        : AlignmentDirectional.centerStart,
                    child: ColoredBox(
                      color: enabled ? SsColors.canvas : SsColors.neutral,
                      child: const SizedBox.square(dimension: 14),
                    ),
                  ),
                ),
              ),
            ),
          ),
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
