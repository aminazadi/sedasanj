import 'dart:async';
import '../../../core/speaker/speaker_matcher.dart';
import 'channel_owner_sheet.dart';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/utils/format.dart';
import '../../meetings/data/attendee.dart';
import '../../meetings/presentation/meeting_type_picker_sheet.dart';
import '../../onboarding/tour_overlay.dart';
import '../../people/application/people_providers.dart';
import '../../people/presentation/attendee_picker_sheet.dart';
import '../../onboarding/tour_step.dart';
import '../../catalog/application/catalog_providers.dart';
import '../application/live_audio_waveform.dart';
import '../application/pending_attendees.dart';
import '../application/pending_meeting_type.dart';
import '../application/recorder_controller.dart';
import 'live_transcript_panel.dart';
import 'live_waveform.dart';
import 'meeting_illustration.dart';
import 'recording_start_sound.dart';

class RecordingScreen extends ConsumerStatefulWidget {
  const RecordingScreen({super.key, this.liveTranscript});

  /// Replaces the built-in live transcript panel (previews and tests).
  final Widget? liveTranscript;

  @override
  ConsumerState<RecordingScreen> createState() => _RecordingScreenState();
}

class _RecordingScreenState extends ConsumerState<RecordingScreen> {
  static const _controlsHeight = 132.0;
  late final AppLifecycleListener _lifecycle;
  RecordingStartSound? _startSound;
  Timer? _countdownTimer;
  int? _secondsRemaining;
  bool _openingMicrophone = false;

  bool get _preparing => _startSound != null || _openingMicrophone;

  @override
  void initState() {
    super.initState();
    _lifecycle = AppLifecycleListener(onInactive: _cancelPreparation);
  }

  @override
  void dispose() {
    _lifecycle.dispose();
    _countdownTimer?.cancel();
    final sound = _startSound;
    if (sound != null) unawaited(sound.close());
    super.dispose();
  }

  void _prepare() {
    if (_preparing) return;
    setState(() => _startSound = ref.read(recordingStartSoundProvider)());
  }

  void _cancelPreparation() {
    final sound = _startSound;
    if (sound == null) return;
    _countdownTimer?.cancel();
    setState(() {
      _startSound = null;
      _secondsRemaining = null;
    });
    unawaited(sound.close());
  }

  void _beginCountdown() {
    final sound = _startSound;
    if (sound == null) return;

    void showSecond(int seconds) {
      setState(() => _secondsRemaining = seconds);
      unawaited(sound.play());
    }

    var seconds = 3;
    showSecond(seconds);
    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      seconds--;
      if (seconds > 0) {
        showSecond(seconds);
      } else {
        timer.cancel();
        unawaited(_openMicrophone(sound));
      }
    });
  }

  Future<void> _openMicrophone(RecordingStartSound sound) async {
    setState(() => _secondsRemaining = 0);
    await sound.playFinal();
    await sound.close();
    if (!mounted || !identical(_startSound, sound)) return;

    setState(() {
      _startSound = null;
      _secondsRemaining = null;
      _openingMicrophone = true;
    });
    try {
      final chosen = ref.read(pendingAttendeesProvider);
      final people = ref.read(peopleProvider).value ?? const [];
      final attendees = [
        for (final p in people)
          if (chosen.contains(p.clientId))
            Attendee(personId: p.clientId, name: p.name),
      ];
      final meetingType = ref.read(pendingMeetingTypeProvider);
      await ref
          .read(recorderControllerProvider.notifier)
          .start(
            attendees: attendees,
            outputTypeCode: meetingType.code,
            outputTypeInputValues: meetingType.values,
          );
      ref.read(pendingAttendeesProvider.notifier).clear();
      ref.read(pendingMeetingTypeProvider.notifier).clear();
    } finally {
      if (mounted) setState(() => _openingMicrophone = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(recorderControllerProvider);
    final controller = ref.read(recorderControllerProvider.notifier);

    ref.listen(recorderControllerProvider, (previous, next) {
      if (next.error != null && next.error != previous?.error) {
        SsToastHost.show(context, next.error!);
      }
      final meetingId = next.savedMeetingId;
      if (meetingId != null && meetingId != previous?.savedMeetingId) {
        context.pushReplacement('/meeting/$meetingId');
      }
    });

    final isRecording = state.status == RecorderStatus.recording;
    final isPaused = state.status == RecorderStatus.paused;
    final isSaving = state.status == RecorderStatus.saving;

    final isActive = isRecording || isPaused || isSaving;

    return PopScope(
      canPop: !isActive && !_openingMicrophone,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) {
          _cancelPreparation();
          return;
        }
        if (!isActive || isSaving) return;
        final leave = await showDialog<String>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('توقف ضبط؟'),
            content: const Text(
              'ضبط در جریان است. با خروج، ضبط متوقف و جلسه ذخیره می‌شود.',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, 'continue'),
                child: const Text('ادامه ضبط'),
              ),
              TextButton(
                style: TextButton.styleFrom(
                  foregroundColor: SsColors.of(context).danger,
                ),
                onPressed: () => Navigator.pop(context, 'discard'),
                child: const Text('حذف'),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(context, 'save'),
                child: const Text('توقف و ذخیره'),
              ),
            ],
          ),
        );
        if (leave == 'save') await controller.stop();
        if (leave == 'discard') {
          if (!context.mounted) return;
          final sure = await showDialog<bool>(
            context: context,
            builder: (context) => AlertDialog(
              title: const Text('حذف این ضبط؟'),
              content: const Text(
                'ضبط و متن آن برای همیشه پاک می‌شود و برگشتی ندارد.',
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context, false),
                  child: const Text('انصراف'),
                ),
                FilledButton(
                  style: FilledButton.styleFrom(
                    backgroundColor: SsColors.of(context).danger,
                  ),
                  onPressed: () => Navigator.pop(context, true),
                  child: const Text('حذف'),
                ),
              ],
            ),
          );
          if (sure == true) {
            await controller.stopAndDiscard();
            if (!context.mounted) return;
            if (context.canPop()) {
              context.pop();
            } else {
              context.go('/');
            }
          }
        }
      },
      child: Scaffold(
        appBar: SsAppBar(title: const Text('ضبط جلسه'), actions: []),
        body: SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
            child: Stack(
              fit: StackFit.expand,
              children: [
                Column(
                  children: [
                    Expanded(
                      child: isActive
                          // Just the text, from the top of the page down to the
                          // waveform: new lines slide in and, once the page
                          // is full, older ones scroll up and fade out.
                          ? ClipRect(
                              child:
                                  widget.liveTranscript ??
                                  LiveTranscriptPanel(
                                    state: controller.live,
                                    bare: true,
                                  ),
                            )
                          : const SizedBox.expand(),
                    ),
                    if (isActive) ...[
                      if (state.interrupted || isPaused || isSaving)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 6),
                          child: Text(
                            isSaving
                                ? 'در حال ذخیرهٔ جلسه، لطفاً صبر کنید…'
                                : isPaused
                                ? 'ضبط موقتاً متوقف است'
                                : 'ضبط توسط سیستم موقتاً متوقف شد و خودکار ادامه می‌یابد.',
                            textAlign: TextAlign.center,
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                        ),
                      ValueListenableBuilder<String?>(
                        valueListenable: controller.channelNotice,
                        builder: (context, notice, _) => notice == null
                            ? const SizedBox.shrink()
                            : Padding(
                                padding: const EdgeInsets.only(bottom: 6),
                                child: Text(
                                  notice,
                                  textAlign: TextAlign.center,
                                  style: Theme.of(context).textTheme.bodySmall,
                                ),
                              ),
                      ),
                      ValueListenableBuilder<List<LiveAudioWaveform>>(
                        valueListenable: controller.channelWaveforms,
                        builder: (context, waveforms, _) =>
                            ValueListenableBuilder<Set<int>>(
                              valueListenable: controller.mutedChannels,
                              builder: (context, muted, _) =>
                                  ValueListenableBuilder<
                                    Map<int, SpeakerIdentity>
                                  >(
                                    valueListenable: controller.channelOwners,
                                    builder: (context, owners, _) =>
                                        _RecordingMonitor(
                                          state: state,
                                          active:
                                              isRecording && !state.interrupted,
                                          waveforms: waveforms,
                                          muted: muted,
                                          owners: owners,
                                          onToggleMute:
                                              controller.toggleChannelMute,
                                          onPickOwner: (i, label) async {
                                            final choice =
                                                await showChannelOwnerPicker(
                                                  context,
                                                  channelLabel: label,
                                                  currentPersonId:
                                                      owners[i]?.personId,
                                                );
                                            if (choice == null) return;
                                            final p = choice.person;
                                            controller.assignChannel(
                                              i,
                                              p == null
                                                  ? null
                                                  : SpeakerIdentity(
                                                      name: p.name,
                                                      personId: p.clientId,
                                                      confidence: 100,
                                                    ),
                                            );
                                          },
                                        ),
                                  ),
                            ),
                      ),
                    ],
                    SizedBox(
                      height: _controlsHeight,
                      child: Center(
                        child: switch (state.status) {
                          RecorderStatus.idle when _preparing =>
                            _openingMicrophone
                                ? const SsProcessingMark(size: 30)
                                : const SizedBox.shrink(),
                          RecorderStatus.idle => _ControlColumn(
                            label: 'شروع ضبط',
                            child: TourTarget(
                              step: TourStep.recording,
                              child: SsDiamondButton(
                                pulse: true,
                                half: 38,
                                // Same hand-drawn glyph as the bottom nav
                                // bar's floating record button, since both
                                // represent the same "start recording"
                                // action.
                                glyphBuilder: (color, size) =>
                                    SsMicGlyph(color: color, size: size),
                                onTap: _prepare,
                              ),
                            ),
                          ),
                          RecorderStatus.saving => const Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [SsProcessingMark(size: 30)],
                          ),
                          _ => Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              _ControlColumn(
                                label: isRecording ? 'توقف موقت' : 'ادامه',
                                // Same half as "شروع ضبط" and the bottom
                                // bar's record diamond: the gap between the
                                // two buttons closes the space instead of
                                // shrinking either one below that size.
                                child: SsDiamondButton(
                                  half: 38,
                                  icon: isRecording
                                      ? Icons.pause
                                      : Icons.play_arrow,
                                  outlined: true,
                                  onTap: isRecording
                                      ? controller.pause
                                      : controller.resume,
                                ),
                              ),
                              const SizedBox(width: 28),
                              _ControlColumn(
                                label: 'پایان و ذخیره',
                                child: SsDiamondButton(
                                  half: 38,
                                  icon: Icons.stop,
                                  danger: true,
                                  onTap: controller.stop,
                                ),
                              ),
                            ],
                          ),
                        },
                      ),
                    ),
                  ],
                ),
                Positioned.fill(
                  bottom: _controlsHeight,
                  child: _RecordingPreview(
                    dispersed: _preparing || isActive,
                    secondsRemaining: _secondsRemaining,
                    onDispersed: _beginCountdown,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _RecordingPreview extends StatelessWidget {
  const _RecordingPreview({
    required this.dispersed,
    required this.secondsRemaining,
    required this.onDispersed,
  });

  final bool dispersed;
  final int? secondsRemaining;
  final VoidCallback onDispersed;

  @override
  Widget build(BuildContext context) {
    return Stack(
      fit: StackFit.expand,
      children: [
        _buildIllustration(context),
        if (secondsRemaining == 0)
          Center(
            child: Semantics(
              liveRegion: true,
              child: Text(
                'آمادهٔ ضبط…',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.headlineSmall,
              ),
            ),
          )
        else if (secondsRemaining case final seconds?)
          Center(child: _CountdownNumber(seconds: seconds)),
      ],
    );
  }

  Widget _buildIllustration(BuildContext context) {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Flexible(
          child: Padding(
            padding: const EdgeInsets.only(bottom: 20),
            child: IgnorePointer(
              child: MeetingIllustration(
                dispersed: dispersed,
                onDispersed: onDispersed,
              ),
            ),
          ),
        ),
        Visibility.maintain(
          visible: !dispersed,
          child: Column(
            children: [
              Text(
                'قبل از شروع جلسه لطفا موارد زیر را مشخص کنید',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodySmall,
              ),
              const SizedBox(height: 14),
              const SizedBox(width: double.infinity, child: _SetupSteps()),
            ],
          ),
        ),
      ],
    );
  }
}

class _CountdownNumber extends StatelessWidget {
  const _CountdownNumber({required this.seconds});

  final int seconds;

  @override
  Widget build(BuildContext context) {
    final digit = toPersianDigits('$seconds');
    return Semantics(
      liveRegion: true,
      label: 'شروع ضبط تا $digit ثانیهٔ دیگر',
      excludeSemantics: true,
      child: TweenAnimationBuilder<double>(
        key: ValueKey(seconds),
        duration: MediaQuery.disableAnimationsOf(context)
            ? Duration.zero
            : const Duration(milliseconds: 220),
        curve: Curves.easeOutCubic,
        tween: Tween(begin: 0.35, end: 1),
        builder: (context, opacity, child) => Opacity(
          opacity: opacity,
          child: Transform.scale(scale: 0.9 + 0.1 * opacity, child: child),
        ),
        child: Text(
          digit,
          key: const Key('countdown-digit'),
          style: Theme.of(context).textTheme.displayLarge?.copyWith(
            color: SsColors.of(context).primary,
            fontSize: 96,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
    );
  }
}

class _RecordingMonitor extends StatelessWidget {
  const _RecordingMonitor({
    required this.state,
    required this.active,
    required this.waveforms,
    required this.muted,
    required this.owners,
    required this.onToggleMute,
    required this.onPickOwner,
  });

  final RecorderState state;
  final bool active;
  final List<LiveAudioWaveform> waveforms;
  final Set<int> muted;
  final Map<int, SpeakerIdentity> owners;
  final ValueChanged<int> onToggleMute;
  final void Function(int channel, String label) onPickOwner;

  /// Height of three channel rows (button height 32).
  static const double _maxRowsHeight = 3 * 32.0;

  @override
  Widget build(BuildContext context) {
    final color = active
        ? SsColors.of(context).danger
        : SsColors.of(context).ink;
    final many = waveforms.length > 1;
    return DecoratedBox(
      decoration: BoxDecoration(
        border: Border(top: BorderSide(color: SsColors.of(context).line)),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Row(
          textDirection: TextDirection.rtl,
          children: [
            Semantics(
              label: 'زمان ضبط',
              child: Text(
                formatDuration(state.elapsed),
                textDirection: TextDirection.ltr,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: color,
                  fontFeatures: const [FontFeature.tabularFigures()],
                ),
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              // Up to three channels are shown; more scroll, so the text keeps
              // its room.
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: _maxRowsHeight),
                child: SingleChildScrollView(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      for (var i = 0; i < waveforms.length; i++)
                        Row(
                          textDirection: TextDirection.rtl,
                          children: [
                            Expanded(
                              child: Opacity(
                                opacity: muted.contains(i) ? 0.3 : 1,
                                child: LiveWaveform(
                                  waveform: waveforms[i],
                                  active: active && !muted.contains(i),
                                ),
                              ),
                            ),
                            const SizedBox(width: 8),
                            _MuteButton(
                              muted: muted.contains(i),
                              label: many
                                  ? 'کانال ${toPersianDigits('${i + 1}')}'
                                  : 'میکروفون',
                              number: many ? toPersianDigits('${i + 1}') : null,
                              onTap: () => onToggleMute(i),
                            ),
                            const SizedBox(width: 4),
                            _OwnerButton(
                              name: owners[i]?.name,
                              onTap: () => onPickOwner(
                                i,
                                many
                                    ? 'کانال ${toPersianDigits('${i + 1}')}'
                                    : 'میکروفون',
                              ),
                            ),
                          ],
                        ),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Icon-only button naming who holds a microphone ("نامشخص" while nobody
/// does and voices are recognised automatically); opens the picker.
class _OwnerButton extends StatelessWidget {
  const _OwnerButton({required this.name, required this.onTap});

  final String? name;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final assigned = name != null;
    final color = assigned
        ? SsColors.of(context).primary
        : SsColors.of(context).ink;
    return Tooltip(
      message: assigned
          ? 'صاحب میکروفون: $name؛ برای تغییر بزنید'
          : 'انتساب میکروفون به یک فرد',
      child: Semantics(
        button: true,
        label: assigned ? 'صاحب میکروفون $name' : 'انتساب میکروفون',
        child: InkResponse(
          onTap: onTap,
          radius: 20,
          child: SizedBox(
            width: 32,
            height: 32,
            child: Icon(Icons.person_outline, size: 18, color: color),
          ),
        ),
      ),
    );
  }
}

/// Icon-only mute toggle: a plain mic while the channel is live, a crossed-out
/// mic in the danger color when it is muted. No border, no fill.
class _MuteButton extends StatelessWidget {
  const _MuteButton({
    required this.muted,
    required this.label,
    required this.onTap,
    this.number,
  });

  final bool muted;
  final String label;
  final String? number;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final color = muted
        ? SsColors.of(context).danger
        : SsColors.of(context).primary;
    return Tooltip(
      message: muted
          ? '$label بی‌صدا است؛ برای باز کردن بزنید'
          : 'بی‌صدا کردن $label',
      child: Semantics(
        button: true,
        toggled: muted,
        label: label,
        child: InkResponse(
          onTap: onTap,
          radius: 20,
          child: SizedBox(
            width: 32,
            height: 32,
            child: Center(
              child: number == null
                  ? Icon(
                      muted ? Icons.mic_off : Icons.mic_none,
                      size: 18,
                      color: color,
                    )
                  : Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          muted ? Icons.mic_off : Icons.mic_none,
                          size: 15,
                          color: color,
                        ),
                        Text(
                          number!,
                          style: TextStyle(fontSize: 11, color: color),
                        ),
                      ],
                    ),
            ),
          ),
        ),
      ),
    );
  }
}

class _ControlColumn extends StatelessWidget {
  const _ControlColumn({required this.label, required this.child});

  final String label;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        child,
        const SizedBox(height: 8),
        Text(
          label,
          style: TextStyle(
            fontFamily: 'YekanBakh',
            fontSize: 12,
            fontWeight: FontWeight.w600,
            color: SsColors.of(context).ink,
          ),
        ),
      ],
    );
  }
}

/// Two steps between the ready-to-record instructions and the mic button:
/// who's in the meeting, and which category it will be converted into.
class _SetupSteps extends ConsumerWidget {
  const _SetupSteps();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final chosen = ref.watch(pendingAttendeesProvider);
    final people = ref.watch(peopleProvider).value ?? const [];
    final names = {for (final p in people) p.clientId: p.name};

    final meetingType = ref.watch(pendingMeetingTypeProvider);
    final typesAsync = ref.watch(meetingTypesProvider);
    final types = typesAsync.value ?? const [];
    // A failed load used to fall back silently to the default label, which hid
    // why the admin's categories were missing. Say so instead.
    final typeLoadFailed = typesAsync.hasError && types.isEmpty;
    final typeTitle = typeLoadFailed
        ? 'فهرست دسته‌ها بارگذاری نشد؛ برای تلاش دوباره ضربه بزنید'
        : [
                for (final t in types)
                  if (t.code == meetingType.code) t.title,
              ].firstOrNull ??
              'صورت جلسه عمومی';

    Future<void> pickAttendees() async {
      final result = await showAttendeePicker(context, selected: chosen);
      if (result != null) {
        ref.read(pendingAttendeesProvider.notifier).set(result);
      }
    }

    Future<void> pickType() async {
      if (typeLoadFailed) {
        ref.invalidate(meetingTypesProvider);
        return;
      }
      final result = await showMeetingTypePicker(context, initial: meetingType);
      if (result != null) {
        ref.read(pendingMeetingTypeProvider.notifier).set(result);
      }
    }

    return TourTarget(
      step: TourStep.setup,
      child: SsCard(
        padding: EdgeInsets.zero,
        elevated: true,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            _StepTile(
              title: 'حاضران جلسه',
              subtitle: chosen.isEmpty
                  ? 'برای افزودن حاضران ضربه بزنید'
                  : '${toPersianDigits('${chosen.length}')} نفر: '
                        '${chosen.map((id) => names[id] ?? 'فرد حذف‌شده').join('، ')}',
              onTap: pickAttendees,
            ),
            Padding(
              padding: const EdgeInsetsDirectional.only(start: 16, end: 16),
              child: Divider(height: 1, color: SsColors.of(context).line),
            ),
            _StepTile(
              title: 'نوع خروجی درخواستی',
              subtitle: typeTitle,
              onTap: pickType,
            ),
          ],
        ),
      ),
    );
  }
}

class _StepTile extends StatelessWidget {
  const _StepTile({
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    title,
                    style: theme.textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    subtitle,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodySmall,
                  ),
                ],
              ),
            ),
            const SizedBox(width: 4),
            Icon(
              Icons.chevron_right_rounded,
              color: SsColors.of(context).neutral,
              size: 22,
            ),
          ],
        ),
      ),
    );
  }
}
