import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/utils/format.dart';
import '../../people/data/person.dart';
import '../application/meeting_providers.dart';
import '../data/meeting.dart';
import '../data/speaker_discovery.dart';
import 'speaker_lines_card.dart';

/// Voices the app heard in this meeting that nobody enrolled. Each one can be
/// named in one step: it becomes a person with a voiceprint made from this
/// meeting, so the next meeting names them by itself.
class DetectedSpeakersCard extends ConsumerWidget {
  const DetectedSpeakersCard({
    super.key,
    required this.meetingId,
    required this.segments,
  });

  final String meetingId;
  final List<Segment> segments;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final detected = detectUnnamedSpeakers(segments);
    return SsCard(
      title: 'گویندگان این جلسه',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (detected.isEmpty)
            Text(
              'اپ می‌تواند صدای همه‌ی حاضران را از هم جدا کند (مثلاً ۴ یا ۵ نفر) '
              'و هر کدام را «ناشناس ۱»، «ناشناس ۲»، … بنامد؛ بعد فقط نامشان را بنویسید.',
              style: theme.textTheme.bodySmall,
            )
          else ...[
            Text(
              '${toPersianDigits('${detected.length}')} صدای ناشناس پیدا شد. '
              'نام هر کدام را بنویسید تا به «افراد» اضافه شود و در جلسه‌های بعد '
              'خودکار شناخته شود.',
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: 8),
            for (final d in detected)
              _DetectedTile(speaker: d, onName: () => _name(context, ref, d)),
          ],
          const SizedBox(height: 8),
          Align(
            alignment: AlignmentDirectional.centerStart,
            child: OutlinedButton.icon(
              onPressed: () => runPreciseWithToast(context, ref, meetingId),
              icon: const Icon(Icons.groups_outlined, size: 18),
              label: Text(
                detected.isEmpty ? 'تشخیص خودکار گویندگان' : 'تشخیص دوباره',
              ),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _name(
    BuildContext context,
    WidgetRef ref,
    DetectedSpeaker speaker,
  ) async {
    final name = await showDialog<String>(
      context: context,
      builder: (context) => _NameDialog(speaker: speaker),
    );
    if (name == null || !context.mounted) return;
    final status = await ref
        .read(meetingActionsProvider(meetingId))
        .nameDetectedSpeaker(
          label: speaker.label,
          name: name,
          visibility: PersonVisibility.private,
          consentGiven: true,
        );
    if (!context.mounted) return;
    SsToastHost.show(context, switch (status) {
      NameSpeakerStatus.done =>
        '«$name» به افراد اضافه شد و خط‌هایش نام‌گذاری شد',
      NameSpeakerStatus.needsModels =>
        'مدل «تشخیص گوینده» نصب نیست؛ از بخش «مدل‌ها» دانلودش کنید.',
      NameSpeakerStatus.tooShort =>
        'از این صدا گفتار کافی نیست؛ جلسه‌ی دیگری با صحبت بیشتر یا ثبت دستی صدا را امتحان کنید.',
      NameSpeakerStatus.busy =>
        'تا پایان ضبط یا ارسال جلسه، نام‌گذاری ممکن نیست.',
      NameSpeakerStatus.failed => 'نام‌گذاری انجام نشد؛ دوباره امتحان کنید.',
    });
    if (status == NameSpeakerStatus.needsModels && context.mounted) {
      context.push('/models');
    }
  }
}

class _DetectedTile extends StatelessWidget {
  const _DetectedTile({required this.speaker, required this.onName});

  final DetectedSpeaker speaker;
  final VoidCallback onName;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final seconds = (speaker.speechMs / 1000).round();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Wrap(
                  spacing: 6,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    SsBadge(speaker.label),
                    Text(
                      '${toPersianDigits('${speaker.lineCount}')} خط · '
                      '${toPersianDigits('$seconds')} ثانیه',
                      style: theme.textTheme.bodySmall,
                    ),
                    if (!speaker.usable)
                      const SsBadge('گفتار کم', color: SsColors.warning),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  speaker.sampleText,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodyMedium,
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          FilledButton(
            onPressed: speaker.usable ? onName : null,
            child: const Text('نام‌گذاری'),
          ),
        ],
      ),
    );
  }
}

class _NameDialog extends StatefulWidget {
  const _NameDialog({required this.speaker});

  final DetectedSpeaker speaker;

  @override
  State<_NameDialog> createState() => _NameDialogState();
}

class _NameDialogState extends State<_NameDialog> {
  final _controller = TextEditingController();
  bool _agreed = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final ready = _agreed && _controller.text.trim().isNotEmpty;
    return AlertDialog(
      title: Text('نام ${widget.speaker.label}'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            '«${widget.speaker.sampleText}»',
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.bodySmall,
          ),
          TextField(
            controller: _controller,
            autofocus: true,
            maxLength: 80,
            decoration: const InputDecoration(labelText: 'نام فرد'),
            onChanged: (_) => setState(() {}),
          ),
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            controlAffinity: ListTileControlAffinity.leading,
            value: _agreed,
            onChanged: (v) => setState(() => _agreed = v ?? false),
            title: const Text(
              'این فرد با نگه‌داشتن ردصدایش روی این گوشی (و صداسنج در صورت اتصال) موافق است.',
              style: TextStyle(fontSize: 13),
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('انصراف'),
        ),
        FilledButton(
          onPressed: ready
              ? () => Navigator.pop(context, _controller.text.trim())
              : null,
          child: const Text('افزودن به افراد'),
        ),
      ],
    );
  }
}
