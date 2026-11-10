import 'dart:async';
import '../../../core/speaker/speaker_matcher.dart';
import 'channel_owner_sheet.dart';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/utils/format.dart';
import '../../meetings/data/attendee.dart';
import '../../onboarding/tour_overlay.dart';
import '../../people/application/people_providers.dart';
import '../../people/presentation/attendee_picker_sheet.dart';
import '../../onboarding/tour_step.dart';
import '../application/live_audio_waveform.dart';
import '../application/pending_attendees.dart';
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
      await ref
          .read(recorderControllerProvider.notifier)
          .start(attendees: attendees);
      ref.read(pendingAttendeesProvider.notifier).clear();
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
                style: TextButton.styleFrom(foregroundColor: SsColors.danger),
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
                    backgroundColor: SsColors.danger,
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
                              child: _DiamondButton(
                                pulse: true,
                                half: 38,
                                icon: Icons.mic,
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
                                child: _DiamondButton(
                                  half: 34,
                                  icon: isRecording
                                      ? Icons.pause
                                      : Icons.play_arrow,
                                  outlined: true,
                                  onTap: isRecording
                                      ? controller.pause
                                      : controller.resume,
                                ),
                              ),
                              const SizedBox(width: 44),
                              _ControlColumn(
                                label: 'پایان و ذخیره',
                                child: _DiamondButton(
                                  half: 34,
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
                'برای شروع ضبط، دکمهٔ زیر را بزنید',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodySmall,
              ),
              const SizedBox(height: 12),
              const _AttendeesSelector(),
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
          style: Theme.of(context).textTheme.displayLarge?.copyWith(
            color: SsColors.primary,
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
    final color = active ? SsColors.danger : SsColors.ink;
    final many = waveforms.length > 1;
    return DecoratedBox(
      decoration: const BoxDecoration(
        border: Border(top: BorderSide(color: SsColors.line)),
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

/// Flat outlined button naming who holds a microphone ("نامشخص" while nobody
/// does and voices are recognised automatically); opens the picker.
class _OwnerButton extends StatelessWidget {
  const _OwnerButton({required this.name, required this.onTap});

  final String? name;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final assigned = name != null;
    final color = assigned ? SsColors.primary : SsColors.ink;
    return Tooltip(
      message: assigned
          ? 'صاحب میکروفون: $name؛ برای تغییر بزنید'
          : 'انتساب میکروفون به یک فرد',
      child: Semantics(
        button: true,
        label: assigned ? 'صاحب میکروفون $name' : 'انتساب میکروفون',
        child: Material(
          color: assigned ? SsColors.primary : Colors.transparent,
          shape: RoundedRectangleBorder(
            side: BorderSide(
              color: assigned ? SsColors.primary : SsColors.line,
            ),
          ),
          child: InkWell(
            onTap: onTap,
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 32, maxWidth: 110),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      Icons.person_outline,
                      size: 16,
                      color: assigned ? SsColors.canvas : color,
                    ),
                    const SizedBox(width: 4),
                    Flexible(
                      child: Text(
                        name ?? 'فرد',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontSize: 12,
                          color: assigned ? SsColors.canvas : color,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Square mute toggle in the app's flat style (like the play buttons): an
/// outlined mic while the channel is live, a filled red crossed-out mic when
/// it is muted.
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
    final color = muted ? SsColors.danger : SsColors.primary;
    return Tooltip(
      message: muted
          ? '$label بی‌صدا است؛ برای باز کردن بزنید'
          : 'بی‌صدا کردن $label',
      child: Semantics(
        button: true,
        toggled: muted,
        label: label,
        child: Material(
          color: muted ? SsColors.danger : Colors.transparent,
          shape: RoundedRectangleBorder(side: BorderSide(color: color)),
          child: InkWell(
            onTap: onTap,
            child: SizedBox(
              width: 32,
              height: 32,
              child: Center(
                child: number == null
                    ? Icon(
                        muted ? Icons.mic_off : Icons.mic_none,
                        size: 18,
                        color: muted ? SsColors.canvas : color,
                      )
                    : Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            muted ? Icons.mic_off : Icons.mic_none,
                            size: 15,
                            color: muted ? SsColors.canvas : color,
                          ),
                          Text(
                            number!,
                            style: TextStyle(
                              fontSize: 11,
                              color: muted ? SsColors.canvas : color,
                            ),
                          ),
                        ],
                      ),
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
          style: const TextStyle(
            fontFamily: 'Vazirmatn',
            fontSize: 12,
            fontWeight: FontWeight.w600,
            color: SsColors.ink,
          ),
        ),
      ],
    );
  }
}

/// Diamond (45° square) button, the same shape as the record button in the
/// bottom bar. [half] is the diamond's half-diagonal.
class _DiamondButton extends StatefulWidget {
  const _DiamondButton({
    required this.half,
    required this.icon,
    required this.onTap,
    this.outlined = false,
    this.danger = false,
    this.pulse = false,
  });

  final double half;
  final IconData icon;
  final VoidCallback onTap;
  final bool outlined;
  final bool danger;
  final bool pulse;

  @override
  State<_DiamondButton> createState() => _DiamondButtonState();
}

class _DiamondButtonState extends State<_DiamondButton>
    with SingleTickerProviderStateMixin {
  late final AnimationController _pulse = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 2400),
  );
  bool _down = false;

  @override
  void initState() {
    super.initState();
    if (widget.pulse) _pulse.repeat();
  }

  @override
  void didUpdateWidget(covariant _DiamondButton oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.pulse != oldWidget.pulse) {
      if (widget.pulse) {
        _pulse.repeat();
      } else {
        _pulse.stop();
        _pulse.value = 0;
      }
    }
  }

  @override
  void dispose() {
    _pulse.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final d = widget.half;
    final side = d * math.sqrt2;
    // The pulsing start button is the record button: red, like the bar's.
    final red = widget.danger || widget.pulse;
    final main = red ? SsColors.danger : SsColors.primary;
    final colors = red
        ? const [Color(0xFFE5484D), SsColors.danger, Color(0xFF8F0E2E)]
        : const [SsColors.primaryLight, SsColors.primary, SsColors.primaryDark];
    return Semantics(
      button: true,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTapDown: (_) => setState(() => _down = true),
        onTapCancel: () => setState(() => _down = false),
        onTapUp: (_) => setState(() => _down = false),
        onTap: widget.onTap,
        child: AnimatedBuilder(
          animation: _pulse,
          builder: (context, child) {
            final animate =
                widget.pulse && !MediaQuery.disableAnimationsOf(context);
            return Stack(
              alignment: Alignment.center,
              clipBehavior: Clip.none,
              children: [
                if (animate)
                  Container(
                    width: side * 0.9,
                    height: side * 0.9,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      boxShadow: [
                        BoxShadow(
                          color: main.withValues(
                            alpha:
                                0.25 +
                                0.3 *
                                    (0.5 +
                                        0.5 *
                                            math.sin(
                                              _pulse.value * 2 * math.pi,
                                            )),
                          ),
                          blurRadius:
                              18 +
                              12 *
                                  (0.5 +
                                      0.5 *
                                          math.sin(_pulse.value * 2 * math.pi)),
                          spreadRadius: 3,
                        ),
                      ],
                    ),
                  ),
                if (animate)
                  Builder(
                    builder: (context) {
                      // Same single ring as the bottom bar's record diamond.
                      final t = Curves.easeOut.transform(_pulse.value);
                      final ringSize = side + 12 * t;
                      return Positioned(
                        left: (2 * d + 8 - ringSize) / 2,
                        top: (2 * d + 8 - ringSize) / 2,
                        width: ringSize,
                        height: ringSize,
                        child: Transform.rotate(
                          angle: math.pi / 4,
                          child: DecoratedBox(
                            decoration: BoxDecoration(
                              border: Border.all(
                                color: main.withValues(alpha: 0.35 * (1 - t)),
                              ),
                            ),
                          ),
                        ),
                      );
                    },
                  ),
                child!,
              ],
            );
          },
          child: AnimatedScale(
            duration: const Duration(milliseconds: 120),
            scale: _down ? 0.93 : 1,
            child: SizedBox(
              width: 2 * d + 8,
              height: 2 * d + 8,
              child: Stack(
                alignment: Alignment.center,
                children: [
                  Transform.rotate(
                    angle: math.pi / 4,
                    child: Container(
                      width: side,
                      height: side,
                      decoration: BoxDecoration(
                        color: widget.outlined ? SsColors.canvas : null,
                        gradient: widget.outlined
                            ? null
                            : LinearGradient(
                                begin: Alignment.topLeft,
                                end: Alignment.bottomRight,
                                colors: colors,
                                stops: const [0, 0.55, 1],
                              ),
                        border: Border.all(color: main, width: 1.5),
                        boxShadow: widget.outlined
                            ? null
                            : [
                                BoxShadow(
                                  color: main.withValues(alpha: 0.4),
                                  blurRadius: 14,
                                  offset: const Offset(0, 5),
                                ),
                              ],
                      ),
                      child: widget.pulse
                          ? ClipRect(
                              child: Stack(
                                fit: StackFit.expand,
                                children: [
                                  const SsDots.onPrimary(
                                    child: SizedBox.expand(),
                                  ),
                                  FractionallySizedBox(
                                    alignment: Alignment(
                                      -2 + 4 * _pulse.value,
                                      0,
                                    ),
                                    widthFactor: 0.35,
                                    child: DecoratedBox(
                                      decoration: BoxDecoration(
                                        gradient: LinearGradient(
                                          colors: [
                                            Colors.white.withValues(alpha: 0),
                                            Colors.white.withValues(
                                              alpha: 0.35,
                                            ),
                                            Colors.white.withValues(alpha: 0),
                                          ],
                                        ),
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                            )
                          : null,
                    ),
                  ),
                  Icon(
                    widget.icon,
                    size: d * 0.8,
                    color: widget.outlined ? main : SsColors.canvas,
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

/// Inline attendee selection below the ready-to-record instructions.
class _AttendeesSelector extends ConsumerWidget {
  const _AttendeesSelector();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final chosen = ref.watch(pendingAttendeesProvider);
    final people = ref.watch(peopleProvider).value ?? const [];
    final names = {for (final p in people) p.clientId: p.name};
    Future<void> pick() async {
      final result = await showAttendeePicker(context, selected: chosen);
      if (result != null) {
        ref.read(pendingAttendeesProvider.notifier).set(result);
      }
    }

    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          OutlinedButton.icon(
            onPressed: pick,
            icon: const Icon(Icons.group_add_outlined),
            label: Text(chosen.isEmpty ? 'انتخاب حاضران' : 'ویرایش حاضران'),
          ),
          for (final id in chosen) ...[
            const SizedBox(width: 8),
            InputChip(
              label: Text(names[id] ?? 'فرد حذف‌شده'),
              onDeleted: () =>
                  ref.read(pendingAttendeesProvider.notifier).remove(id),
            ),
          ],
        ],
      ),
    );
  }
}
