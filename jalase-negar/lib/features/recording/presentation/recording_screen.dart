import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:record/record.dart' show InputDevice;

import '../../../app/theme.dart';
import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/utils/format.dart';
import '../../meetings/data/attendee.dart';
import '../../onboarding/tour_overlay.dart';
import '../../people/application/people_providers.dart';
import '../../people/presentation/attendee_picker_sheet.dart';
import '../../onboarding/tour_step.dart';
import '../application/live_engine_provider.dart';
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
        final leave = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('توقف ضبط؟'),
            content: const Text(
              'ضبط در جریان است. با خروج، ضبط متوقف و جلسه ذخیره می‌شود.',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('ادامه ضبط'),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('توقف و ذخیره'),
              ),
            ],
          ),
        );
        if (leave == true) await controller.stop();
      },
      child: Scaffold(
        appBar: SsAppBar(
          title: const Text('ضبط جلسه'),
          actions: [
            if (!isActive && !_preparing)
              Padding(
                padding: const EdgeInsetsDirectional.only(end: 8),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const TourTarget(step: TourStep.live, child: _LiveToggle()),
                    const SizedBox(width: 4),
                    _MicMenu(state: state, controller: controller),
                  ],
                ),
              ),
          ],
        ),
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
                          ? ClipRect(
                              child:
                                  widget.liveTranscript ??
                                  LiveTranscriptPanel(state: controller.live),
                            )
                          : _preparing
                          ? const SizedBox.expand()
                          : const Align(
                              alignment: Alignment.topCenter,
                              child: SingleChildScrollView(
                                child: _AttendeesCard(),
                              ),
                            ),
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
                      _RecordingMonitor(
                        state: state,
                        waveform: LiveWaveform(
                          waveform: controller.waveform,
                          active: isRecording && !state.interrupted,
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
    return IgnorePointer(
      child: Stack(
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
      ),
    );
  }

  Widget _buildIllustration(BuildContext context) {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Flexible(
          child: Padding(
            padding: const EdgeInsets.only(bottom: 20),
            child: MeetingIllustration(
              dispersed: dispersed,
              onDispersed: onDispersed,
            ),
          ),
        ),
        Visibility.maintain(
          visible: !dispersed,
          child: Column(
            children: [
              Text(
                formatDuration(Duration.zero),
                textDirection: TextDirection.ltr,
                style: Theme.of(context).textTheme.displaySmall?.copyWith(
                  fontSize: 56,
                  fontWeight: FontWeight.w300,
                  height: 1.1,
                ),
              ),
              const SizedBox(height: 14),
              Text(
                'برای شروع ضبط، دکمهٔ زیر را بزنید',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodySmall,
              ),
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
  const _RecordingMonitor({required this.state, required this.waveform});

  final RecorderState state;
  final LiveWaveform waveform;

  @override
  Widget build(BuildContext context) {
    final color = waveform.active ? SsColors.danger : SsColors.ink;
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
            Expanded(child: waveform),
          ],
        ),
      ),
    );
  }
}

/// Input device picker in the app bar: a compact button that opens a dropdown
/// of the available microphones (the current one is ticked).
class _MicMenu extends StatelessWidget {
  const _MicMenu({required this.state, required this.controller});

  final RecorderState state;
  final RecorderController controller;

  static const _refresh = '__refresh__';

  String _labelOf(InputDevice device) =>
      device.label.isEmpty ? 'میکروفون ${device.id}' : device.label;

  @override
  Widget build(BuildContext context) {
    final textStyle = Theme.of(context).textTheme.labelMedium;

    PopupMenuItem<String> item(String value, String label, {bool on = false}) {
      return PopupMenuItem<String>(
        value: value,
        height: 40,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: 18,
              child: on
                  ? const Icon(Icons.check, size: 16, color: SsColors.primary)
                  : null,
            ),
            const SizedBox(width: 6),
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 220),
              child: Text(
                label,
                overflow: TextOverflow.ellipsis,
                style: textStyle?.copyWith(
                  color: on ? SsColors.primary : SsColors.ink,
                  fontWeight: on ? FontWeight.w600 : FontWeight.w400,
                ),
              ),
            ),
          ],
        ),
      );
    }

    return PopupMenuButton<String>(
      tooltip: 'انتخاب ورودی صوتی',
      position: PopupMenuPosition.under,
      padding: EdgeInsets.zero,
      constraints: const BoxConstraints(minWidth: 200),
      onSelected: (value) {
        if (value == _refresh) {
          controller.refreshInputDevices();
        } else {
          controller.setInputDevice(value);
        }
      },
      itemBuilder: (context) => [
        item('', 'میکروفون پیش‌فرض', on: state.selectedInputDeviceId.isEmpty),
        for (final device in state.inputDevices)
          item(
            device.id,
            _labelOf(device),
            on: device.id == state.selectedInputDeviceId,
          ),
        const PopupMenuDivider(height: 1),
        PopupMenuItem<String>(
          value: _refresh,
          height: 40,
          enabled: !state.discoveringInputDevices,
          padding: const EdgeInsets.symmetric(horizontal: 12),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              const SizedBox(width: 18),
              const SizedBox(width: 6),
              const Icon(Icons.refresh, size: 16, color: SsColors.neutral),
              const SizedBox(width: 6),
              Text(
                'به‌روزرسانی لیست',
                style: textStyle?.copyWith(color: SsColors.neutral),
              ),
            ],
          ),
        ),
      ],
      child: _HeaderActionIcon(
        icon: Icons.mic_none,
        busy: state.discoveringInputDevices,
      ),
    );
  }
}

class _HeaderActionIcon extends StatelessWidget {
  const _HeaderActionIcon({required this.icon, this.busy = false});

  final IconData icon;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    return SizedBox.square(
      dimension: 44,
      child: Center(
        child: Container(
          width: 34,
          height: 34,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: SsColors.ink.withValues(alpha: 0.06),
            border: Border.all(color: SsColors.ink.withValues(alpha: 0.25)),
          ),
          child: busy
              ? const SizedBox.square(
                  dimension: 14,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : Icon(icon, size: 18, color: SsColors.primary),
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
    final main = widget.danger ? SsColors.danger : SsColors.primary;
    final colors = widget.danger
        ? const [Color(0xFFD1305A), SsColors.danger, Color(0xFF9F0F36)]
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
                  for (final offset in [0.0, 0.5])
                    Builder(
                      builder: (context) {
                        final progress = (_pulse.value + offset) % 1.0;
                        final eased = Curves.easeOut.transform(progress);
                        final ringSize = side * (1 + 0.55 * eased);
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
                                  color: main.withValues(
                                    alpha: 0.38 * (1 - progress),
                                  ),
                                  width: 1.5,
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

/// App-bar switch for live transcription; the choice is remembered.
class _LiveToggle extends ConsumerWidget {
  const _LiveToggle();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final enabled = ref.watch(liveTranscriptEnabledProvider).value ?? true;
    return IconButton(
      tooltip: enabled ? 'متن زنده روشن است' : 'متن زنده خاموش است',
      padding: EdgeInsets.zero,
      constraints: const BoxConstraints.tightFor(width: 44, height: 44),
      icon: _HeaderActionIcon(
        icon: enabled ? Icons.subtitles_outlined : Icons.subtitles_off_outlined,
      ),
      onPressed: () {
        ref.read(liveTranscriptEnabledProvider.notifier).set(!enabled);
        SsToastHost.show(
          context,
          enabled
              ? 'متن زنده خاموش شد؛ ضبط مثل قبل انجام می‌شود.'
              : 'متن زنده روشن شد؛ از ضبط بعدی متن هم‌زمان نمایش داده می‌شود.',
          queue: SsToastQueue.dismissCurrent,
        );
      },
    );
  }
}

/// Optional "who is here" card on the ready-to-record screen.
class _AttendeesCard extends ConsumerWidget {
  const _AttendeesCard();

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

    return SsCard(
      title: 'حاضران جلسه (اختیاری)',
      ripple: true,
      onTap: pick,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (chosen.isEmpty)
            const Text(
              'افراد حاضر را انتخاب کنید تا نام‌ها دقیق‌تر تشخیص داده شوند.',
            )
          else
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final id in chosen)
                  InputChip(
                    label: Text(names[id] ?? 'فرد حذف‌شده'),
                    onDeleted: () =>
                        ref.read(pendingAttendeesProvider.notifier).remove(id),
                  ),
              ],
            ),
          const SizedBox(height: 8),
          TextButton.icon(
            onPressed: pick,
            icon: const Icon(Icons.group_add_outlined),
            label: Text(chosen.isEmpty ? 'انتخاب حاضران' : 'ویرایش حاضران'),
          ),
        ],
      ),
    );
  }
}
