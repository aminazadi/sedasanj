import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/widgets/ss_widgets.dart';
import '../../../core/platform/cpu_budget.dart';
import '../../../core/utils/format.dart';

/// Lets the owner choose how many processor cores the app may use for all its
/// work, from 1 up to half of the phone's cores.
class CpuLimitCard extends ConsumerWidget {
  const CpuLimitCard({super.key, this.processors});

  /// Overrides the phone's core count (tests).
  final int? processors;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final max = maxCpuCores(processors);
    final budget = ref.watch(cpuBudgetProvider).value;
    final cores = clampCpuCores(budget?.cores, processors);
    final notifier = ref.read(cpuBudgetProvider.notifier);
    return SsCard(
      title: 'سهم پردازنده',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'تعیین کنید جلسه‌نگار برای کارهای سنگینش (متن زنده، تشخیص گوینده، '
            'تشخیص صداهایی مثل خنده و تحلیل دقیق) از چند هستهٔ گوشی استفاده کند. عدد بیشتر سریع‌تر '
            'است ولی گوشی را گرم‌تر و باتری را زودتر خالی می‌کند. حداکثر '
            'همهٔ هسته‌ها به‌جز یکی (${toPersianDigits('$max')} از '
            '${toPersianDigits('${processors ?? Platform.numberOfProcessors}')}) مجاز است.',
            style: theme.textTheme.bodyMedium,
          ),
          const SizedBox(height: 8),
          if (max == 1)
            Text(
              'این گوشی فقط یک هسته را می‌تواند به برنامه بدهد.',
              style: theme.textTheme.bodyMedium,
            )
          else
            Row(
              children: [
                Expanded(
                  child: Slider(
                    min: 1,
                    max: max.toDouble(),
                    divisions: max - 1,
                    value: cores.toDouble(),
                    label: toPersianDigits('$cores'),
                    onChanged: (v) => notifier.setCores(v.round()),
                  ),
                ),
                Text(
                  '${toPersianDigits('$cores')} هسته',
                  style: theme.textTheme.titleMedium,
                ),
              ],
            ),
          Text(
            'تغییر از ضبط یا تحلیل بعدی اعمال می‌شود.',
            style: theme.textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}
