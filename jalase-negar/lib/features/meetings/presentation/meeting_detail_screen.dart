import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:share_plus/share_plus.dart';

import '../../../app/widgets/ss_widgets.dart';
import '../../../core/utils/format.dart';
import '../application/pipeline_controller.dart';
import '../data/meeting.dart';
import 'audio_waveform_player.dart';

/// Shows one recorded meeting and its on-device draft transcript.
/// Analysis (speakers, minutes) is produced by SedaSanj and read in the panel.
class MeetingDetailScreen extends ConsumerWidget {
  const MeetingDetailScreen({super.key, required this.meetingId});

  final String meetingId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final detail = ref.watch(meetingDetailProvider(meetingId));
    final pipeline = ref.watch(pipelineControllerProvider(meetingId));
    final controller = ref.read(pipelineControllerProvider(meetingId).notifier);

    ref.listen(pipelineControllerProvider(meetingId), (previous, next) {
      if (next.error != null && next.error != previous?.error) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(next.error!)));
      }
    });

    return detail.when(
      loading: () =>
          const Scaffold(body: Center(child: CircularProgressIndicator())),
      error: (error, _) => Scaffold(body: Center(child: Text('خطا: $error'))),
      data: (data) {
        if (data == null) {
          return const Scaffold(body: Center(child: Text('جلسه پیدا نشد')));
        }

        final saved = _rawTranscript(data.segments);
        final transcript = pipeline.transcribing
            ? pipeline.liveTranscript
            : saved.isNotEmpty
            ? saved
            : pipeline.liveTranscript;

        return Scaffold(
          appBar: SsAppBar(title: Text(data.meeting.title)),
          bottomNavigationBar: AudioWaveformPlayer(
            path: data.meeting.audioPath,
            title: data.meeting.title,
          ),
          body: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              _TranscriptionHeader(
                meeting: data.meeting,
                hasTranscript: transcript.isNotEmpty,
                transcribing: pipeline.transcribing,
                progress: pipeline.transcribeProgress,
                liveWordCount: pipeline.liveWordCount,
                onTranscribe: controller.transcribeMeeting,
              ),
              const SizedBox(height: 12),
              _TranscriptCard(
                transcript: transcript,
                transcribing: pipeline.transcribing,
                onCopy: transcript.isEmpty
                    ? null
                    : () async {
                        await Clipboard.setData(
                          ClipboardData(text: transcript),
                        );
                        if (!context.mounted) return;
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(content: Text('متن کپی شد')),
                        );
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

class _TranscriptionHeader extends StatelessWidget {
  const _TranscriptionHeader({
    required this.meeting,
    required this.hasTranscript,
    required this.transcribing,
    required this.progress,
    required this.liveWordCount,
    required this.onTranscribe,
  });

  final Meeting meeting;
  final bool hasTranscript;
  final bool transcribing;
  final double progress;
  final int liveWordCount;
  final VoidCallback onTranscribe;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final percent = (progress * 100).round().clamp(0, 100);

    return SsCard(
      title: 'تبدیل صوت به متن',
      trailing: Text(
        formatDuration(meeting.duration),
        style: theme.textTheme.bodySmall,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            transcribing
                ? liveWordCount == 0
                      ? 'شنوا در حال شنیدن و تحلیل فایل است… $percent٪'
                      : 'رونویسی زنده: $liveWordCount کلمه تا این لحظه — $percent٪'
                : hasTranscript
                ? 'رونویسی انجام شد؛ متن زیر خروجی مستقیم صوت است.'
                : 'فایل صوتی آماده است. برای شروع، تبدیل دقیق را اجرا کنید.',
            style: theme.textTheme.bodySmall,
          ),
          if (transcribing) ...[
            const SizedBox(height: 12),
            LinearProgressIndicator(value: progress),
          ] else ...[
            const SizedBox(height: 14),
            Align(
              alignment: AlignmentDirectional.centerStart,
              child: FilledButton.icon(
                onPressed: onTranscribe,
                icon: const Icon(Icons.transcribe),
                label: Text(hasTranscript ? 'رونویسی دوباره' : 'شروع رونویسی'),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _TranscriptCard extends StatelessWidget {
  const _TranscriptCard({
    required this.transcript,
    required this.transcribing,
    required this.onCopy,
    required this.onShare,
  });

  final String transcript;
  final bool transcribing;
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
              transcribing
                  ? 'متن به‌محض آماده شدن اینجا نمایش داده می‌شود…'
                  : 'هنوز متنی وجود ندارد.',
              style: theme.textTheme.bodySmall,
            )
          : SelectableText(transcript, style: theme.textTheme.bodyMedium),
    );
  }
}
