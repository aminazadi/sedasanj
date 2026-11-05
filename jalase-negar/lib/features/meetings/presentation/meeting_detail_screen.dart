import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/utils/format.dart';
import '../application/meeting_providers.dart';
import '../data/meeting.dart';
import '../data/transcript_edit.dart';
import 'audio_waveform_player.dart';
import 'share_meeting_audio.dart';
import 'speaker_lines_card.dart';
import 'transcript_editor.dart';

/// Plays the recording and shows the transcript stored for the meeting.
class MeetingDetailScreen extends ConsumerWidget {
  const MeetingDetailScreen({super.key, required this.meetingId});

  final String meetingId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
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

        return Scaffold(
          appBar: SsAppBar(
            actions: [_MeetingMenu(meeting: data.meeting)],
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
          ),
          // Hidden (not disposed) while the keyboard is up so editing keeps
          // the whole screen and the playback position survives.
          bottomNavigationBar: Visibility(
            visible: MediaQuery.viewInsetsOf(context).bottom == 0,
            maintainState: true,
            child: AudioWaveformPlayer(path: data.meeting.audioPath),
          ),
          body: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (transcript.isNotEmpty &&
                  (!data.meeting.sendText ||
                      data.meeting.status == MeetingStatus.failed)) ...[
                _SendTextCard(
                  failed: data.meeting.status == MeetingStatus.failed,
                  onSend: () =>
                      ref.read(meetingActionsProvider(meetingId)).sendText(),
                ),
                const SizedBox(height: 12),
              ],
              if (data.segments.any((s) => s.speaker != null)) ...[
                SpeakerLinesCard(
                  meetingId: meetingId,
                  segments: data.segments,
                  editable: data.meeting.status != MeetingStatus.uploading,
                ),
                const SizedBox(height: 12),
              ],
              if (transcript.isEmpty)
                const _EmptyTranscriptCard()
              else
                TranscriptEditor(
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
          ),
        );
      },
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
          Flexible(child: Text(label, style: TextStyle(color: color))),
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

/// Offers to send a meeting's text that was not sent (switch off, or a send
/// that failed). The audio is stored for playback and never transcribed.
class _SendTextCard extends StatelessWidget {
  const _SendTextCard({required this.failed, required this.onSend});

  final bool failed;
  final VoidCallback onSend;

  @override
  Widget build(BuildContext context) {
    return SsCard(
      title: failed ? 'ارسال متن ناموفق بود' : 'متن این جلسه ارسال نشده است',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'متن و صدای جلسه به صداسنج فرستاده می‌شود؛ صورت‌جلسه فقط از روی متن ساخته می‌شود.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 8),
          FilledButton.icon(
            icon: const Icon(Icons.cloud_upload_outlined),
            label: const Text('ارسال متن این جلسه'),
            onPressed: onSend,
          ),
        ],
      ),
    );
  }
}

class _EmptyTranscriptCard extends StatelessWidget {
  const _EmptyTranscriptCard();

  @override
  Widget build(BuildContext context) {
    return SsCard(
      title: 'متن جلسه',
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: const [
          IconButton(
            tooltip: 'کپی',
            visualDensity: VisualDensity.compact,
            onPressed: null,
            icon: Icon(Icons.copy, size: 20),
          ),
          IconButton(
            tooltip: 'اشتراک‌گذاری',
            visualDensity: VisualDensity.compact,
            onPressed: null,
            icon: Icon(Icons.ios_share, size: 20),
          ),
        ],
      ),
      child: Text(
        'برای این جلسه متنی ذخیره نشده است. می‌توانید فایل صوتی را پخش کنید.',
        style: Theme.of(context).textTheme.bodySmall,
      ),
    );
  }
}
