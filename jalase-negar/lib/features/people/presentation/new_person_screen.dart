import 'dart:async';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:uuid/uuid.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../application/people_providers.dart';
import '../data/enrollment_quality.dart';
import '../data/enrollment_session.dart';
import '../data/person.dart';

/// Adds a person on one page: read a motivational text aloud, type the name,
/// confirm consent and save. The person is only created when "save" is tapped.
class NewPersonScreen extends ConsumerStatefulWidget {
  const NewPersonScreen({super.key, this.returnPerson = false});

  /// When true (opened from the attendee picker) a successful save pops back
  /// with the new person's client id instead of going to the people list.
  final bool returnPerson;

  @override
  ConsumerState<NewPersonScreen> createState() => _NewPersonScreenState();
}

enum _Phase { idle, recording, processing, ready }

class _NewPersonScreenState extends ConsumerState<NewPersonScreen> {
  final _name = TextEditingController();
  late final EnrollmentRecorder _recorder = ref.read(
    enrollmentRecorderFactoryProvider,
  )();
  StreamSubscription<double>? _levels;
  _Phase _phase = _Phase.idle;
  double _level = 0;
  String? _message;
  bool _shared = false;
  bool _agreed = false;
  bool _saving = false;
  Float32List? _embedding;
  EnrollmentAssessment? _assessment;

  @override
  void dispose() {
    _levels?.cancel();
    _recorder.dispose();
    _name.dispose();
    super.dispose();
  }

  bool get _canSave =>
      _phase == _Phase.ready &&
      _name.text.trim().isNotEmpty &&
      _agreed &&
      !_saving;

  Future<void> _toggle(VoiceEmbeddingService service) async {
    if (_phase == _Phase.recording) {
      await _stop(service);
    } else if (_phase == _Phase.idle || _phase == _Phase.ready) {
      await _start();
    }
  }

  Future<void> _start() async {
    final granted = await _recorder.start();
    if (!mounted) return;
    if (!granted) {
      setState(
        () => _message =
            'دسترسی به میکروفون داده نشد؛ در تنظیمات گوشی اجازه‌ی میکروفون را فعال کنید.',
      );
      return;
    }
    _levels = _recorder.levels.listen((v) => setState(() => _level = v));
    setState(() {
      _phase = _Phase.recording;
      _message = null;
      _embedding = null;
      _assessment = null;
    });
  }

  Future<void> _stop(VoiceEmbeddingService service) async {
    await _levels?.cancel();
    _levels = null;
    setState(() {
      _phase = _Phase.processing;
      _level = 0;
    });
    final samples = await _recorder.stop();
    final assessment = assessEnrollmentSample(samples);
    if (!assessment.ok) {
      if (!mounted) return;
      setState(() {
        _phase = _Phase.idle;
        _message = assessment.messageFa;
      });
      return;
    }
    final embedding = await service.embed(samples);
    if (!mounted) return;
    if (embedding == null || embedding.isEmpty) {
      setState(() {
        _phase = _Phase.idle;
        _message =
            'ردصدا ساخته نشد؛ دوباره بخوانید و اگر تکرار شد مدل «تشخیص گوینده» را در بخش «مدل‌ها» دوباره نصب کنید.';
      });
      return;
    }
    setState(() {
      _phase = _Phase.ready;
      _embedding = embedding;
      _assessment = assessment;
      _message = null;
    });
  }

  Future<void> _save(VoiceEmbeddingService service) async {
    final embedding = _embedding;
    final assessment = _assessment;
    if (embedding == null || assessment == null || !_canSave) return;
    setState(() => _saving = true);
    try {
      final repo = await ref.read(peopleRepositoryProvider.future);
      final person = await ref
          .read(peopleActionsProvider)
          .create(
            name: _name.text.trim(),
            visibility: _shared
                ? PersonVisibility.org
                : PersonVisibility.private,
          );
      await repo.addVoiceprints(person.clientId, [
        Voiceprint(
          clientId: const Uuid().v4(),
          personId: person.clientId,
          modelId: service.modelId,
          modelVersion: service.modelVersion,
          embedding: embedding,
          createdAt: DateTime.now(),
          quality: assessment.quality,
          durationMs: assessment.speechMs,
        ),
      ]);
      ref.read(peopleActionsProvider).samplesAdded();
      if (!mounted) return;
      if (widget.returnPerson) {
        context.pop(person.clientId);
      } else {
        context.go('/people');
      }
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _message = 'ذخیره‌ی فرد انجام نشد؛ دوباره «ذخیره» را بزنید.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final prompts = ref.watch(speakerPromptsProvider);
    final embedder = ref.watch(voiceEmbeddingServiceProvider);
    Widget scaffold(Widget body) => Scaffold(
      appBar: SsAppBar(title: const Text('افزودن فرد')),
      body: body,
    );

    if (prompts.isLoading || embedder.isLoading) {
      return scaffold(const Center(child: CircularProgressIndicator()));
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
    final text = prompts.value?.prompts.firstOrNull?.text ?? '';
    final recording = _phase == _Phase.recording;
    final busy = _phase == _Phase.processing;
    return scaffold(
      ListView(
        padding: const EdgeInsets.all(16),
        children: [
          SsCard(
            title: '۱. این متن را بلند بخوانید',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'گوشی را مثل زمان تماس نزدیک نگه دارید و با صدای طبیعی بخوانید.',
                  style: theme.textTheme.bodySmall,
                ),
                const Divider(),
                Text(
                  text,
                  style: theme.textTheme.titleMedium?.copyWith(height: 2),
                ),
                const SizedBox(height: 12),
                _LevelMeter(level: _level, active: recording),
                const SizedBox(height: 12),
                FilledButton.icon(
                  onPressed: busy || _saving ? null : () => _toggle(service),
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
                        : _phase == _Phase.ready
                        ? 'ضبط دوباره'
                        : 'شروع خواندن',
                  ),
                ),
                if (_phase == _Phase.ready) ...[
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      const Icon(
                        Icons.check_circle,
                        size: 18,
                        color: SsColors.primary,
                      ),
                      const SizedBox(width: 6),
                      Text('صدا ضبط شد', style: theme.textTheme.bodyMedium),
                    ],
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 12),
          SsCard(
            title: '۲. نام فرد',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TextField(
                  controller: _name,
                  maxLength: 80,
                  textInputAction: TextInputAction.done,
                  onChanged: (_) => setState(() {}),
                  decoration: const InputDecoration(
                    labelText: 'نام فرد',
                    hintText: 'مثلاً علی رضایی',
                  ),
                ),
                SsSwitchTile(
                  value: _shared,
                  onChanged: (v) => setState(() => _shared = v),
                  title: const Text('اشتراک با سازمان'),
                  subtitle: const Text(
                    'اگر روشن باشد، همکاران متصل به همین سازمان هم می‌توانند از این صدا برای تشخیص گوینده استفاده کنند. به‌طور پیش‌فرض فقط برای خودتان است.',
                  ),
                ),
                CheckboxListTile(
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                  value: _agreed,
                  onChanged: (v) => setState(() => _agreed = v ?? false),
                  title: const Text(
                    'خودِ این فرد موافقت کرد که ردصدایش (نه فایل صوتی) فقط برای نوشتن نامش در جلسه‌ها، رمزشده روی گوشی (و سرور سازمان در صورت اتصال) نگه‌داری شود. هر زمان از صفحه‌ی فرد قابل حذف است.',
                  ),
                ),
              ],
            ),
          ),
          if (_message != null) ...[
            const SizedBox(height: 8),
            Text(
              _message!,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: SsColors.danger,
              ),
            ),
          ],
          const SizedBox(height: 12),
          FilledButton(
            onPressed: _canSave ? () => _save(service) : null,
            child: Text(_saving ? 'در حال ذخیره…' : 'ذخیره'),
          ),
        ],
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
