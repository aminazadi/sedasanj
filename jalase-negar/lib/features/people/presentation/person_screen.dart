import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/models/model_catalog.dart';
import '../../../core/utils/format.dart';
import '../application/people_providers.dart';
import '../data/person.dart';

/// One person: rename, sharing, voice samples, record again, delete.
class PersonScreen extends ConsumerWidget {
  const PersonScreen({super.key, required this.personId});

  final String personId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final people = ref.watch(peopleProvider);
    final person = people.value
        ?.where((p) => p.clientId == personId)
        .firstOrNull;
    if (person == null) {
      return Scaffold(
        appBar: SsAppBar(title: const Text('فرد')),
        body: Center(
          child: people.isLoading
              ? const SsProcessingMark(size: 30)
              : const Text('این فرد پیدا نشد.'),
        ),
      );
    }
    final theme = Theme.of(context);
    final actions = ref.read(peopleActionsProvider);
    final voiceprints =
        ref.watch(_voiceprintsProvider(personId)).value ?? const [];
    final needsReEnroll =
        voiceprints.isNotEmpty &&
        !voiceprints.any(
          (v) =>
              v.modelId == ModelCatalog.speakerEmbedding.id &&
              v.modelVersion == ModelCatalog.speakerEmbeddingVersion,
        );

    return Scaffold(
      appBar: SsAppBar(
        title: Text(person.name),
        actions: [
          if (person.mine)
            IconButton(
              tooltip: 'تغییر نام',
              onPressed: () => _rename(context, ref, person),
              icon: const Icon(Icons.edit_outlined),
            ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (!person.mine)
            const SsCard(
              child: Text(
                'این فرد را یکی از همکارانتان با سازمان به اشتراک گذاشته است؛ برای تشخیص گوینده استفاده می‌شود ولی ویرایش یا حذف آن فقط با صاحبش است.',
              ),
            ),
          if (person.mine) ...[
            SsCard(
              child: SsSwitchTile(
                value: person.shared,
                onChanged: (v) => actions.update(
                  person.clientId,
                  visibility: v
                      ? PersonVisibility.org
                      : PersonVisibility.private,
                ),
                title: const Text('اشتراک با سازمان'),
                subtitle: Text(
                  person.shared
                      ? 'همکاران متصل به سازمان می‌توانند از این صدا برای تشخیص گوینده استفاده کنند.'
                      : 'فقط شما از این صدا استفاده می‌کنید.',
                ),
              ),
            ),
            const SizedBox(height: 12),
          ],
          SsCard(
            title: 'نمونه‌های صدا',
            trailing: person.pendingSync
                ? const SsBadge('منتظر ارسال', color: SsColors.warning)
                : null,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (person.consentAt != null)
                  Text(
                    'رضایت ثبت‌شده: ${formatJalaliDay(person.consentAt!)}',
                    style: theme.textTheme.bodySmall,
                  ),
                if (needsReEnroll) ...[
                  const SizedBox(height: 6),
                  Text(
                    'نمونه‌های این فرد با مدلی ساخته شده که روی این گوشی نصب نیست؛ '
                    'برای شناسایی، صدا را دوباره ثبت کنید یا مدل را نصب کنید.',
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: SsColors.danger,
                    ),
                  ),
                ],
                if (voiceprints.isEmpty)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Text(
                      'هنوز صدایی ثبت نشده است.',
                      style: theme.textTheme.bodyMedium,
                    ),
                  ),
                for (final v in voiceprints)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    dense: true,
                    leading: const Icon(Icons.graphic_eq),
                    title: Text(
                      'نمونه‌ی ${formatJalaliDay(v.createdAt)}'
                      '${v.quality == null ? '' : ' — کیفیت ${toPersianDigits('${v.quality}')}٪'}',
                    ),
                    subtitle: v.synced
                        ? null
                        : const Text('هنوز به صداسنج نرسیده'),
                    trailing: person.mine
                        ? IconButton(
                            tooltip: 'حذف این نمونه',
                            onPressed: () => actions.removeVoiceprint(
                              person.clientId,
                              v.clientId,
                            ),
                            icon: const Icon(Icons.close, size: 18),
                          )
                        : null,
                  ),
                if (person.mine)
                  FilledButton.icon(
                    onPressed: () =>
                        context.push('/people/${person.clientId}/enroll'),
                    icon: const Icon(Icons.mic),
                    label: Text(
                      voiceprints.isEmpty ? 'ثبت صدا' : 'ثبت نمونه‌ی بیشتر',
                    ),
                  ),
              ],
            ),
          ),
          if (person.mine) ...[
            const SizedBox(height: 12),
            OutlinedButton.icon(
              style: OutlinedButton.styleFrom(foregroundColor: SsColors.danger),
              onPressed: () => _confirmDelete(context, ref, person),
              icon: const Icon(Icons.delete_outline),
              label: const Text('حذف این فرد و صدایش'),
            ),
          ],
        ],
      ),
    );
  }

  Future<void> _rename(
    BuildContext context,
    WidgetRef ref,
    Person person,
  ) async {
    final controller = TextEditingController(text: person.name);
    final name = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('تغییر نام'),
        content: TextField(
          controller: controller,
          autofocus: true,
          maxLength: 80,
          onSubmitted: (v) => Navigator.pop(context, v),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('انصراف'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, controller.text),
            child: const Text('ذخیره'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (name == null || name.trim().isEmpty) return;
    await ref.read(peopleActionsProvider).update(person.clientId, name: name);
  }

  Future<void> _confirmDelete(
    BuildContext context,
    WidgetRef ref,
    Person person,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('حذف فرد'),
        content: Text(
          'نام و ردصدای «${person.name}» از این گوشی، صداسنج و گوشی‌های دیگر شما '
          'پاک می‌شود. متن جلسه‌های قبلی همان نام را نگه می‌دارد.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('انصراف'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('حذف'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    await ref.read(peopleActionsProvider).delete(person.clientId);
    if (!context.mounted) return;
    SsToastHost.show(context, 'فرد حذف شد');
    if (context.canPop()) context.pop();
  }
}

final _voiceprintsProvider = FutureProvider.family<List<Voiceprint>, String>((
  ref,
  personId,
) async {
  ref.watch(speakerSyncProvider.select((s) => s.tick));
  final repo = await ref.watch(peopleRepositoryProvider.future);
  return repo.voiceprints(personId);
});
