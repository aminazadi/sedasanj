import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/utils/format.dart';
import '../application/people_providers.dart';
import '../data/enrollment_session.dart';
import '../data/people_repository.dart';
import '../data/person.dart';

/// Records a person reading the prompt texts, one at a time. Each accepted
/// recording is stored immediately.
class EnrollScreen extends ConsumerWidget {
  const EnrollScreen({super.key, required this.personId});

  final String personId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final people = ref.watch(peopleProvider);
    final prompts = ref.watch(speakerPromptsProvider);
    final embedder = ref.watch(voiceEmbeddingServiceProvider);
    final repo = ref.watch(peopleRepositoryProvider);

    Widget scaffold(Widget body) => Scaffold(
      appBar: SsAppBar(title: const Text('ثبت صدا')),
      body: body,
    );

    if (people.isLoading ||
        prompts.isLoading ||
        embedder.isLoading ||
        repo.isLoading) {
      return scaffold(const Center(child: CircularProgressIndicator()));
    }
    final person = people.value
        ?.where((p) => p.clientId == personId)
        .firstOrNull;
    if (person == null ||
        !person.mine ||
        prompts.value == null ||
        repo.value == null) {
      return scaffold(const Center(child: Text('این فرد پیدا نشد.')));
    }
    final service = embedder.value;
    if (service == null) {
      return scaffold(
        ListView(
          padding: const EdgeInsets.all(16),
          children: [
            SsCard(
              title: 'مدل تشخیص گوینده نصب نیست',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text(
                    'برای ثبت صدا، مدل «تشخیص گوینده» را یک‌بار از بخش «مدل‌ها» دانلود کنید و برگردید.',
                  ),
                  const SizedBox(height: 8),
                  FilledButton(
                    onPressed: () => context.push('/models'),
                    child: const Text('رفتن به مدل‌ها'),
                  ),
                ],
              ),
            ),
          ],
        ),
      );
    }
    return _EnrollBody(
      person: person,
      prompts: prompts.value!,
      embedder: service,
      repository: repo.value!,
    );
  }
}

class _EnrollBody extends ConsumerStatefulWidget {
  const _EnrollBody({
    required this.person,
    required this.prompts,
    required this.embedder,
    required this.repository,
  });

  final Person person;
  final SpeakerPrompts prompts;
  final VoiceEmbeddingService embedder;
  final PeopleRepository repository;

  @override
  ConsumerState<_EnrollBody> createState() => _EnrollBodyState();
}

class _EnrollBodyState extends ConsumerState<_EnrollBody> {
  late final EnrollmentSession _session;

  @override
  void initState() {
    super.initState();
    _session = EnrollmentSession(
      personId: widget.person.clientId,
      prompts: widget.prompts,
      recorder: ref.read(enrollmentRecorderFactoryProvider)(),
      embedder: widget.embedder,
      repository: widget.repository,
    );
  }

  @override
  void dispose() {
    _session.dispose();
    super.dispose();
  }

  Future<void> _toggle() async {
    final phase = _session.state.value.phase;
    if (phase == EnrollmentPhase.recording) {
      final ok = await _session.stop();
      if (ok) ref.read(peopleActionsProvider).samplesAdded();
    } else if (phase == EnrollmentPhase.idle) {
      await _session.start();
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: SsAppBar(title: Text('ثبت صدای ${widget.person.name}')),
      body: ValueListenableBuilder<EnrollmentState>(
        valueListenable: _session.state,
        builder: (context, state, _) {
          final prompts = widget.prompts.prompts;
          final prompt = prompts[state.index];
          final recording = state.phase == EnrollmentPhase.recording;
          final busy = state.phase == EnrollmentPhase.processing;
          if (state.phase == EnrollmentPhase.finished) {
            return _Done(person: widget.person, state: state);
          }
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Text(
                'متن ${toPersianDigits('${state.index + 1}')} از ${toPersianDigits('${prompts.length}')}'
                '${prompt.required ? '' : ' (اختیاری؛ دقت را بیشتر می‌کند)'}',
                style: theme.textTheme.labelLarge,
              ),
              const SizedBox(height: 4),
              LinearProgressIndicator(
                value: state.accepted.length / prompts.length,
                color: SsColors.primary,
                backgroundColor: SsColors.selected,
              ),
              const SizedBox(height: 12),
              SsCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      prompt.near
                          ? 'گوشی را مثل زمان تماس، نزدیک نگه دارید.'
                          : 'این متن را با گوشی روی میز، حدود ۵۰ سانتی‌متر دورتر بخوانید (مثل جلسه).',
                      style: theme.textTheme.bodySmall,
                    ),
                    const Divider(),
                    Text(
                      prompt.text,
                      style: theme.textTheme.titleMedium?.copyWith(height: 2),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 12),
              _LevelMeter(level: state.level, active: recording),
              if (state.message != null) ...[
                const SizedBox(height: 8),
                Text(
                  state.message!,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: SsColors.danger,
                  ),
                ),
              ],
              const SizedBox(height: 12),
              FilledButton.icon(
                onPressed: busy ? null : _toggle,
                icon: busy
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : Icon(recording ? Icons.stop : Icons.mic),
                label: Text(
                  busy
                      ? 'در حال بررسی…'
                      : recording
                      ? 'پایان خواندن'
                      : state.accepted.contains(prompt.id)
                      ? 'ضبط دوباره‌ی این متن'
                      : 'شروع خواندن',
                ),
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  TextButton(
                    onPressed: state.index > 0 && !recording && !busy
                        ? () => _session.goTo(state.index - 1)
                        : null,
                    child: const Text('متن قبلی'),
                  ),
                  const Spacer(),
                  if (!prompt.required || state.accepted.contains(prompt.id))
                    TextButton(
                      onPressed:
                          state.index < prompts.length - 1 &&
                              !recording &&
                              !busy
                          ? () => _session.goTo(state.index + 1)
                          : null,
                      child: const Text('متن بعدی'),
                    ),
                ],
              ),
              if (_session.canFinish)
                OutlinedButton(
                  onPressed: recording || busy
                      ? null
                      : () => context.pushReplacement(
                          '/people/${widget.person.clientId}',
                        ),
                  child: const Text('پایان ثبت صدا'),
                ),
            ],
          );
        },
      ),
    );
  }
}

class _LevelMeter extends StatelessWidget {
  const _LevelMeter({required this.level, required this.active});

  final double level;
  final bool active;

  @override
  Widget build(BuildContext context) {
    // Power to a perceptual bar: speech sits around -30 dB.
    final bar = active && level > 0
        ? ((10 * math.log(level) / math.ln10 + 50) / 50).clamp(0.0, 1.0)
        : 0.0;
    return Semantics(
      label: 'تراز صدای ورودی',
      child: ClipRRect(
        borderRadius: BorderRadius.circular(4),
        child: LinearProgressIndicator(
          minHeight: 10,
          value: bar,
          color: bar > 0.92 ? SsColors.danger : SsColors.primary,
          backgroundColor: SsColors.selected,
        ),
      ),
    );
  }
}

class _Done extends StatelessWidget {
  const _Done({required this.person, required this.state});

  final Person person;
  final EnrollmentState state;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        SsCard(
          title: 'صدای ${person.name} ثبت شد',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                'از این پس، در جلسه‌هایی که با «نوشتن نام گوینده» ضبط می‌کنید، نام این فرد کنار گفته‌هایش می‌آید.',
              ),
              const SizedBox(height: 12),
              FilledButton(
                onPressed: () =>
                    context.pushReplacement('/people/${person.clientId}'),
                child: const Text('تمام'),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
