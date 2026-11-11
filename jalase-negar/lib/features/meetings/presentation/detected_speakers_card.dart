import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/utils/format.dart';
import '../../people/data/person.dart';
import '../../people/application/people_providers.dart';
import '../application/meeting_providers.dart';
import '../data/meeting.dart';
import '../data/speaker_discovery.dart';
import 'audio_waveform_player.dart';

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
    if (detected.isEmpty) return const SizedBox.shrink();
    return SsCard(
      title: 'نام‌گذاری صداهای ناشناس',
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'نام هر صدا را بنویسید تا در جلسه‌های بعد خودکار شناخته شود.',
            style: theme.textTheme.bodySmall,
          ),
          const SizedBox(height: 4),
          for (var i = 0; i < detected.length; i++) ...[
            if (i > 0) const SizedBox(height: 8),
            _DetectedTile(
              speaker: detected[i],
              samples: unnamedSpeakerSampleLines(segments, detected[i].label),
              onName: () => _name(context, ref, detected[i]),
            ),
          ],
        ],
      ),
    );
  }

  Future<void> _name(
    BuildContext context,
    WidgetRef ref,
    DetectedSpeaker speaker,
  ) async {
    final people = ref.read(peopleProvider).value ?? const <Person>[];
    final result = await showDialog<_NameResult>(
      context: context,
      builder: (context) => _NameDialog(speaker: speaker, people: people),
    );
    if (result == null || !context.mounted) return;
    final name = result.person?.name ?? result.newName ?? '';
    final status = await ref
        .read(meetingActionsProvider(meetingId))
        .nameDetectedSpeaker(
          label: speaker.label,
          name: name,
          visibility: PersonVisibility.private,
          consentGiven: true,
          existingPerson: result.person,
          addVoiceprints: result.addVoiceprints,
        );
    if (!context.mounted) return;
    SsToastHost.show(context, switch (status) {
      NameSpeakerStatus.done when result.person != null =>
        'خط‌های ${speaker.label} به «$name» نسبت داده شد',
      NameSpeakerStatus.done =>
        '«$name» به افراد اضافه شد و خط‌هایش نام‌گذاری شد',
      NameSpeakerStatus.assignedWithoutVoiceprint =>
        'خط‌های ${speaker.label} به «$name» نسبت داده شد؛ ردصدا اضافه نشد (گفتار کافی نبود). بعداً از صفحهٔ فرد می‌توانید ردصدا اضافه کنید.',
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

class _DetectedTile extends StatefulWidget {
  const _DetectedTile({
    required this.speaker,
    required this.samples,
    required this.onName,
  });

  final DetectedSpeaker speaker;
  final List<SpeakerSample> samples;
  final VoidCallback onName;

  @override
  State<_DetectedTile> createState() => _DetectedTileState();
}

class _DetectedTileState extends State<_DetectedTile> {
  static const _maxChips = 6;
  int _selected = 0;

  List<SpeakerSample> get _samples => widget.samples.length > _maxChips
      ? widget.samples.sublist(0, _maxChips)
      : widget.samples;

  bool _isPlaying(SpeakerSample sample) {
    final playing = playingSpan.value;
    return playing != null &&
        playing.startMs == sample.startMs &&
        playing.endMs == sample.endMs;
  }

  void _play(SpeakerSample sample) {
    spanPlayRequests.value = SpanPlayRequest(sample.startMs, sample.endMs);
  }

  /// The big button plays the chosen sample, or pauses it while it plays.
  void _toggle() {
    final sample = _samples[_selected];
    if (_isPlaying(sample)) {
      spanPauseRequests.value++;
    } else {
      _play(sample);
    }
  }

  /// A number chooses that sample and plays it at once.
  void _choose(int index) {
    setState(() => _selected = index);
    _play(_samples[index]);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final speaker = widget.speaker;
    final seconds = (speaker.speechMs / 1000).round();
    final samples = _samples;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  '${speaker.label} · ${toPersianDigits('$seconds')} ثانیه'
                  '${speaker.usable ? '' : ' · گفتار کم'}',
                  style: theme.textTheme.labelMedium,
                ),
              ),
              TextButton(
                onPressed: widget.onName,
                style: TextButton.styleFrom(
                  visualDensity: VisualDensity.compact,
                ),
                child: const Text('نام‌گذاری'),
              ),
            ],
          ),
          if (samples.isEmpty)
            Text(
              'برای این صدا نمونهٔ قابل‌پخش پیدا نشد.',
              style: theme.textTheme.bodySmall,
            )
          else
            ValueListenableBuilder<SpanPlayRequest?>(
              valueListenable: playingSpan,
              builder: (context, _, _) => _buildPlayer(theme, samples),
            ),
        ],
      ),
    );
  }

  Widget _buildPlayer(ThemeData theme, List<SpeakerSample> samples) {
    final sample = samples[_selected];
    final playing = _isPlaying(sample);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 36,
              height: 36,
              child: IconButton.filled(
                tooltip: playing ? 'توقف' : 'پخش نمونه',
                padding: EdgeInsets.zero,
                style: IconButton.styleFrom(
                  backgroundColor: SsColors.primary,
                  foregroundColor: SsColors.canvas,
                  shape: const RoundedRectangleBorder(),
                ),
                icon: Icon(playing ? Icons.pause : Icons.play_arrow, size: 22),
                onPressed: _toggle,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    sample.text.isEmpty ? '—' : sample.text,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodyMedium,
                  ),
                  const SizedBox(height: 6),
                  // Reserved while idle so the row does not jump on play.
                  ValueListenableBuilder<double?>(
                    valueListenable: playingSpanProgress,
                    builder: (context, progress, _) => SizedBox(
                      height: 2,
                      child: playing
                          ? LinearProgressIndicator(
                              value: progress ?? 0,
                              color: SsColors.primary,
                              backgroundColor: SsColors.line,
                            )
                          : null,
                    ),
                  ),
                  if (samples.length > 1 || sample.overlap) ...[
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        for (
                          var i = 0;
                          samples.length > 1 && i < samples.length;
                          i++
                        )
                          Padding(
                            padding: const EdgeInsetsDirectional.only(end: 4),
                            child: _NumberChip(
                              label: toPersianDigits('${i + 1}'),
                              selected: i == _selected,
                              onTap: () => _choose(i),
                            ),
                          ),
                        if (sample.overlap)
                          Padding(
                            padding: const EdgeInsetsDirectional.only(start: 6),
                            child: Text(
                              'دو صدا همزمان',
                              style: theme.textTheme.bodySmall,
                            ),
                          ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _NumberChip extends StatelessWidget {
  const _NumberChip({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      selected: selected,
      label: 'نمونهٔ $label',
      child: InkWell(
        onTap: onTap,
        child: Container(
          width: 26,
          height: 26,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: selected ? SsColors.primary : Colors.transparent,
            border: Border.all(
              color: selected ? SsColors.primary : SsColors.line,
            ),
          ),
          child: Text(
            label,
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: selected ? SsColors.canvas : SsColors.ink,
            ),
          ),
        ),
      ),
    );
  }
}

/// What the user chose in [_NameDialog]: a new person's name, or an existing
/// [person] (with whether this voice should also be added to their voiceprint).
class _NameResult {
  const _NameResult.created(String name)
    : newName = name,
      person = null,
      addVoiceprints = true;
  const _NameResult.existing(Person this.person, {required this.addVoiceprints})
    : newName = null;

  final String? newName;
  final Person? person;
  final bool addVoiceprints;
}

class _NameDialog extends StatefulWidget {
  const _NameDialog({required this.speaker, required this.people});

  final DetectedSpeaker speaker;
  final List<Person> people;

  @override
  State<_NameDialog> createState() => _NameDialogState();
}

class _NameDialogState extends State<_NameDialog> {
  final _controller = TextEditingController();
  bool _addVoice = true;
  Person? _picked;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final picked = _picked;
    final ready = picked != null ? true : _controller.text.trim().isNotEmpty;
    return AlertDialog(
      title: Text('این صدا (${widget.speaker.label}) کیست؟'),
      content: SizedBox(
        width: 420,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                '«${widget.speaker.sampleText}»',
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
                style: theme.textTheme.bodySmall,
              ),
              if (widget.people.isNotEmpty) ...[
                const SizedBox(height: 12),
                DropdownMenu<Person>(
                  key: ValueKey(_picked?.clientId),
                  expandedInsets: EdgeInsets.zero,
                  initialSelection: _picked,
                  enableFilter: true,
                  requestFocusOnTap: true,
                  label: const Text('انتخاب از افراد ثبت‌شده'),
                  menuHeight: 240,
                  dropdownMenuEntries: [
                    for (final person in widget.people)
                      DropdownMenuEntry<Person>(
                        value: person,
                        label: person.name,
                      ),
                  ],
                  onSelected: (person) => setState(() {
                    _picked = person;
                    if (person != null) _controller.clear();
                  }),
                ),
                const SizedBox(height: 4),
              ],
              if (picked != null) ...[
                Align(
                  alignment: AlignmentDirectional.centerStart,
                  child: TextButton(
                    onPressed: () => setState(() => _picked = null),
                    style: TextButton.styleFrom(
                      visualDensity: VisualDensity.compact,
                    ),
                    child: const Text('به‌جای آن، فرد جدید بسازم'),
                  ),
                ),
                CheckboxListTile(
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                  value: _addVoice,
                  onChanged: (v) => setState(() => _addVoice = v ?? true),
                  title: Text(
                    'ردصدای این گوینده هم به «${picked.name}» اضافه شود تا بهتر شناخته شود.',
                    style: const TextStyle(fontSize: 13),
                  ),
                ),
              ] else ...[
                TextField(
                  controller: _controller,
                  autofocus: widget.people.isEmpty,
                  maxLength: 80,
                  buildCounter:
                      (
                        context, {
                        required currentLength,
                        required isFocused,
                        required maxLength,
                      }) => null,
                  decoration: InputDecoration(
                    labelText: widget.people.isEmpty
                        ? 'نام فرد'
                        : 'یا نام فرد جدید',
                  ),
                  onChanged: (_) => setState(() {}),
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('انصراف'),
        ),
        FilledButton(
          onPressed: ready
              ? () => Navigator.pop(
                  context,
                  picked != null
                      ? _NameResult.existing(picked, addVoiceprints: _addVoice)
                      : _NameResult.created(_controller.text.trim()),
                )
              : null,
          child: Text(picked != null ? 'نسبت دادن' : 'افزودن به افراد'),
        ),
      ],
    );
  }
}
