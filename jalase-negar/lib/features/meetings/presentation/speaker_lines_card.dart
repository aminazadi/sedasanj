import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/utils/format.dart';
import '../../people/application/people_providers.dart';
import '../application/meeting_providers.dart';
import '../data/meeting.dart';
import '../data/speaker_edit.dart';

/// Speaker-labelled lines (`نام: متن`) with a per-line speaker picker, a split
/// into two speakers and the "precise processing" action. Shown only when at
/// least one line has a speaker.
class SpeakerLinesCard extends ConsumerWidget {
  const SpeakerLinesCard({
    super.key,
    required this.meetingId,
    required this.segments,
    required this.editable,
  });

  final String meetingId;
  final List<Segment> segments;
  final bool editable;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final share = overlapShare(segments);
    return SsCard(
      title: 'گویندگان',
      trailing: share > 0
          ? SsBadge(
              'هم‌زمان ${toPersianDigits('${(share * 100).round()}')}٪',
              color: SsColors.warning,
            )
          : null,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < segments.length; i++)
            if (segments[i].text.trim().isNotEmpty)
              _Line(
                segment: segments[i],
                onTap: editable ? () => _edit(context, ref, i) : null,
              ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            children: [
              OutlinedButton.icon(
                onPressed: () async {
                  await Clipboard.setData(
                    ClipboardData(text: labeledTranscriptText(segments)),
                  );
                  if (context.mounted) {
                    SsToastHost.show(context, 'متن با نام گویندگان کپی شد');
                  }
                },
                icon: const Icon(Icons.copy, size: 18),
                label: const Text('کپی با نام گوینده'),
              ),
              if (editable)
                OutlinedButton.icon(
                  onPressed: () => _precise(context, ref),
                  icon: const Icon(Icons.auto_fix_high, size: 18),
                  label: const Text('پردازش دقیق'),
                ),
            ],
          ),
          if (editable)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                'روی هر خط بزنید تا گوینده‌اش را عوض کنید یا آن را بین دو نفر تقسیم کنید. '
                'انتخاب دستی شما با «پردازش دقیق» عوض نمی‌شود.',
                style: theme.textTheme.bodySmall,
              ),
            ),
        ],
      ),
    );
  }

  Future<void> _precise(BuildContext context, WidgetRef ref) async {
    SsToastHost.show(context, 'پردازش دقیق شروع شد؛ ممکن است چند دقیقه طول بکشد');
    final outcome = await ref
        .read(meetingActionsProvider(meetingId))
        .runPreciseProcessing();
    if (!context.mounted) return;
    SsToastHost.show(
      context,
      switch (outcome.status) {
        PreciseStatus.done =>
          'پردازش دقیق تمام شد؛ ${toPersianDigits('${outcome.changedLines}')} خط تغییر کرد',
        PreciseStatus.needsModels =>
          'مدل‌های «تشخیص گوینده» نصب نیستند؛ از بخش «مدل‌ها» دانلودشان کنید.',
        PreciseStatus.tooLong =>
          'ضبط برای پردازش دقیق روی گوشی بیش از حد طولانی است (حداکثر ۴۰ دقیقه).',
        PreciseStatus.busy => 'تا پایان ضبط یا ارسال جلسه، پردازش دقیق ممکن نیست.',
        PreciseStatus.failed =>
          'پردازش دقیق انجام نشد و چیزی تغییر نکرد؛ دوباره امتحان کنید.',
      },
    );
    if (outcome.status == PreciseStatus.needsModels && context.mounted) {
      context.push('/models');
    }
  }

  Future<void> _edit(BuildContext context, WidgetRef ref, int index) async {
    final people = ref.read(peopleProvider).value ?? const [];
    final choices = <SpeakerChoice>[
      for (final p in people) SpeakerChoice(name: p.name, personId: p.clientId),
      for (final c in speakersIn(segments))
        if (!c.isPerson) c,
    ];
    final action = await showModalBottomSheet<_EditAction>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (context) => _PickerSheet(
        segment: segments[index],
        choices: choices,
      ),
    );
    if (action == null || !context.mounted) return;
    final actions = ref.read(meetingActionsProvider(meetingId));
    switch (action) {
      case _Assign(:final choice, :final all):
        await actions.saveSegments(
          assignSpeaker(segments, index, choice, allWithSameLabel: all),
        );
      case _Split(:final first, :final second):
        final text = segments[index].text;
        final next = splitToTwoSpeakers(
          segments,
          index,
          offset: suggestSplitOffset(text),
          first: first,
          second: second,
        );
        if (identical(next, segments)) {
          if (context.mounted) {
            SsToastHost.show(context, 'این خط برای تقسیم خیلی کوتاه است.');
          }
          return;
        }
        await actions.saveSegments(next);
    }
  }
}

sealed class _EditAction {
  const _EditAction();
}

class _Assign extends _EditAction {
  const _Assign(this.choice, {this.all = false});
  final SpeakerChoice? choice;
  final bool all;
}

class _Split extends _EditAction {
  const _Split(this.first, this.second);
  final SpeakerChoice first;
  final SpeakerChoice second;
}

class _Line extends StatelessWidget {
  const _Line({required this.segment, this.onTap});

  final Segment segment;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final low = !segment.speakerManual &&
        segment.speaker != null &&
        (segment.speakerConfidence ?? 100) < 60;
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 6,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                SsBadge(segment.speakerLabel ?? 'بدون گوینده'),
                if (segment.overlap)
                  const SsBadge('هم‌زمان', color: SsColors.warning),
                if (low)
                  const SsBadge('احتمالاً اشتباه', color: SsColors.warning),
              ],
            ),
            const SizedBox(height: 2),
            Text(segment.text, style: theme.textTheme.bodyMedium),
          ],
        ),
      ),
    );
  }
}

class _PickerSheet extends StatelessWidget {
  const _PickerSheet({required this.segment, required this.choices});

  final Segment segment;
  final List<SpeakerChoice> choices;

  @override
  Widget build(BuildContext context) {
    final current = firstSpeakerOf(segment);
    return SafeArea(
      child: ListView(
        shrinkWrap: true,
        children: [
          const ListTile(title: Text('گوینده‌ی این خط چه کسی است؟')),
          for (final c in choices)
            ListTile(
              leading: Icon(c.isPerson ? Icons.person : Icons.person_outline),
              title: Text(c.name),
              selected: c == current,
              onTap: () => Navigator.pop(context, _Assign(c)),
              trailing: c.isUnknownLabel && c == current
                  ? TextButton(
                      onPressed: () async {
                        final name = await _askName(context);
                        if (name != null && context.mounted) {
                          Navigator.pop(
                            context,
                            _Assign(SpeakerChoice(name: name), all: true),
                          );
                        }
                      },
                      child: const Text('نام‌گذاری همه'),
                    )
                  : null,
            ),
          ListTile(
            leading: const Icon(Icons.person_off_outlined),
            title: const Text('بدون گوینده'),
            onTap: () => Navigator.pop(context, const _Assign(null)),
          ),
          const Divider(),
          ListTile(
            leading: const Icon(Icons.call_split),
            title: const Text('تقسیم بین دو گوینده'),
            subtitle: const Text('متن از وسط (نزدیک‌ترین فاصله) بریده می‌شود.'),
            enabled: segment.text.trim().length >= 2 && choices.length >= 2,
            onTap: () async {
              final pair = await _askPair(context, choices);
              if (pair != null && context.mounted) {
                Navigator.pop(context, _Split(pair.$1, pair.$2));
              }
            },
          ),
        ],
      ),
    );
  }

  Future<String?> _askName(BuildContext context) async {
    final controller = TextEditingController();
    final name = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('نام این گوینده'),
        content: TextField(controller: controller, autofocus: true, maxLength: 80),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('انصراف'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, controller.text.trim()),
            child: const Text('ذخیره'),
          ),
        ],
      ),
    );
    controller.dispose();
    return name == null || name.isEmpty ? null : name;
  }

  Future<(SpeakerChoice, SpeakerChoice)?> _askPair(
    BuildContext context,
    List<SpeakerChoice> choices,
  ) {
    var first = choices.first;
    var second = choices[1];
    return showDialog<(SpeakerChoice, SpeakerChoice)>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setState) => AlertDialog(
          title: const Text('دو گوینده'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              DropdownButton<SpeakerChoice>(
                isExpanded: true,
                value: first,
                items: [
                  for (final c in choices)
                    DropdownMenuItem(value: c, child: Text('اول: ${c.name}')),
                ],
                onChanged: (v) => setState(() => first = v ?? first),
              ),
              DropdownButton<SpeakerChoice>(
                isExpanded: true,
                value: second,
                items: [
                  for (final c in choices)
                    DropdownMenuItem(value: c, child: Text('دوم: ${c.name}')),
                ],
                onChanged: (v) => setState(() => second = v ?? second),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('انصراف'),
            ),
            FilledButton(
              onPressed: first == second
                  ? null
                  : () => Navigator.pop(context, (first, second)),
              child: const Text('تقسیم'),
            ),
          ],
        ),
      ),
    );
  }
}
