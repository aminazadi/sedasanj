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
    // Narrow watches: reloading the list (status polling, upload ticks) must
    // not rebuild or flash the screen. It only rebuilds when the set/order of
    // meetings changes; each tile then updates itself.
    final idsKey = ref.watch(
      meetingsProvider.select((a) => a.value?.map((m) => m.id).join(',')),
    );
    final failed = ref.watch(
      meetingsProvider.select((a) => a.hasError && !a.hasValue),
    );
    if (failed) {
      return Center(child: Text('خطا: ${ref.read(meetingsProvider).error}'));
    }
    if (idsKey == null) {
      return const Center(child: CircularProgressIndicator());
    }
    final ids = idsKey.isEmpty ? const <String>[] : idsKey.split(',');
    if (ids.isEmpty) {
      return const SsEmptyState(
        title: 'هنوز جلسه‌ای ضبط نشده است',
        hint: 'برای شروع روی دکمهٔ «ضبط جلسه» پایین صفحه بزنید',
      );
    }
    return RefreshIndicator(
      onRefresh: () => ref.refresh(meetingsProvider.future),
      child: ListView.builder(
        padding: const EdgeInsets.all(12),
        itemCount: ids.length + 1,
        findChildIndexCallback: (key) {
          if (key is! ValueKey<String>) return null;
          final i = ids.indexOf(key.value);
          return i < 0 ? null : i + 1;
        },
        itemBuilder: (context, index) => index == 0
            ? const _Header(key: ValueKey('header'))
            : _MeetingTile(key: ValueKey(ids[index - 1]), id: ids[index - 1]),
      ),
    );
  }
}

class _Header extends ConsumerWidget {
  const _Header({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final needsReconnect = ref.watch(
      uploadQueueProvider.select((s) => s.needsReconnect),
    );
    final creditExhausted = ref.watch(
      uploadQueueProvider.select((s) => s.creditExhausted),
    );
    final notice = needsReconnect
        ? 'توکن ابطال شده است؛ از «تنظیمات» دوباره به صداسنج متصل شوید.'
        : creditExhausted
        ? 'اعتبار سازمان تمام شده است؛ در پنل صداسنج شارژ کنید تا ارسال ادامه یابد.'
        : null;
    if (notice == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: _QueueNotice(notice),
    );
  }
}

class _MeetingTile extends ConsumerWidget {
  const _MeetingTile({super.key, required this.id});

  final String id;

  Color _tone(MeetingStatus status) => switch (status) {
    MeetingStatus.complete => SsColors.success,
    MeetingStatus.failed => SsColors.danger,
    _ => SsColors.neutral,
  };

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    // Rebuilds only when this meeting itself changed (Meeting has value ==).
    final meeting = ref.watch(
      meetingsProvider.select(
        (a) => a.value?.where((m) => m.id == id).firstOrNull,
      ),
    );
    if (meeting == null) return const SizedBox.shrink();
    // `.value` keeps the previous progress while the provider reloads, so the
    // progress row never flickers away between ticks.
    final counts = ref.watch(uploadProgressProvider(id).select((a) => a.value));
    final progress =
        counts == null ||
            counts.$2 == 0 ||
            meeting.status == MeetingStatus.complete
        ? null
        : counts;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: SsCard(
        padding: EdgeInsets.zero,
        onTap: () => context.push('/meeting/${meeting.id}'),
        child: IntrinsicHeight(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Status accent edge on the start (right) side.
              AnimatedContainer(
                duration: const Duration(milliseconds: 250),
                width: 4,
                color: switch (meeting.status) {
                  MeetingStatus.complete => SsColors.primary,
                  MeetingStatus.failed => SsColors.danger,
                  _ => SsColors.accent,
                },
              ),
              Expanded(
                child: Padding(
                  padding: const EdgeInsetsDirectional.fromSTEB(14, 6, 4, 0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              displayMeetingTitle(meeting.title),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: theme.textTheme.titleSmall,
                            ),
                          ),
                          _menu(context, ref, meeting),
                        ],
                      ),
                      Padding(
                        padding: const EdgeInsetsDirectional.only(end: 10),
                        child: Row(
                          children: [
                            _Meta(
                              Icons.calendar_today_outlined,
                              '${formatJalaliDay(meeting.createdAt)}  ·  '
                              '${formatClock(meeting.createdAt)}',
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 10),
                      Container(height: 1, color: SsColors.line),
                      Padding(
                        padding: const EdgeInsetsDirectional.only(
                          end: 10,
                          top: 10,
                          bottom: 12,
                        ),
                        child: Row(
                          children: [
                            SsBadge(
                              _statusLabel(meeting.status),
                              color: _tone(meeting.status),
                              icon: _statusIcon(meeting.status),
                              leading: _isBusy(meeting.status)
                                  ? const SsProcessingMark(size: 14)
                                  : null,
                            ),
                            if (progress != null) ...[
                              const SizedBox(width: 10),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      toPersianDigits(
                                        'ارسال ${progress.$1} از ${progress.$2} تکه',
                                      ),
                                      style: theme.textTheme.labelSmall,
                                    ),
                                    const SizedBox(height: 4),
                                    LinearProgressIndicator(
                                      value: progress.$1 / progress.$2,
                                      minHeight: 3,
                                      color: SsColors.primary,
                                      backgroundColor: SsColors.line,
                                    ),
                                  ],
                                ),
                              ),
                              const SizedBox(width: 10),
                            ] else
                              const Spacer(),
                            _Meta(
                              Icons.timer_outlined,
                              formatDuration(meeting.duration),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _menu(BuildContext context, WidgetRef ref, Meeting meeting) {
    return SizedBox(
      width: 32,
      height: 32,
      child: PopupMenuButton<String>(
        padding: EdgeInsets.zero,
        iconSize: 20,
        icon: const Icon(Icons.more_vert, color: SsColors.neutral),
        tooltip: 'گزینه‌ها',
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
        constraints: const BoxConstraints(minWidth: 0),
        position: PopupMenuPosition.under,
        itemBuilder: (context) => [
          PopupMenuItem(
            value: 'delete',
            height: 38,
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(
                  Icons.delete_outline,
                  size: 17,
                  color: SsColors.danger,
                ),
                const SizedBox(width: 8),
                Text(
                  'حذف جلسه',
                  style: Theme.of(
                    context,
                  ).textTheme.labelMedium?.copyWith(color: SsColors.danger),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  bool _isBusy(MeetingStatus status) =>
      status == MeetingStatus.transcribing ||
      status == MeetingStatus.uploading ||
      status == MeetingStatus.processing;

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

/// Small icon + text pair for a tile's date / time / duration line.
class _Meta extends StatelessWidget {
  const _Meta(this.icon, this.text);

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 14, color: SsColors.neutral),
        const SizedBox(width: 5),
        Text(text, style: Theme.of(context).textTheme.bodySmall),
      ],
    );
  }
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
