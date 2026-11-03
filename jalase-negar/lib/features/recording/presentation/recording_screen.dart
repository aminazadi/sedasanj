import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:record/record.dart' show InputDevice;

import '../../../app/theme.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/utils/format.dart';
import '../application/recorder_controller.dart';
import 'meeting_illustration.dart';

class RecordingScreen extends ConsumerWidget {
  const RecordingScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(recorderControllerProvider);
    final controller = ref.read(recorderControllerProvider.notifier);

    ref.listen(recorderControllerProvider, (previous, next) {
      if (next.savedMeetingId != null) {
        context.pushReplacement('/meeting/${next.savedMeetingId}');
      }
      if (next.error != null && next.error != previous?.error) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(next.error!)));
      }
    });

    final isRecording = state.status == RecorderStatus.recording;
    final isPaused = state.status == RecorderStatus.paused;
    final isSaving = state.status == RecorderStatus.saving;

    final isActive = isRecording || isPaused || isSaving;

    return PopScope(
      canPop: !isActive,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop || isSaving) return;
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
            if (state.status == RecorderStatus.idle)
              _MicMenu(state: state, controller: controller),
          ],
        ),
        body: SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
            child: Column(
              children: [
                Expanded(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      if (state.status == RecorderStatus.idle) ...[
                        const Flexible(
                          child: Padding(
                            padding: EdgeInsets.only(bottom: 20),
                            child: MeetingIllustration(),
                          ),
                        ),
                      ],
                      Text(
                        formatDuration(state.elapsed),
                        style: Theme.of(context).textTheme.displaySmall
                            ?.copyWith(
                              fontSize: 56,
                              fontWeight: FontWeight.w300,
                              height: 1.1,
                              color: isRecording
                                  ? SsColors.danger
                                  : SsColors.ink,
                            ),
                      ),
                      if (isRecording || isPaused) ...[
                        const SizedBox(height: 22),
                        _WavePanel(
                          level: controller.level,
                          active: isRecording && !state.interrupted,
                          paused: isPaused || state.interrupted,
                        ),
                      ],
                      const SizedBox(height: 14),
                      Text(
                        switch (state.status) {
                          RecorderStatus.idle =>
                            'برای شروع ضبط، دکمه‌ی زیر را بزنید',
                          RecorderStatus.recording =>
                            state.interrupted
                                ? 'ضبط توسط سیستم متوقف شد (تماس یا برنامه‌ی دیگر)؛ پس از پایان خودکار ادامه می‌یابد'
                                : 'گوشی را نزدیک سخنران‌ها نگه دارید',
                          RecorderStatus.paused => 'ضبط متوقف شده است',
                          RecorderStatus.saving =>
                            'در حال ذخیره‌ی جلسه، لطفاً صبر کنید…',
                        },
                        textAlign: TextAlign.center,
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ],
                  ),
                ),
                SizedBox(
                  height: 150,
                  child: Center(
                    child: switch (state.status) {
                      RecorderStatus.idle => _ControlColumn(
                        label: 'شروع ضبط',
                        child: _DiamondButton(
                          pulse: true,
                          half: 38,
                          icon: Icons.mic,
                          onTap: controller.start,
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
          ),
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
    final selected = state.inputDevices
        .where((d) => d.id == state.selectedInputDeviceId)
        .firstOrNull;
    final current = state.selectedInputDeviceId.isEmpty || selected == null
        ? 'میکروفون پیش‌فرض'
        : _labelOf(selected);
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

    return Padding(
      padding: const EdgeInsetsDirectional.only(end: 12),
      child: Center(
        child: PopupMenuButton<String>(
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
            item(
              '',
              'میکروفون پیش‌فرض',
              on: state.selectedInputDeviceId.isEmpty,
            ),
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
          child: Container(
            height: 34,
            padding: const EdgeInsets.symmetric(horizontal: 10),
            decoration: BoxDecoration(
              color: SsColors.ink.withValues(alpha: 0.06),
              border: Border.all(color: SsColors.ink.withValues(alpha: 0.25)),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.mic_none, size: 18, color: SsColors.primary),
                const SizedBox(width: 6),
                ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 120),
                  child: Text(
                    current,
                    overflow: TextOverflow.ellipsis,
                    style: textStyle,
                  ),
                ),
                const SizedBox(width: 2),
                state.discoveringInputDevices
                    ? const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.arrow_drop_down, size: 20),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Framed live waveform: mirrored rounded bars scrolling with the input level.
class _WavePanel extends StatefulWidget {
  const _WavePanel({
    required this.level,
    required this.active,
    required this.paused,
  });

  final ValueListenable<double> level;
  final bool active;
  final bool paused;

  @override
  State<_WavePanel> createState() => _WavePanelState();
}

class _WavePanelState extends State<_WavePanel> {
  static const _bars = 64;
  final List<double> _history = List.filled(_bars, 0);
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _sync();
  }

  @override
  void didUpdateWidget(_WavePanel old) {
    super.didUpdateWidget(old);
    _sync();
  }

  void _sync() {
    if (widget.active && _timer == null) {
      _timer = Timer.periodic(const Duration(milliseconds: 70), (_) {
        _history
          ..removeAt(0)
          ..add(widget.level.value);
        setState(() {});
      });
    } else if (!widget.active && _timer != null) {
      _timer!.cancel();
      _timer = null;
      if (!widget.paused) _history.fillRange(0, _bars, 0);
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final color = widget.active
        ? SsColors.danger
        : widget.paused
        ? SsColors.warning
        : SsColors.neutral;
    return SizedBox(
      height: 110,
      width: double.infinity,
      child: RepaintBoundary(
        child: CustomPaint(painter: _WavePainter(_history, color)),
      ),
    );
  }
}

class _WavePainter extends CustomPainter {
  _WavePainter(this.values, this.color);

  final List<double> values;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final mid = size.height / 2;
    final maxH = size.height - 8;
    final n = values.length;
    final dx = size.width / (n - 1);

    // Baseline.
    canvas.drawLine(
      Offset(0, mid),
      Offset(size.width, mid),
      Paint()
        ..color = color.withValues(alpha: 0.25)
        ..strokeWidth = 1,
    );

    double half(int i) => math.max(1.0, values[i] * maxH / 2);

    // Smooth mirrored envelope: top edge left->right, bottom edge back.
    final top = <Offset>[
      for (var i = 0; i < n; i++) Offset(i * dx, mid - half(i)),
    ];
    final bottom = <Offset>[
      for (var i = n - 1; i >= 0; i--) Offset(i * dx, mid + half(i)),
    ];
    Path smooth(List<Offset> pts, Path path, {bool moveFirst = true}) {
      if (moveFirst) {
        path.moveTo(pts.first.dx, pts.first.dy);
      } else {
        path.lineTo(pts.first.dx, pts.first.dy);
      }
      for (var i = 1; i < pts.length - 1; i++) {
        final m = Offset(
          (pts[i].dx + pts[i + 1].dx) / 2,
          (pts[i].dy + pts[i + 1].dy) / 2,
        );
        path.quadraticBezierTo(pts[i].dx, pts[i].dy, m.dx, m.dy);
      }
      path.lineTo(pts.last.dx, pts.last.dy);
      return path;
    }

    final path = smooth(top, Path());
    smooth(bottom, path, moveFirst: false);
    path.close();

    final shader = LinearGradient(
      colors: [color.withValues(alpha: 0.05), color.withValues(alpha: 0.9)],
    ).createShader(Offset.zero & size);
    canvas.drawPath(path, Paint()..shader = shader);
  }

  @override
  bool shouldRepaint(_WavePainter old) => true;
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
