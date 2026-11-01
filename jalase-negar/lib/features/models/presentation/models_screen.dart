import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/models/download_manager.dart';
import '../../../core/models/model_spec.dart';
import '../../../core/utils/format.dart';
import '../application/models_controller.dart';
import '../../../app/widgets/ss_widgets.dart';

class ModelsScreen extends ConsumerWidget {
  const ModelsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(modelsControllerProvider);
    return Scaffold(
      appBar: SsAppBar(title: const Text('مدل‌های هوش مصنوعی')),
      body: state.loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(12),
              children: [
                const SsPageHeader(
                  title: 'مدل‌های هوش مصنوعی',
                  description: 'دانلود و مدیریت مدل‌های آفلاین',
                ),
                const _SectionHeader(
                  title: 'تشخیص گفتار',
                  subtitle: 'پیش‌نیاز رونویسی؛ حجم بسیار کم',
                ),
                for (final item in state.byKind(ModelKind.vad))
                  _ModelCard(item: item),
                const _SectionHeader(
                  title: 'بهبود صدای ورودی',
                  subtitle: 'اختیاری؛ برای نویز محیط و صدای ضعیف',
                ),
                for (final item in state.byKind(ModelKind.denoiser))
                  _ModelCard(item: item),
                const _SectionHeader(
                  title: 'مدل‌های شنوا (گفتار به متن)',
                  subtitle:
                      'برای بالاترین دقت «شنوا کوچیک ۱۱۴M» را انتخاب کنید؛ مدل‌های سبک‌تر سریع‌ترند',
                ),
                for (final item in state.byKind(ModelKind.asr))
                  _ModelCard(item: item),
              ],
            ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader({required this.title, required this.subtitle});

  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 16, bottom: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SsSectionTitle(title: title),
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 6, 4, 0),
            child: Text(subtitle, style: Theme.of(context).textTheme.bodySmall),
          ),
        ],
      ),
    );
  }
}

class _ModelCard extends ConsumerWidget {
  const _ModelCard({required this.item});

  final ModelItemState item;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final controller = ref.read(modelsControllerProvider.notifier);
    final download = item.download;
    final downloading = download?.status == DownloadStatus.downloading;

    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Flexible(
                            child: Text(
                              item.spec.nameFa,
                              style: Theme.of(context).textTheme.titleSmall,
                            ),
                          ),
                          if (item.spec.recommended)
                            const Padding(
                              padding: EdgeInsets.symmetric(horizontal: 6),
                              child: Chip(
                                label: Text('پیشنهادی'),
                                visualDensity: VisualDensity.compact,
                              ),
                            ),
                        ],
                      ),
                      Text(
                        item.spec.descriptionFa,
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                      Text(
                        formatBytes(item.spec.totalSizeBytes),
                        style: Theme.of(context).textTheme.labelSmall,
                      ),
                    ],
                  ),
                ),
                if (item.installed && item.spec.kind != ModelKind.vad)
                  IconButton(
                    tooltip: item.selected
                        ? 'مدل فعال'
                        : 'انتخاب به‌عنوان مدل فعال',
                    icon: Icon(
                      item.selected
                          ? Icons.radio_button_checked
                          : Icons.radio_button_off,
                      color: item.selected
                          ? Theme.of(context).colorScheme.primary
                          : null,
                    ),
                    onPressed: item.selected
                        ? null
                        : () => controller.select(item.spec.id),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            if (downloading) ...[
              LinearProgressIndicator(value: download!.progress),
              const SizedBox(height: 4),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    '${formatBytes(download.receivedBytes)} از '
                    '${formatBytes(download.totalBytes)}',
                    style: Theme.of(context).textTheme.labelSmall,
                  ),
                  if (download.speedBytesPerSecond > 0)
                    Text(
                      '${formatBytes(download.speedBytesPerSecond)}/ثانیه',
                      style: Theme.of(context).textTheme.labelSmall,
                    ),
                  TextButton(
                    onPressed: () => controller.cancelDownload(item.spec.id),
                    child: const Text('توقف'),
                  ),
                ],
              ),
            ] else if (item.installed)
              Row(
                children: [
                  Icon(
                    Icons.check_circle,
                    size: 18,
                    color: Theme.of(context).colorScheme.primary,
                  ),
                  const SizedBox(width: 4),
                  const Text('نصب‌شده'),
                  const Spacer(),
                  TextButton(
                    onPressed: () => controller.delete(item.spec.id),
                    child: const Text('حذف'),
                  ),
                ],
              )
            else
              Row(
                children: [
                  if (download?.status == DownloadStatus.failed)
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'دانلود ناموفق بود',
                            style: TextStyle(
                              color: Theme.of(context).colorScheme.error,
                            ),
                          ),
                          if (download?.error != null)
                            Text(
                              download!.error!,
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: Theme.of(context).textTheme.labelSmall,
                            ),
                        ],
                      ),
                    )
                  else if (download?.status == DownloadStatus.paused)
                    const Expanded(child: Text('متوقف‌شده (قابل ادامه)'))
                  else
                    const Spacer(),
                  FilledButton.tonalIcon(
                    icon: const Icon(Icons.download),
                    label: Text(
                      download?.status == DownloadStatus.paused ||
                              download?.status == DownloadStatus.failed
                          ? 'ادامه دانلود'
                          : 'دانلود',
                    ),
                    onPressed: () => controller.download(item.spec.id),
                  ),
                ],
              ),
          ],
        ),
      ),
    );
  }
}
