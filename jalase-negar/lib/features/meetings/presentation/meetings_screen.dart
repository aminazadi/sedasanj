import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:shamsi_date/shamsi_date.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/providers.dart';
import '../../../core/utils/format.dart';
import '../../models/application/models_controller.dart';
import '../../recording/application/recorder_controller.dart';
import '../../upload/upload_controller.dart';
import '../application/meeting_providers.dart';
import '../application/meetings_search_controller.dart';
import '../data/meeting.dart';
import '../data/meeting_repository.dart' show foldPersianLetters;
import 'jalali_date_picker.dart';
import 'send_meeting_action.dart';
import 'share_meeting_audio.dart';

bool _matchesQuery(Meeting m, String query, Set<String> textMatches) {
  if (query.trim().isEmpty) return true;
  final q = toPersianDigits(foldPersianLetters(query.trim()));
  return displayMeetingTitle(m.title).contains(q) ||
      formatJalaliDay(m.createdAt).contains(q) ||
      textMatches.contains(m.id);
}

bool _matchesDate(Meeting m, Jalali? date) {
  if (date == null) return true;
  final d = Jalali.fromDateTime(m.createdAt);
  return d.year == date.year && d.month == date.month && d.day == date.day;
}

class MeetingsScreen extends ConsumerStatefulWidget {
  const MeetingsScreen({super.key});

  @override
  ConsumerState<MeetingsScreen> createState() => _MeetingsScreenState();
}

class _MeetingsScreenState extends ConsumerState<MeetingsScreen> {
  // The transcript lookup follows the typing after a short pause.
  var _textQuery = '';
  Timer? _debounce;

  void _scheduleTextMatch(String query) {
    _debounce?.cancel();
    if (query.trim().isEmpty) {
      setState(() => _textQuery = '');
      return;
    }
    _debounce = Timer(const Duration(milliseconds: 250), () {
      if (mounted) setState(() => _textQuery = query);
    });
  }

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }

  /// Opens the "jump to date" calendar from a pinned date-group header and
  /// applies the pick as a filter on the list.
  Future<void> _pickDate(BuildContext context) async {
    final current = ref.read(meetingsSearchProvider).date;
    final picked = await showJalaliDatePicker(context, initial: current);
    if (picked == null || !mounted) return;
    ref.read(meetingsSearchProvider.notifier).setDate(picked);
  }

  @override
  Widget build(BuildContext context) {
    final hidden = ref.watch(pendingDeletesProvider);
    // The search box lives in the shell's header, not on this screen.
    final search = ref.watch(meetingsSearchProvider);
    ref.listen(
      meetingsSearchProvider.select((s) => s.query),
      (_, next) => _scheduleTextMatch(next),
    );
    // Search results follow list changes (a finished transcription or an
    // edit), refreshed after the frame so no provider is invalidated mid-build.
    ref.listen(meetingsProvider, (_, _) {
      Future.microtask(() {
        if (mounted) ref.invalidate(transcriptMatchesProvider);
      });
    });
    // Narrow watches: reloading the list (status polling, upload ticks) must
    // not rebuild or flash the screen. It only rebuilds when the set/order of
    // visible meetings changes; each tile then updates itself.
    final textMatches =
        ref.watch(transcriptMatchesProvider(_textQuery)).value ??
        const <String>{};
    final idsKey = ref.watch(
      meetingsProvider.select(
        (a) => a.value
            ?.where(
              (m) =>
                  !hidden.contains(m.id) &&
                  search.filter.accepts(m) &&
                  _matchesQuery(m, search.query, textMatches) &&
                  _matchesDate(m, search.date),
            )
            .map((m) => m.id)
            .join(','),
      ),
    );
    final total = ref.watch(
      meetingsProvider.select(
        (a) => a.value?.where((m) => !hidden.contains(m.id)).length,
      ),
    );
    final failed = ref.watch(
      meetingsProvider.select((a) => a.hasError && !a.hasValue),
    );
    if (failed) {
      return SsEmptyState(
        title: 'بارگذاری فهرست جلسه‌ها ناموفق بود',
        hint:
            'دوباره تلاش کنید. اگر خطا تکرار شد، برنامه را ببندید و باز کنید. '
            '(JN-MTG-0001)',
        action: FilledButton.icon(
          onPressed: () => ref.invalidate(meetingRepositoryProvider),
          icon: const Icon(Icons.refresh, size: 18),
          label: const Text('تلاش مجدد'),
        ),
      );
    }
    if (idsKey == null || total == null) return const _SkeletonList();
    if (total == 0) {
      return SsEmptyState(
        title: 'هنوز جلسه‌ای ضبط نشده است',
        hint: 'اولین جلسهٔ خود را ضبط کنید تا متن آن اینجا ظاهر شود',
        action: FilledButton.icon(
          onPressed: () => context.push('/record'),
          icon: const Icon(Icons.mic_none, size: 18),
          label: const Text('ضبط اولین جلسه'),
        ),
      );
    }

    final ids = idsKey.isEmpty ? const <String>[] : idsKey.split(',');
    final byId = {
      for (final m in ref.read(meetingsProvider).value ?? const <Meeting>[])
        m.id: m,
    };
    final now = DateTime.now();
    final groups = <(String, List<String>)>[];
    for (final id in ids) {
      final meeting = byId[id];
      if (meeting == null) continue;
      final label = meetingGroupLabel(meeting.createdAt, now);
      if (groups.isNotEmpty && groups.last.$1 == label) {
        groups.last.$2.add(id);
      } else {
        groups.add((label, [id]));
      }
    }

    return RefreshIndicator(
      onRefresh: () => ref.refresh(meetingsProvider.future),
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          const SliverToBoxAdapter(child: _Header(key: ValueKey('header'))),
          const SliverToBoxAdapter(child: _ModelsPromptCard()),
          if (ids.isEmpty)
            SliverFillRemaining(
              hasScrollBody: false,
              child: _NoResults(
                onClear: () =>
                    ref.read(meetingsSearchProvider.notifier).clear(),
              ),
            )
          else
            for (final (index, (label, groupIds)) in groups.indexed)
              SliverMainAxisGroup(
                slivers: [
                  // The first group's date is obvious from context, so its
                  // header is skipped; later groups still show one.
                  if (index != 0)
                    SliverPersistentHeader(
                      pinned: true,
                      delegate: _GroupHeaderDelegate(
                        label,
                        groupIds.length,
                        onTap: () => _pickDate(context),
                      ),
                    ),
                  SliverPadding(
                    // Without its own header above, the first group needs
                    // the same standard top gap other sections use instead
                    // of the header's left-over 2px.
                    padding: EdgeInsets.fromLTRB(
                      12,
                      index == 0 ? 12 : 2,
                      12,
                      4,
                    ),
                    sliver: SliverList.builder(
                      itemCount: groupIds.length,
                      findChildIndexCallback: (key) {
                        if (key is! ValueKey<String>) return null;
                        final i = groupIds.indexOf(key.value);
                        return i < 0 ? null : i;
                      },
                      itemBuilder: (context, i) => _MeetingTile(
                        key: ValueKey(groupIds[i]),
                        id: groupIds[i],
                      ),
                    ),
                  ),
                ],
              ),
          // The shell extends the body behind the bottom bar so the list shows
          // through the notch under the record button; leave room to scroll
          // the last card clear of the bar.
          SliverToBoxAdapter(
            child: SizedBox(height: MediaQuery.paddingOf(context).bottom + 12),
          ),
        ],
      ),
    );
  }
}

/// A meeting-card-styled prompt shown above the list, only while the
/// transcription models are not fully installed and activated.
class _ModelsPromptCard extends ConsumerWidget {
  const _ModelsPromptCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(modelsControllerProvider);
    if (state.loading || state.ready) return const SizedBox.shrink();
    final theme = Theme.of(context);
    final downloading = state.installingAll;
    final failed = state.hasFailure && !downloading;
    final percent = toPersianDigits('${(state.progress * 100).floor()}');

    return Padding(
      // Top padding so this card doesn't sit flush against the header above
      // it, matching its own bottom spacing before the meetings list.
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      child: SsCard(
        ripple: true,
        elevated: true,
        onTap: () => context.push('/models'),
        child: Row(
          children: [
            Icon(Icons.download_outlined, color: SsColors.of(context).primary),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'نصب مدل‌های رونویسی',
                    style: theme.textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    downloading
                        ? 'در حال دانلود و نصب… $percent٪'
                        : failed
                        ? 'دانلود کامل نشد؛ برای ادامه دوباره بزنید.'
                        : 'برای رونویسی فارسی و تشخیص گوینده روی گوشی و '
                              'بدون اینترنت، مدل‌ها را دانلود و نصب کنید.',
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: SsColors.of(context).ink.withValues(alpha: 0.8),
                    ),
                  ),
                  if (downloading) ...[
                    const SizedBox(height: 8),
                    LinearProgressIndicator(value: state.progress),
                  ],
                ],
              ),
            ),
            Icon(Icons.chevron_right, color: SsColors.of(context).neutral),
          ],
        ),
      ),
    );
  }
}

class _GroupHeaderDelegate extends SliverPersistentHeaderDelegate {
  const _GroupHeaderDelegate(this.label, this.count, {required this.onTap});

  final String label;
  final int count;
  final VoidCallback onTap;

  @override
  double get minExtent => 38;

  @override
  double get maxExtent => 38;

  @override
  Widget build(
    BuildContext context,
    double shrinkOffset,
    bool overlapsContent,
  ) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      alignment: Alignment.center,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(999),
          onTap: onTap,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
            decoration: BoxDecoration(
              color: SsColors.of(context).canvas,
              border: Border.all(
                color: SsColors.of(context).neutral.withValues(alpha: 0.5),
              ),
              borderRadius: BorderRadius.circular(999),
            ),
            child: Text(
              label,
              style: theme.textTheme.labelLarge?.copyWith(
                color: SsColors.of(context).primaryDark,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ),
      ),
    );
  }

  @override
  bool shouldRebuild(_GroupHeaderDelegate old) =>
      old.label != label || old.count != count;
}

class _NoResults extends StatelessWidget {
  const _NoResults({required this.onClear});

  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.all(32),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.search_off, size: 44, color: SsColors.of(context).accent),
          const SizedBox(height: 12),
          Text('جلسه‌ای پیدا نشد', style: theme.textTheme.titleMedium),
          const SizedBox(height: 4),
          Text(
            'عبارت جست‌وجو یا فیلتر را تغییر دهید',
            style: theme.textTheme.bodySmall,
          ),
          const SizedBox(height: 12),
          TextButton(onPressed: onClear, child: const Text('پاک کردن فیلترها')),
        ],
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
    final date = ref.watch(meetingsSearchProvider.select((s) => s.date));
    final notice = needsReconnect
        ? 'توکن ابطال شده است؛ از «تنظیمات» دوباره به صداسنج متصل شوید.'
        : creditExhausted
        ? 'اعتبار سازمان تمام شده است؛ در پنل صداسنج شارژ کنید تا ارسال ادامه یابد.'
        : null;
    if (notice == null && date == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 4, 12, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (date != null) ...[
            _DateFilterChip(date),
            if (notice != null) const SizedBox(height: 8),
          ],
          if (notice != null) _QueueNotice(notice),
        ],
      ),
    );
  }
}

/// Shows the active "jump to date" filter, with a way to clear it back to
/// the full list.
class _DateFilterChip extends ConsumerWidget {
  const _DateFilterChip(this.date);

  final Jalali date;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final f = date.formatter;
    final label = toPersianDigits('${f.d} ${f.mN} ${f.yyyy}');
    return Align(
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          color: SsColors.of(context).selected,
          borderRadius: BorderRadius.circular(999),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.event,
              size: 14,
              color: SsColors.of(context).primaryDark,
            ),
            const SizedBox(width: 6),
            Text(
              label,
              style: theme.textTheme.labelSmall?.copyWith(
                color: SsColors.of(context).primaryDark,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(width: 6),
            InkWell(
              onTap: () =>
                  ref.read(meetingsSearchProvider.notifier).clearDate(),
              customBorder: const CircleBorder(),
              child: Padding(
                padding: EdgeInsets.all(2),
                child: Icon(
                  Icons.close,
                  size: 14,
                  color: SsColors.of(context).primaryDark,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _QueueNotice extends StatelessWidget {
  const _QueueNotice(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: scheme.errorContainer),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.info_outline, size: 18, color: scheme.error),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: scheme.error),
            ),
          ),
        ],
      ),
    );
  }
}

class _MeetingTile extends ConsumerWidget {
  const _MeetingTile({super.key, required this.id});

  final String id;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    // Rebuilds only when this meeting itself changed (Meeting has value ==).
    final stored = ref.watch(
      meetingsProvider.select(
        (a) => a.value?.where((m) => m.id == id).firstOrNull,
      ),
    );
    if (stored == null) return const SizedBox.shrink();
    // "Recording" is only true while the recorder is open on this meeting;
    // a stale row must read as recorded, never as a live capture.
    final capturing = ref.watch(
      recorderControllerProvider.select((s) => s.status != RecorderStatus.idle),
    );
    final meeting = capturing ? stored : stored.asClosedRecording();
    final preview =
        ref.watch(meetingPreviewProvider(id).select((a) => a.value)) ?? '';
    final canSwipe =
        meeting.status != MeetingStatus.recording &&
        meeting.status != MeetingStatus.transcribing;

    final card = SsCard(
      ripple: true,
      elevated: true,
      padding: EdgeInsets.zero,
      onTap: () => context.push('/meeting/${meeting.id}'),
      child: Padding(
        padding: const EdgeInsetsDirectional.fromSTEB(16, 12, 4, 14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: Hero(
                    tag: 'meeting-title-${meeting.id}',
                    child: Material(
                      type: MaterialType.transparency,
                      child: Text(
                        displayMeetingTitle(meeting.title),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ),
                ),
                _menu(context, ref, meeting, preview),
              ],
            ),
            Padding(
              padding: const EdgeInsetsDirectional.only(end: 12),
              child: Row(
                children: [
                  Expanded(
                    child: _Meta(
                      Icons.calendar_today_outlined,
                      '${formatJalaliDay(meeting.createdAt)}  ·  '
                      '${formatClock(meeting.createdAt)}',
                    ),
                  ),
                  _DurationChip(formatDuration(meeting.duration)),
                ],
              ),
            ),
            if (preview.isNotEmpty)
              Padding(
                padding: const EdgeInsetsDirectional.only(end: 12, top: 10),
                child: Text(
                  toPersianDigits(preview),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    fontSize: 13,
                    height: 1.65,
                    color: SsColors.of(context).ink.withValues(alpha: 0.8),
                  ),
                ),
              ),
            if (meeting.status != MeetingStatus.complete)
              Padding(
                padding: const EdgeInsetsDirectional.only(end: 12, top: 12),
                child: _StatusArea(meeting: meeting),
              ),
          ],
        ),
      ),
    );

    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: canSwipe
          ? Dismissible(
              key: ValueKey('dismiss-${meeting.id}'),
              // Swipe one way to rename (the card stays), the other to delete.
              direction: DismissDirection.horizontal,
              background: const _SwipeBackground.rename(),
              secondaryBackground: const _SwipeBackground.delete(),
              confirmDismiss: (direction) async {
                if (direction != DismissDirection.startToEnd) return true;
                await _rename(context, ref, meeting);
                return false;
              },
              onDismissed: (_) => _deleteWithUndo(context, meeting),
              child: card,
            )
          : Dismissible(
              key: ValueKey('rename-${meeting.id}'),
              direction: DismissDirection.startToEnd,
              background: const _SwipeBackground.rename(),
              confirmDismiss: (_) async {
                await _rename(context, ref, meeting);
                return false;
              },
              child: card,
            ),
    );
  }

  /// Hides the tile now and deletes for real once the undo toast closes
  /// without "restore", so a swipe never loses audio instantly.
  Future<void> _deleteWithUndo(BuildContext context, Meeting meeting) async {
    // The tile is gone after the swipe; keep what outlives it.
    final container = ProviderScope.containerOf(context);
    final pending = container.read(pendingDeletesProvider.notifier);
    final actions = container.read(meetingActionsProvider(meeting.id));
    pending.hide(meeting.id);
    final result = await SsToastHost.show(
      context,
      'جلسه حذف شد',
      actionLabel: 'بازگردانی',
      duration: const Duration(seconds: 5),
      queue: SsToastQueue.clear,
    );
    if (!actions.ref.mounted) return;
    try {
      if (result == SsToastResult.dismissed) await actions.deleteMeeting();
    } finally {
      if (actions.ref.mounted) pending.restore(meeting.id);
    }
  }

  Widget _menu(
    BuildContext context,
    WidgetRef ref,
    Meeting meeting,
    String preview,
  ) {
    TextStyle? style(Color? color) =>
        Theme.of(context).textTheme.labelMedium?.copyWith(color: color);
    PopupMenuItem<String> item(
      String value,
      IconData icon,
      String label, {
      Color? color,
      bool enabled = true,
    }) => PopupMenuItem(
      value: value,
      enabled: enabled,
      height: 40,
      padding: const EdgeInsets.symmetric(horizontal: 14),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 18, color: color ?? SsColors.of(context).ink),
          const SizedBox(width: 10),
          Flexible(child: Text(label, style: style(color))),
        ],
      ),
    );

    return PopupMenuButton<String>(
      icon: Icon(Icons.more_vert, color: SsColors.of(context).neutral),
      tooltip: 'گزینه‌ها',
      shape: RoundedRectangleBorder(
        side: BorderSide(color: SsColors.of(context).line),
      ),
      position: PopupMenuPosition.under,
      onSelected: (value) => switch (value) {
        'rename' => _rename(context, ref, meeting),
        'send' => sendMeetingToSedasanj(context, ref, meeting.id),
        'share' => shareMeetingAudio(context, meeting),
        _ => _confirmDelete(context, ref, meeting),
      },
      itemBuilder: (context) => [
        item('rename', Icons.edit_outlined, 'تغییر نام'),
        item(
          'send',
          Icons.cloud_upload_outlined,
          'ارسال به صداسنج',
          enabled: canSendMeetingText(meeting, hasText: preview.isNotEmpty),
        ),
        item('share', Icons.ios_share, 'اشتراک‌گذاری فایل صوتی'),
        item(
          'delete',
          Icons.delete_outline,
          'حذف جلسه',
          color: SsColors.of(context).danger,
        ),
      ],
    );
  }

  Future<void> _rename(
    BuildContext context,
    WidgetRef ref,
    Meeting meeting,
  ) async {
    final title = await showDialog<String>(
      context: context,
      builder: (context) =>
          _RenameDialog(initial: displayMeetingTitle(meeting.title)),
    );
    if (title == null) return;
    await ref.read(meetingActionsProvider(meeting.id)).renameMeeting(title);
  }

  Future<void> _confirmDelete(
    BuildContext context,
    WidgetRef ref,
    Meeting meeting,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('حذف جلسه'),
        content: Text(
          '«${displayMeetingTitle(meeting.title)}» به همراه فایل صوتی، متن و '
          'صورت‌جلسه حذف شود؟',
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
      await ref.read(meetingActionsProvider(meeting.id)).deleteMeeting();
    }
  }
}

class _RenameDialog extends StatefulWidget {
  const _RenameDialog({required this.initial});

  final String initial;

  @override
  State<_RenameDialog> createState() => _RenameDialogState();
}

class _RenameDialogState extends State<_RenameDialog> {
  late final _controller = TextEditingController(text: widget.initial);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('تغییر نام جلسه'),
      content: TextField(
        controller: _controller,
        autofocus: true,
        maxLength: 80,
        textInputAction: TextInputAction.done,
        onSubmitted: (v) => Navigator.pop(context, v),
        decoration: const InputDecoration(hintText: 'عنوان جلسه'),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('انصراف'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context, _controller.text),
          child: const Text('ذخیره'),
        ),
      ],
    );
  }
}

class _SwipeBackground extends StatelessWidget {
  const _SwipeBackground.rename()
    : _rename = true,
      icon = Icons.edit_outlined,
      label = 'تغییر نام',
      alignment = AlignmentDirectional.centerStart;

  const _SwipeBackground.delete()
    : _rename = false,
      icon = Icons.delete_outline,
      label = 'حذف',
      alignment = AlignmentDirectional.centerEnd;

  final bool _rename;
  final IconData icon;
  final String label;
  final AlignmentDirectional alignment;

  @override
  Widget build(BuildContext context) {
    final color = _rename
        ? SsColors.of(context).primary
        : SsColors.of(context).danger;
    return Container(
      color: color,
      padding: const EdgeInsets.symmetric(horizontal: 22),
      alignment: alignment,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: Colors.white),
          const SizedBox(width: 8),
          Text(
            label,
            style: const TextStyle(
              fontFamily: 'YekanBakh',
              color: Colors.white,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

/// Bottom area of a tile that is not complete: progress while the pipeline is
/// running, an error message for failures, otherwise a plain status badge.
class _StatusArea extends ConsumerWidget {
  const _StatusArea({required this.meeting});

  final Meeting meeting;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = meeting.status;
    if (status == MeetingStatus.failed) {
      return _FailedPanel(meeting: meeting);
    }
    if (meeting.analyzingSpeakers &&
        (status == MeetingStatus.recorded ||
            status == MeetingStatus.transcribed)) {
      final progress = ref.watch(speakerProgressProvider)[meeting.id] ?? 0;
      return _BusyLine(
        'در حال استخراج گوینده‌ها (${toPersianDigits("$progress")}٪)',
      );
    }
    if (status == MeetingStatus.uploading) {
      return const _BusyLine('در حال ارسال به صداسنج');
    }
    if (status == MeetingStatus.processing) {
      return const _BusyLine('در حال پردازش در صداسنج');
    }
    return Align(
      alignment: AlignmentDirectional.centerStart,
      child: SsBadge(
        _statusLabel(status),
        color: status == MeetingStatus.recording
            ? SsColors.of(context).danger
            : SsColors.of(context).neutral,
        icon: _statusIcon(status),
      ),
    );
  }

  static IconData _statusIcon(MeetingStatus status) => switch (status) {
    MeetingStatus.recording => Icons.fiber_manual_record,
    MeetingStatus.recorded => Icons.audiotrack,
    MeetingStatus.transcribed => Icons.notes,
    MeetingStatus.uploaded => Icons.cloud_done_outlined,
    _ => Icons.circle_outlined,
  };

  static String _statusLabel(MeetingStatus status) => switch (status) {
    MeetingStatus.recording => 'در حال ضبط',
    MeetingStatus.recorded => 'ضبط‌شده',
    MeetingStatus.transcribed => 'رونویسی‌شده',
    MeetingStatus.uploaded => 'ارسال‌شده',
    _ => '',
  };
}

/// The app's own loading mark with one line of text; no bar, no background.
class _BusyLine extends StatelessWidget {
  const _BusyLine(this.label);

  final String label;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        const SsProcessingMark(size: 14),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            label,
            style: Theme.of(context).textTheme.labelMedium?.copyWith(
              color: SsColors.of(context).primaryDark,
            ),
          ),
        ),
      ],
    );
  }
}

class _FailedPanel extends StatelessWidget {
  const _FailedPanel({required this.meeting});

  final Meeting meeting;

  @override
  Widget build(BuildContext context) {
    final error = meeting.error;
    // Stored errors may be raw exceptions; only show human (Persian) text.
    final message = error != null && RegExp(r'[؀-ۿ]').hasMatch(error)
        ? error
        : 'پردازش این جلسه ناموفق بود. برای بررسی، جزئیات جلسه را باز کنید.';
    return Container(
      padding: const EdgeInsetsDirectional.fromSTEB(12, 8, 6, 8),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.errorContainer,
      ),
      child: Row(
        children: [
          Icon(
            Icons.error_outline,
            size: 18,
            color: SsColors.of(context).danger,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.labelSmall?.copyWith(
                color: SsColors.of(context).danger,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Small icon + text pair for a tile's date / time line.
class _Meta extends StatelessWidget {
  const _Meta(this.icon, this.text);

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 14, color: SsColors.of(context).neutral),
        const SizedBox(width: 5),
        Flexible(
          child: Text(
            text,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
      ],
    );
  }
}

class _DurationChip extends StatelessWidget {
  const _DurationChip(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 2),
      decoration: BoxDecoration(color: SsColors.of(context).selected),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            Icons.timer_outlined,
            size: 13,
            color: SsColors.of(context).primary,
          ),
          const SizedBox(width: 4),
          Text(
            text,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: SsColors.of(context).primaryDark,
              fontWeight: FontWeight.w500,
            ),
          ),
        ],
      ),
    );
  }
}

/// Pulsing placeholder cards shown while the list first loads.
class _SkeletonList extends StatefulWidget {
  const _SkeletonList();

  @override
  State<_SkeletonList> createState() => _SkeletonListState();
}

class _SkeletonListState extends State<_SkeletonList>
    with SingleTickerProviderStateMixin {
  late final _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1100),
  );

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (MediaQuery.disableAnimationsOf(context)) {
      _c.stop();
    } else if (!_c.isAnimating) {
      _c.repeat(reverse: true);
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'در حال بارگذاری جلسه‌ها',
      child: ExcludeSemantics(
        child: ListView.builder(
          physics: const NeverScrollableScrollPhysics(),
          padding: const EdgeInsets.all(12),
          itemCount: 5,
          itemBuilder: (context, _) => FadeTransition(
            opacity: Tween(begin: 0.45, end: 1.0).animate(_c),
            child: Container(
              height: 104,
              margin: const EdgeInsets.only(bottom: 10),
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: SsColors.of(context).canvas,
                border: Border.all(color: SsColors.of(context).line),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _bar(150, 14),
                  const SizedBox(height: 10),
                  _bar(100, 10),
                  const SizedBox(height: 14),
                  _bar(double.infinity, 10),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _bar(double width, double height) => Container(
    width: width,
    height: height,
    decoration: BoxDecoration(color: SsColors.of(context).selected),
  );
}
