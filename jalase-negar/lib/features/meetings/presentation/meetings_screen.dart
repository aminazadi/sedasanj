import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/providers.dart';
import '../../../core/utils/format.dart';
import '../../recording/application/recorder_controller.dart';
import '../../upload/upload_controller.dart';
import '../application/meeting_providers.dart';
import '../data/meeting.dart';
import '../data/meeting_repository.dart' show foldPersianLetters;
import 'send_meeting_action.dart';
import 'share_meeting_audio.dart';

enum _Filter {
  all('همه'),
  active('در حال پردازش'),
  complete('کامل'),
  failed('ناموفق');

  const _Filter(this.label);

  final String label;

  bool accepts(Meeting m) => switch (this) {
    _Filter.all => true,
    _Filter.active =>
      m.status != MeetingStatus.complete && m.status != MeetingStatus.failed,
    _Filter.complete => m.status == MeetingStatus.complete,
    _Filter.failed => m.status == MeetingStatus.failed,
  };
}

bool _matchesQuery(Meeting m, String query, Set<String> textMatches) {
  if (query.trim().isEmpty) return true;
  final q = toPersianDigits(foldPersianLetters(query.trim()));
  return displayMeetingTitle(m.title).contains(q) ||
      formatJalaliDay(m.createdAt).contains(q) ||
      textMatches.contains(m.id);
}

class MeetingsScreen extends ConsumerStatefulWidget {
  const MeetingsScreen({super.key});

  @override
  ConsumerState<MeetingsScreen> createState() => _MeetingsScreenState();
}

class _MeetingsScreenState extends ConsumerState<MeetingsScreen> {
  final _search = TextEditingController();
  var _query = '';
  // The transcript lookup follows the typing after a short pause.
  var _textQuery = '';
  Timer? _debounce;
  var _filter = _Filter.all;

  void _onQuery(String v) {
    setState(() => _query = v);
    _debounce?.cancel();
    if (v.trim().isEmpty) {
      setState(() => _textQuery = '');
      return;
    }
    _debounce = Timer(const Duration(milliseconds: 250), () {
      if (mounted) setState(() => _textQuery = v);
    });
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final hidden = ref.watch(pendingDeletesProvider);
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
                  _filter.accepts(m) &&
                  _matchesQuery(m, _query, textMatches),
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
          SliverToBoxAdapter(
            child: _SearchAndFilters(
              controller: _search,
              filter: _filter,
              onQuery: _onQuery,
              onFilter: (f) => setState(() => _filter = f),
            ),
          ),
          if (ids.isEmpty)
            SliverFillRemaining(
              hasScrollBody: false,
              child: _NoResults(
                onClear: () => setState(() {
                  _search.clear();
                  _query = '';
                  _textQuery = '';
                  _filter = _Filter.all;
                }),
              ),
            )
          else
            for (final (label, groupIds) in groups)
              SliverMainAxisGroup(
                slivers: [
                  SliverPersistentHeader(
                    pinned: true,
                    delegate: _GroupHeaderDelegate(label, groupIds.length),
                  ),
                  SliverPadding(
                    padding: const EdgeInsets.fromLTRB(12, 2, 12, 4),
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

class _GroupHeaderDelegate extends SliverPersistentHeaderDelegate {
  const _GroupHeaderDelegate(this.label, this.count);

  final String label;
  final int count;

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
      color: SsColors.canvas,
      padding: const EdgeInsets.symmetric(horizontal: 16),
      alignment: AlignmentDirectional.centerStart,
      child: Row(
        children: [
          Text(
            label,
            style: theme.textTheme.labelLarge?.copyWith(
              color: SsColors.primaryDark,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(width: 8),
          Text(toPersianDigits('$count'), style: theme.textTheme.labelSmall),
          const SizedBox(width: 10),
          const Expanded(child: Divider()),
        ],
      ),
    );
  }

  @override
  bool shouldRebuild(_GroupHeaderDelegate old) =>
      old.label != label || old.count != count;
}

class _SearchAndFilters extends StatelessWidget {
  const _SearchAndFilters({
    required this.controller,
    required this.filter,
    required this.onQuery,
    required this.onFilter,
  });

  final TextEditingController controller;
  final _Filter filter;
  final ValueChanged<String> onQuery;
  final ValueChanged<_Filter> onFilter;

  @override
  Widget build(BuildContext context) {
    OutlineInputBorder border(Color c) => OutlineInputBorder(
      borderRadius: BorderRadius.zero,
      borderSide: BorderSide(color: c),
    );
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 4, 12, 10),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(
              child: ValueListenableBuilder<TextEditingValue>(
                valueListenable: controller,
                builder: (context, value, _) => TextField(
                  controller: controller,
                  onChanged: onQuery,
                  textInputAction: TextInputAction.search,
                  decoration: InputDecoration(
                    hintText: 'جست‌وجو در عنوان، تاریخ و متن جلسه',
                    filled: true,
                    fillColor: Colors.white,
                    isDense: true,
                    contentPadding: const EdgeInsets.symmetric(vertical: 12),
                    prefixIcon: const Icon(
                      Icons.search,
                      color: SsColors.neutral,
                    ),
                    suffixIcon: value.text.isEmpty
                        ? null
                        : IconButton(
                            tooltip: 'پاک کردن',
                            icon: const Icon(Icons.close, size: 18),
                            onPressed: () {
                              controller.clear();
                              onQuery('');
                            },
                          ),
                    border: border(SsColors.line),
                    enabledBorder: border(SsColors.line),
                    focusedBorder: border(SsColors.primary),
                  ),
                ),
              ),
            ),
            const SizedBox(width: 8),
            _FilterMenu(filter: filter, onFilter: onFilter),
          ],
        ),
      ),
    );
  }
}

/// Icon button beside the search field; opens the status filters as a dropdown.
class _FilterMenu extends StatelessWidget {
  const _FilterMenu({required this.filter, required this.onFilter});

  final _Filter filter;
  final ValueChanged<_Filter> onFilter;

  @override
  Widget build(BuildContext context) {
    final active = filter != _Filter.all;
    return PopupMenuButton<_Filter>(
      tooltip: 'فیلتر جلسه‌ها',
      position: PopupMenuPosition.under,
      color: Colors.white,
      shape: const RoundedRectangleBorder(
        side: BorderSide(color: SsColors.line),
      ),
      initialValue: filter,
      onSelected: onFilter,
      itemBuilder: (context) => [
        for (final f in _Filter.values)
          PopupMenuItem(
            value: f,
            height: 40,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  f == filter ? Icons.check : null,
                  size: 18,
                  color: SsColors.primary,
                ),
                const SizedBox(width: 10),
                Text(f.label, style: Theme.of(context).textTheme.labelMedium),
              ],
            ),
          ),
      ],
      child: Semantics(
        button: true,
        label: active ? 'فیلتر: ${filter.label}' : 'فیلتر جلسه‌ها',
        child: Container(
          width: 46,
          decoration: BoxDecoration(
            color: active ? SsColors.primary : Colors.white,
            border: Border.all(
              color: active ? SsColors.primary : SsColors.line,
            ),
          ),
          child: Icon(
            Icons.filter_list,
            color: active ? SsColors.canvas : SsColors.neutral,
          ),
        ),
      ),
    );
  }
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
          const Icon(Icons.search_off, size: 44, color: SsColors.accent),
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
    final notice = needsReconnect
        ? 'توکن ابطال شده است؛ از «تنظیمات» دوباره به صداسنج متصل شوید.'
        : creditExhausted
        ? 'اعتبار سازمان تمام شده است؛ در پنل صداسنج شارژ کنید تا ارسال ادامه یابد.'
        : null;
    if (notice == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 4, 12, 8),
      child: _QueueNotice(notice),
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
      color: Colors.white,
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
                if (canSendMeetingText(meeting, hasText: preview.isNotEmpty))
                  SizedBox(
                    width: 36,
                    height: 36,
                    child: IconButton(
                      padding: EdgeInsets.zero,
                      iconSize: 20,
                      tooltip: 'ارسال به صداسنج',
                      icon: const Icon(
                        Icons.cloud_upload_outlined,
                        color: SsColors.primary,
                      ),
                      onPressed: () =>
                          sendMeetingToSedasanj(context, ref, meeting.id),
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
                    color: SsColors.ink.withValues(alpha: 0.8),
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
    }) => PopupMenuItem(
      value: value,
      height: 40,
      padding: const EdgeInsets.symmetric(horizontal: 14),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 18, color: color ?? SsColors.ink),
          const SizedBox(width: 10),
          Flexible(child: Text(label, style: style(color))),
        ],
      ),
    );

    return SizedBox(
      width: 36,
      height: 36,
      child: PopupMenuButton<String>(
        padding: EdgeInsets.zero,
        iconSize: 20,
        icon: const Icon(Icons.more_vert, color: SsColors.neutral),
        tooltip: 'گزینه‌ها',
        color: Colors.white,
        shape: RoundedRectangleBorder(
          side: const BorderSide(color: SsColors.line),
        ),
        constraints: const BoxConstraints(minWidth: 0),
        position: PopupMenuPosition.under,
        onSelected: (value) => switch (value) {
          'rename' => _rename(context, ref, meeting),
          'share' => shareMeetingAudio(context, meeting),
          _ => _confirmDelete(context, ref, meeting),
        },
        itemBuilder: (context) => [
          item('rename', Icons.edit_outlined, 'تغییر نام'),
          item('share', Icons.ios_share, 'اشتراک‌گذاری فایل صوتی'),
          item(
            'delete',
            Icons.delete_outline,
            'حذف جلسه',
            color: SsColors.danger,
          ),
        ],
      ),
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
    : color = SsColors.primary,
      icon = Icons.edit_outlined,
      label = 'تغییر نام',
      alignment = AlignmentDirectional.centerStart;

  const _SwipeBackground.delete()
    : color = SsColors.danger,
      icon = Icons.delete_outline,
      label = 'حذف',
      alignment = AlignmentDirectional.centerEnd;

  final Color color;
  final IconData icon;
  final String label;
  final AlignmentDirectional alignment;

  @override
  Widget build(BuildContext context) {
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
              fontFamily: 'Vazirmatn',
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
            ? SsColors.danger
            : SsColors.neutral,
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
            style: Theme.of(
              context,
            ).textTheme.labelMedium?.copyWith(color: SsColors.primaryDark),
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
          const Icon(Icons.error_outline, size: 18, color: SsColors.danger),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(
                context,
              ).textTheme.labelSmall?.copyWith(color: SsColors.danger),
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
        Icon(icon, size: 14, color: SsColors.neutral),
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
      decoration: BoxDecoration(color: SsColors.selected),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.timer_outlined, size: 13, color: SsColors.primary),
          const SizedBox(width: 4),
          Text(
            text,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: SsColors.primaryDark,
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
                color: Colors.white,
                border: Border.all(color: SsColors.line),
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
    decoration: BoxDecoration(color: SsColors.selected),
  );
}
