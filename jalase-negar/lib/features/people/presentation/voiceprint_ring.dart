import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../app/theme.dart';

/// A ring of one arc per text the person reads. Each accepted recording fills
/// its arc (animated), so the voiceprint "completes" step by step like a
/// fingerprint enrolment. The centre breathes with the microphone level while
/// recording and turns into a check mark when every required text is done.
class VoiceprintRing extends StatelessWidget {
  const VoiceprintRing({
    super.key,
    required this.filled,
    required this.required,
    required this.current,
    required this.level,
    required this.recording,
    required this.complete,
    this.size = 168,
  });

  /// Per arc: its recording is stored.
  final List<bool> filled;

  /// Per arc: the text must be read (the others only improve accuracy).
  final List<bool> required;

  /// The arc of the text on screen.
  final int current;

  /// Microphone level 0..1 while recording.
  final double level;
  final bool recording;

  /// Every required text is stored.
  final bool complete;
  final double size;

  @override
  Widget build(BuildContext context) {
    final count = filled.length;
    final pulse = recording ? math.sqrt(level.clamp(0.0, 1.0)) : 0.0;
    return SizedBox(
      width: size,
      height: size,
      child: Stack(
        alignment: Alignment.center,
        children: [
          for (var i = 0; i < count; i++)
            TweenAnimationBuilder<double>(
              tween: Tween(end: filled[i] ? 1.0 : 0.0),
              duration: const Duration(milliseconds: 700),
              curve: Curves.easeOutCubic,
              builder: (context, fill, _) => CustomPaint(
                size: Size.square(size),
                painter: _ArcPainter(
                  index: i,
                  count: count,
                  fill: fill,
                  isCurrent: i == current,
                  isRequired: required[i],
                ),
              ),
            ),
          AnimatedContainer(
            duration: const Duration(milliseconds: 120),
            width: size * (0.46 + 0.14 * pulse),
            height: size * (0.46 + 0.14 * pulse),
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: SsColors.primary.withValues(
                alpha: complete ? 1 : 0.08 + 0.2 * pulse,
              ),
            ),
            child: Icon(
              complete
                  ? Icons.check
                  : recording
                  ? Icons.graphic_eq
                  : Icons.mic_none,
              size: size * 0.24,
              color: complete ? SsColors.canvas : SsColors.primary,
            ),
          ),
        ],
      ),
    );
  }
}

class _ArcPainter extends CustomPainter {
  const _ArcPainter({
    required this.index,
    required this.count,
    required this.fill,
    required this.isCurrent,
    required this.isRequired,
  });

  final int index;
  final int count;
  final double fill;
  final bool isCurrent;
  final bool isRequired;

  @override
  void paint(Canvas canvas, Size size) {
    const stroke = 10.0;
    final rect = Rect.fromCircle(
      center: size.center(Offset.zero),
      radius: size.width / 2 - stroke,
    );
    final gap = 0.16;
    final span = 2 * math.pi / count - gap;
    final start = -math.pi / 2 + index * (2 * math.pi / count) + gap / 2;
    final base = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..strokeCap = StrokeCap.butt
      ..color = (isCurrent ? SsColors.primary : SsColors.line).withValues(
        alpha: isCurrent ? 0.35 : (isRequired ? 1 : 0.55),
      );
    canvas.drawArc(rect, start, span, false, base);
    if (fill > 0) {
      final done = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = stroke
        ..strokeCap = StrokeCap.butt
        ..color = SsColors.primary;
      canvas.drawArc(rect, start, span * fill, false, done);
    }
  }

  @override
  bool shouldRepaint(_ArcPainter old) =>
      old.fill != fill ||
      old.isCurrent != isCurrent ||
      old.index != index ||
      old.count != count;
}
