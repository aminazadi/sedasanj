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
              child: Center(child: SsProcessingMark(size: 30)),
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
                        const SizedBox(height: 10),
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
      elevated: true,
      padding: EdgeInsets.zero,
      onTap: () => context.push('/people/${person.clientId}'),
      child: Padding(
        padding: const EdgeInsetsDirectional.fromSTEB(16, 12, 4, 14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    person.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 6),
                  child: Icon(
                    Icons.chevron_right /* mirrors to point left in RTL */,
                    color: SsColors.of(context).neutral,
                  ),
                ),
              ],
            ),
            Padding(
              padding: const EdgeInsetsDirectional.only(end: 12, top: 10),
              child: Wrap(
                spacing: 6,
                runSpacing: 4,
                children: [
                  SsBadge(
                    person.voiceprintCount == 0
                        ? 'بدون ردصدا'
                        : '${toPersianDigits('${person.voiceprintCount}')} نمونه صدا',
                    color: person.voiceprintCount == 0
                        ? SsColors.of(context).warning
                        : SsColors.of(context).primary,
                  ),
                  if (!person.mine)
                    SsBadge(
                      'همکار (فقط‌خواندنی)',
                      color: SsColors.of(context).neutral,
                    )
                  else if (person.shared)
                    SsBadge(
                      'اشتراکی با سازمان',
                      color: SsColors.of(context).neutral,
                    ),
                  if (person.pendingSync)
                    SsBadge('منتظر ارسال', color: SsColors.of(context).warning),
                  if (!installed && person.voiceprintCount > 0)
                    SsBadge(
                      'مدل نصب نیست',
                      color: SsColors.of(context).warning,
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
