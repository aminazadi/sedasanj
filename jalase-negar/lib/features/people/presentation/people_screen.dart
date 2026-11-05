import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/utils/format.dart';
import '../application/people_providers.dart';
import '../data/person.dart';

/// Error code shown with problems of this screen (see the help center).
const String kPeopleSyncErrorCode = 'JN-SPK-0001';

/// The people the user enrolled, whose voices are recognised in meetings.
class PeopleScreen extends ConsumerWidget {
  const PeopleScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final people = ref.watch(peopleProvider);
    final modelInstalled = ref.watch(speakerModelInstalledProvider).value;
    return Scaffold(
      body: ListView(
        padding: EdgeInsets.fromLTRB(
          16,
          16,
          16,
          96 + MediaQuery.paddingOf(context).bottom,
        ),
        children: [
          if (modelInstalled == false) ...[
            SsCard(
              title: 'مدل تشخیص گوینده نصب نیست',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    'برای ثبت صدا و نوشتن نام گوینده کنار متن، مدل «تشخیص گوینده» '
                    '(حدود ۲۷ مگابایت) باید یک‌بار دانلود شود؛ بعد از آن همه‌چیز '
                    'آفلاین کار می‌کند.',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                  const SizedBox(height: 8),
                  FilledButton.icon(
                    onPressed: () => context.push('/models'),
                    icon: const Icon(Icons.download_outlined),
                    label: const Text('رفتن به مدل‌ها'),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 12),
          ],
          people.when(
            loading: () => const Padding(
              padding: EdgeInsets.all(32),
              child: Center(child: CircularProgressIndicator()),
            ),
            error: (e, _) => SsCard(child: Text('خطا در خواندن افراد: $e')),
            data: (list) => list.isEmpty
                ? const Padding(
                    padding: EdgeInsets.only(top: 24),
                    child: SsEmptyState(
                      title: 'هنوز کسی ثبت نشده است',
                      hint:
                          'هر فرد چند متن کوتاه را می‌خواند تا اپ بتواند صدایش را در جلسه‌ها تشخیص دهد و نامش را کنار متن بنویسد.',
                    ),
                  )
                : Column(
                    children: [
                      for (final p in list) ...[
                        _PersonTile(person: p),
                        const SizedBox(height: 8),
                      ],
                    ],
                  ),
          ),
        ],
      ),
    );
  }
}

class _PersonTile extends ConsumerWidget {
  const _PersonTile({required this.person});

  final Person person;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final installed = ref.watch(speakerModelInstalledProvider).value ?? true;
    return SsCard(
      ripple: true,
      onTap: () => context.push('/people/${person.clientId}'),
      child: Row(
        children: [
          CircleAvatar(
            backgroundColor: SsColors.selected,
            foregroundColor: SsColors.primaryDark,
            child: Text(
              person.name.isEmpty ? '؟' : person.name.characters.first,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(person.name, style: theme.textTheme.titleSmall),
                const SizedBox(height: 4),
                Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  children: [
                    SsBadge(
                      person.voiceprintCount == 0
                          ? 'بدون ردصدا'
                          : '${toPersianDigits('${person.voiceprintCount}')} نمونه صدا',
                      color: person.voiceprintCount == 0
                          ? SsColors.warning
                          : SsColors.primary,
                    ),
                    if (!person.mine)
                      const SsBadge(
                        'همکار (فقط‌خواندنی)',
                        color: SsColors.neutral,
                      )
                    else if (person.shared)
                      const SsBadge(
                        'اشتراکی با سازمان',
                        color: SsColors.neutral,
                      ),
                    if (person.pendingSync)
                      const SsBadge('منتظر ارسال', color: SsColors.warning),
                    if (!installed && person.voiceprintCount > 0)
                      const SsBadge('مدل نصب نیست', color: SsColors.warning),
                  ],
                ),
              ],
            ),
          ),
          const Icon(Icons.chevron_right) /* mirrors to point left in RTL */,
        ],
      ),
    );
  }
}
