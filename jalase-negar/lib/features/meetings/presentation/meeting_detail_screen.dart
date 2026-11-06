import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/utils/format.dart';
import '../application/meeting_providers.dart';
import '../data/attendee.dart';
import '../data/meeting.dart';
import '../data/transcript_edit.dart';
import 'audio_waveform_player.dart';
import 'share_meeting_audio.dart';
import 'detected_speakers_card.dart';
import 'send_meeting_action.dart';
import 'speaker_lines_card.dart';
import 'transcript_editor.dart';

/// Plays the recording and shows the transcript stored for the meeting.
class MeetingDetailScreen extends ConsumerStatefulWidget {
  const MeetingDetailScreen({super.key, required this.meetingId});

  final String meetingId;

  @override
  ConsumerState<MeetingDetailScreen> createState() =>
      _MeetingDetailScreenState();
}

class _MeetingDetailScreenState extends ConsumerState<MeetingDetailScreen> {
  final _editorKey = GlobalKey<TranscriptEditorState>();
  final _transcriptStatus = ValueNotifier<Widget?>(null);

  @override
  void dispose() {
    _transcriptStatus.dispose();
    super.dispose();
  }

  String get meetingId => widget.meetingId;

  @override
  Widget build(BuildContext context) {
    final detail = ref.watch(meetingDetailProvider(meetingId));

    // An autosave reloads the meeting; keep the editor on screen meanwhile.
    return detail.when(
      skipLoadingOnReload: true,
      loading: () =>
          const Scaffold(body: Center(child: CircularProgressIndicator())),
      error: (error, _) => Scaffold(body: Center(child: Text('خطا: $error'))),
      data: (data) {
        if (data == null) {
          return const Scaffold(body: Center(child: Text('جلسه پیدا نشد')));
        }

        final transcript = transcriptEditorText(data.segments);

        final hasSpeakers = data.segments.any((s) => s.speaker != null);
        final showSpeakers = transcript.isNotEmpty;
        final canSend = canSendMeetingText(
          data.meeting,
          hasText: transcript.isNotEmpty,
        );

        return DefaultTabController(
          length: showSpeakers ? 2 : 1,
          child: Scaffold(
            appBar: SsAppBar(
              actions: [
                if (canSend)
                  IconButton(
                    tooltip: 'ارسال به صداسنج',
                    icon: const Icon(Icons.cloud_upload_outlined),
                    onPressed: () =>
                        sendMeetingToSedasanj(context, ref, meetingId),
                  ),
                if (transcript.isNotEmpty)
                  TranscriptActionsButton(editorKey: _editorKey),
                _MeetingMenu(meeting: data.meeting),
              ],
              title: Hero(
                tag: 'meeting-title-${data.meeting.id}',
                child: Material(
                  type: MaterialType.transparency,
                  child: Text(
                    data.meeting.title,
                    style: Theme.of(context).appBarTheme.titleTextStyle,
                  ),
                ),
              ),
              bottom: showSpeakers
                  ? const TabBar(
                      tabs: [
                        Tab(text: 'متن جلسه'),
                        Tab(text: 'گوینده‌ها'),
                      ],
                    )
                  : null,
            ),
            // Hidden (not disposed) while the keyboard is up so editing keeps
            // the whole screen and the playback position survives.
            bottomNavigationBar: Visibility(
              visible: MediaQuery.viewInsetsOf(context).bottom == 0,
              maintainState: true,
              child: Builder(
                builder: (context) => AnimatedBuilder(
                  animation: DefaultTabController.of(context),
                  builder: (context, _) => Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (showSpeakers &&
                          DefaultTabController.of(context).index == 0)
                        ValueListenableBuilder<Widget?>(
                          valueListenable: _transcriptStatus,
                          builder: (context, status, _) =>
                              status ?? const SizedBox.shrink(),
                        ),
                      AudioWaveformPlayer(path: data.meeting.audioPath),
                    ],
                  ),
                ),
              ),
            ),
            body: showSpeakers
                ? TabBarView(
                    children: [
                      _transcriptTab(context, ref, data, transcript),
                      _speakersTab(context, ref, data, transcript, hasSpeakers),
                    ],
                  )
                : _transcriptTab(context, ref, data, transcript),
          ),
        );
      },
    );
  }

  Widget _speakersTab(
    BuildContext context,
    WidgetRef ref,
    MeetingDetail data,
    String transcript,
    bool hasSpeakers,
  ) {
    final locked = data.meeting.status == MeetingStatus.uploading;
    if (data.meeting.analyzingSpeakers) {
      return Center(child: _AnalyzingBanner(meetingId: meetingId, large: true));
    }
    if (!hasSpeakers) {
      return SsEmptyState(
        title: 'گوینده‌ها هنوز استخراج نشده‌اند',
        hint: 'با تحلیل صدای جلسه، گوینده‌ی هر خط مشخص می‌شود.',
        action: FilledButton.icon(
          icon: const Icon(Icons.record_voice_over_outlined, size: 18),
          label: const Text('استخراج گوینده‌ها'),
          onPressed: locked
              ? null
              : () => runPreciseWithToast(context, ref, meetingId),
        ),
      );
    }
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        if (transcript.isNotEmpty && !locked) ...[
          DetectedSpeakersCard(meetingId: meetingId, segments: data.segments),
          const SizedBox(height: 12),
        ],
        SpeakerLinesCard(
          meetingId: meetingId,
          segments: data.segments,
          editable: !locked,
        ),
      ],
    );
  }

  Widget _transcriptTab(
    BuildContext context,
    WidgetRef ref,
    MeetingDetail data,
    String transcript,
  ) {
    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      children: [
        if (data.meeting.analyzingSpeakers) ...[
          _AnalyzingBanner(meetingId: meetingId),
          const SizedBox(height: 12),
        ],
        _AttendeesSection(meetingId: meetingId),
        if (transcript.isEmpty)
          const _EmptyTranscriptCard()
        else
          TranscriptEditor(
            key: _editorKey,
            statusDestination: _transcriptStatus,
            savedText: transcript,
            readOnly: data.meeting.status == MeetingStatus.uploading,
            notice: _editNotice(data.meeting),
            noticeActionLabel: data.meeting.textSyncPending
                ? 'ارسال دوباره به صداسنج'
                : null,
            onNoticeAction: () => _retrySync(context, ref),
            onSave: (text, {required settle}) => ref
                .read(meetingActionsProvider(meetingId))
                .saveTranscript(text, settle: settle),
          ),
      ],
    );
  }

  Future<void> _retrySync(BuildContext context, WidgetRef ref) async {
    final save = await ref
        .read(meetingActionsProvider(meetingId))
        .retryTextSync();
    if (!context.mounted) return;
    SsToastHost.show(
      context,
      save.result == TranscriptSaveResult.synced
          ? 'ویرایش برای صداسنج ارسال شد'
          : 'ارسال نشد؛ ${save.problem ?? 'دوباره امتحان کنید'}',
    );
  }

  /// What the user should know before editing text SedaSanj may hold.
  String? _editNotice(Meeting meeting) {
    if (meeting.status == MeetingStatus.uploading) {
      return 'متن در حال ارسال به صداسنج است؛ پس از پایان ارسال می‌توانید آن را ویرایش کنید.';
    }
    if (!isTextSentToServer(meeting)) return null;
    if (meeting.textSyncPending) {
      return 'ویرایش‌های ذخیره‌شدهٔ این جلسه هنوز به صداسنج نرسیده‌اند؛ متن و '
          'صورت‌جلسهٔ پنل تا ارسال، همان نسخهٔ قبلی است.';
    }
    return 'این متن پیش‌تر برای صداسنج ارسال شده است؛ با توقف ویرایش یا خروج از '
        'صفحه، متن پنل به‌روز و صورت‌جلسه دوباره ساخته می‌شود.';
  }
}

/// Dropdown at the end of the app bar, opposite the title: rename or delete.
class _MeetingMenu extends ConsumerWidget {
  const _MeetingMenu({required this.meeting});

  final Meeting meeting;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    PopupMenuItem<String> item(
      String value,
      IconData icon,
      String label, {
      Color? color,
    }) => PopupMenuItem<String>(
      value: value,
      child: Row(
        children: [
          Icon(icon, size: 18, color: color ?? SsColors.ink),
          const SizedBox(width: 10),
          Flexible(
            child: Text(label, style: TextStyle(color: color)),
          ),
        ],
      ),
    );

    return PopupMenuButton<String>(
      icon: const Icon(Icons.more_vert),
      tooltip: 'گزینه‌ها',
      color: Colors.white,
      shape: RoundedRectangleBorder(
        side: const BorderSide(color: SsColors.line),
      ),
      position: PopupMenuPosition.under,
      onSelected: (value) => switch (value) {
        'rename' => _rename(context, ref),
        'share' => shareMeetingAudio(context, meeting),
        _ => _confirmDelete(context, ref),
      },
      itemBuilder: (context) => [
        item('rename', Icons.edit_outlined, 'ویرایش عنوان'),
        item('share', Icons.ios_share, 'اشتراک‌گذاری فایل صوتی'),
        item(
          'delete',
          Icons.delete_outline,
          'حذف جلسه',
          color: SsColors.danger,
        ),
      ],
    );
  }

  Future<void> _rename(BuildContext context, WidgetRef ref) async {
    final title = await showDialog<String>(
      context: context,
      builder: (context) =>
          _RenameDialog(initial: displayMeetingTitle(meeting.title)),
    );
    if (title == null) return;
    await ref.read(meetingActionsProvider(meeting.id)).renameMeeting(title);
  }

  Future<void> _confirmDelete(BuildContext context, WidgetRef ref) async {
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
    if (confirmed != true) return;
    // Leave the screen first so it never rebuilds for a meeting that is gone.
    if (context.mounted && context.canPop()) context.pop();
    await ref.read(meetingActionsProvider(meeting.id)).deleteMeeting();
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
      title: const Text('ویرایش عنوان جلسه'),
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

/// The app's loading mark with one line: speakers are being identified.
class _AnalyzingBanner extends ConsumerWidget {
  const _AnalyzingBanner({required this.meetingId, this.large = false});

  final String meetingId;

  final bool large;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final progress = ref.watch(speakerProgressProvider)[meetingId] ?? 0;
    final text = Text(
      'در حال استخراج گوینده‌ها (${toPersianDigits("$progress")}٪)؛ پس از پایان، جلسه برای صداسنج ارسال می‌شود.',
      textAlign: TextAlign.center,
      style: Theme.of(context).textTheme.bodySmall,
    );
    if (large) {
      return Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SsProcessingMark(size: 36),
            const SizedBox(height: 12),
            text,
          ],
        ),
      );
    }
    return Row(
      children: [
        const SsProcessingMark(size: 16),
        const SizedBox(width: 10),
        Expanded(child: text),
      ],
    );
  }
}

class _EmptyTranscriptCard extends StatelessWidget {
  const _EmptyTranscriptCard();

  @override
  Widget build(BuildContext context) {
    return Text(
      'برای این جلسه متنی ذخیره نشده است. می‌توانید فایل صوتی را پخش کنید.',
      style: Theme.of(context).textTheme.bodySmall,
    );
  }
}

/// Who was present, as chosen before recording. Hidden when nobody was.
class _AttendeesSection extends ConsumerWidget {
  const _AttendeesSection({required this.meetingId});

  final String meetingId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final attendees =
        ref.watch(meetingAttendeesProvider(meetingId)).value ??
        const <Attendee>[];
    if (attendees.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: SsCard(
        title: 'حاضران جلسه',
        child: Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [for (final a in attendees) Chip(label: Text(a.name))],
        ),
      ),
    );
  }
}
