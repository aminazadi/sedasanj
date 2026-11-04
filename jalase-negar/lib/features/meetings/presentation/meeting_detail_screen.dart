import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:share_plus/share_plus.dart';

import '../../../app/widgets/ss_toast.dart';
import '../../../app/theme.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/utils/format.dart';
import '../application/meeting_providers.dart';
import '../data/meeting.dart';
import 'audio_waveform_player.dart';

/// Plays the recording and shows the transcript stored for the meeting.
class MeetingDetailScreen extends ConsumerWidget {
  const MeetingDetailScreen({super.key, required this.meetingId});

  final String meetingId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final detail = ref.watch(meetingDetailProvider(meetingId));

    return detail.when(
      loading: () =>
          const Scaffold(body: Center(child: CircularProgressIndicator())),
      error: (error, _) => Scaffold(body: Center(child: Text('خطا: $error'))),
      data: (data) {
        if (data == null) {
          return const Scaffold(body: Center(child: Text('جلسه پیدا نشد')));
        }

        final transcript = _rawTranscript(data.segments);

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
          bottomNavigationBar: AudioWaveformPlayer(
            path: data.meeting.audioPath,
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
              _TranscriptCard(
                transcript: transcript,
                onCopy: transcript.isEmpty
                    ? null
                    : () async {
                        await Clipboard.setData(
                          ClipboardData(text: transcript),
                        );
                        if (!context.mounted) return;
                        SsToastHost.show(context, 'متن کپی شد');
                      },
                onShare: transcript.isEmpty
                    ? null
                    : () => SharePlus.instance.share(
                        ShareParams(text: transcript),
                      ),
              ),
            ],
          ),
        );
      },
    );
  }

  String _rawTranscript(List<Segment> segments) {
    final sorted = [...segments]
      ..sort((a, b) {
        final byTime = a.startMs.compareTo(b.startMs);
        return byTime != 0 ? byTime : a.channel.compareTo(b.channel);
      });
    return sorted
        .map((segment) => segment.text.trim())
        .where((text) => text.isNotEmpty)
        .join('\n');
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
          Text(label, style: TextStyle(color: color)),
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
      onSelected: (value) => value == 'rename'
          ? _rename(context, ref)
          : _confirmDelete(context, ref),
      itemBuilder: (context) => [
        item('rename', Icons.edit_outlined, 'ویرایش عنوان'),
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

class _TranscriptCard extends StatelessWidget {
  const _TranscriptCard({
    required this.transcript,
    required this.onCopy,
    required this.onShare,
  });

  final String transcript;
  final VoidCallback? onCopy;
  final VoidCallback? onShare;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SsCard(
      title: 'متن جلسه',
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          IconButton(
            tooltip: 'کپی',
            visualDensity: VisualDensity.compact,
            onPressed: onCopy,
            icon: const Icon(Icons.copy, size: 20),
          ),
          IconButton(
            tooltip: 'اشتراک‌گذاری',
            visualDensity: VisualDensity.compact,
            onPressed: onShare,
            icon: const Icon(Icons.ios_share, size: 20),
          ),
        ],
      ),
      child: transcript.isEmpty
          ? Text(
              'برای این جلسه متنی ذخیره نشده است. می‌توانید فایل صوتی را پخش کنید.',
              style: theme.textTheme.bodySmall,
            )
          : SelectableText(transcript, style: theme.textTheme.bodyMedium),
    );
  }
}
