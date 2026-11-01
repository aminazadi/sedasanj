import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/utils/format.dart';
import '../../upload/upload_controller.dart';
import '../application/pipeline_controller.dart';
import '../data/meeting.dart';

class MeetingsScreen extends ConsumerWidget {
  const MeetingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final meetings = ref.watch(meetingsProvider);
    final upload = ref.watch(uploadQueueProvider);

    return Stack(
      children: [
        meetings.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => Center(child: Text('خطا: $e')),
          data: (items) => items.isEmpty
              ? const SsEmptyState(
                  title: 'هنوز جلسه‌ای ضبط نشده است',
                  hint: 'برای شروع روی «ضبط جلسه» بزنید',
                )
              : RefreshIndicator(
                  onRefresh: () => ref.refresh(meetingsProvider.future),
                  child: ListView.builder(
                    padding: const EdgeInsets.fromLTRB(12, 12, 12, 88),
                    itemCount: items.length + 1,
                    itemBuilder: (context, index) => index == 0
                        ? Padding(
                            padding: const EdgeInsets.only(bottom: 12),
                            child: Column(
                              children: [
                                SsPageHeader(
                                  title: 'جلسه‌های من',
                                  description:
                                      '${items.length} جلسه ضبط‌شده روی همین دستگاه',
                                ),
                                if (upload.needsReconnect)
                                  const _QueueNotice(
                                    'توکن ابطال شده است؛ از «تنظیمات» دوباره به صداسنج متصل شوید.',
                                  )
                                else if (upload.creditExhausted)
                                  const _QueueNotice(
                                    'اعتبار سازمان تمام شده است؛ در پنل صداسنج شارژ کنید تا ارسال ادامه یابد.',
                                  ),
                              ],
                            ),
                          )
                        : _MeetingTile(meeting: items[index - 1]),
                  ),
                ),
        ),
        // FloatingActionButton
        Positioned(
          bottom: 16,
          left: 16,
          right: 16,
          child: Center(
            child: FloatingActionButton.extended(
              onPressed: () => context.push('/record'),
              icon: const Icon(Icons.mic),
              label: const Text('ضبط جلسه'),
            ),
          ),
        ),
      ],
    );
  }
}

class _MeetingTile extends ConsumerWidget {
  const _MeetingTile({required this.meeting});

  final Meeting meeting;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: SsCard(
        padding: EdgeInsets.zero,
        onTap: () => context.push('/meeting/${meeting.id}'),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 12, 4, 12),
          child: Row(
            children: [
              Container(
                width: 40,
                height: 40,
                decoration: BoxDecoration(
                  color: SsColors.selected,
                  border: Border.all(color: SsColors.line),
                ),
                child: Icon(
                  _statusIcon(meeting.status),
                  size: 20,
                  color: SsColors.primary,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      meeting.title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleSmall,
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '${formatJalaliDate(meeting.createdAt)} • '
                      '${formatDuration(meeting.duration)}',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                    ref
                        .watch(uploadProgressProvider(meeting.id))
                        .maybeWhen(
                          data: (p) =>
                              p.$2 == 0 ||
                                  meeting.status == MeetingStatus.complete
                              ? const SizedBox.shrink()
                              : Padding(
                                  padding: const EdgeInsets.only(top: 2),
                                  child: Text(
                                    'ارسال ${p.$1} از ${p.$2} تکه',
                                    style: Theme.of(
                                      context,
                                    ).textTheme.labelSmall,
                                  ),
                                ),
                          orElse: () => const SizedBox.shrink(),
                        ),
                  ],
                ),
              ),
              SsBadge(
                _statusLabel(meeting.status),
                color: switch (meeting.status) {
                  MeetingStatus.complete => SsColors.success,
                  MeetingStatus.failed => SsColors.danger,
                  _ => SsColors.neutral,
                },
              ),
              PopupMenuButton<String>(
                onSelected: (value) async {
                  if (value != 'delete') return;
                  final confirmed = await showDialog<bool>(
                    context: context,
                    builder: (context) => AlertDialog(
                      title: const Text('حذف جلسه'),
                      content: Text(
                        '«${meeting.title}» به همراه فایل صوتی، متن و صورت‌جلسه حذف شود؟',
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
                  if (confirmed == true) {
                    await ref
                        .read(pipelineControllerProvider(meeting.id).notifier)
                        .deleteMeeting();
                  }
                },
                itemBuilder: (context) => const [
                  PopupMenuItem(value: 'delete', child: Text('حذف جلسه')),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  IconData _statusIcon(MeetingStatus status) => switch (status) {
    MeetingStatus.recording => Icons.fiber_manual_record,
    MeetingStatus.recorded => Icons.audiotrack,
    MeetingStatus.transcribing => Icons.hourglass_top,
    MeetingStatus.transcribed => Icons.notes,
    MeetingStatus.uploading => Icons.cloud_upload_outlined,
    MeetingStatus.uploaded => Icons.cloud_done_outlined,
    MeetingStatus.processing => Icons.hourglass_top,
    MeetingStatus.complete => Icons.task_alt,
    MeetingStatus.failed => Icons.error_outline,
  };

  String _statusLabel(MeetingStatus status) => switch (status) {
    MeetingStatus.recording => 'در حال ضبط',
    MeetingStatus.recorded => 'ضبط‌شده',
    MeetingStatus.transcribing => 'در حال رونویسی',
    MeetingStatus.transcribed => 'رونویسی‌شده',
    MeetingStatus.uploading => 'در حال ارسال',
    MeetingStatus.uploaded => 'ارسال‌شده',
    MeetingStatus.processing => 'در حال پردازش',
    MeetingStatus.complete => 'کامل',
    MeetingStatus.failed => 'ناموفق',
  };
}

class _QueueNotice extends StatelessWidget {
  const _QueueNotice(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: 8),
    child: SsCard(
      child: Text(
        text,
        style: TextStyle(color: Theme.of(context).colorScheme.error),
      ),
    ),
  );
}
