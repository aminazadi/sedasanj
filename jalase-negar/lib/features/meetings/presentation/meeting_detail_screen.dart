import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:share_plus/share_plus.dart';

import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
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
