import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../application/live_audio_waveform.dart';

class LiveWaveform extends StatelessWidget {
  const LiveWaveform({super.key, required this.waveform, required this.active});

  final LiveAudioWaveform waveform;
  final bool active;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: active ? 'موج زندهٔ میکروفون' : 'موج میکروفون متوقف است',
      child: SizedBox(
        height: 34,
        width: double.infinity,
        child: RepaintBoundary(
          child: CustomPaint(painter: _WavePainter(waveform, active)),
        ),
      ),
    );
  }
}

class _WavePainter extends CustomPainter {
  _WavePainter(this.waveform, this.active)
    : super(repaint: active ? waveform : null);

  final LiveAudioWaveform waveform;
  final bool active;

  @override
  void paint(Canvas canvas, Size size) {
    final mid = size.height / 2;
    final color = active ? SsColors.danger : SsColors.neutral;
    final paint = Paint()..color = color.withValues(alpha: 0.25);
    canvas.drawLine(Offset(0, mid), Offset(size.width, mid), paint);
    if (!active) return;

    const count = LiveAudioWaveform.barCount;
    final step = size.width / count;
    paint.color = color;
    for (var i = 0; i < count; i++) {
      final halfHeight = waveform.amplitudeAt(i) * (mid - 2);
      if (halfHeight < 0.5) continue;
      canvas.drawRect(
        Rect.fromCenter(
          center: Offset((i + 0.5) * step, mid),
          width: math.min(step * 0.65, 3),
          height: 2 * halfHeight,
        ),
        paint,
      );
    }
  }

  @override
  bool shouldRepaint(_WavePainter oldDelegate) =>
      waveform != oldDelegate.waveform || active != oldDelegate.active;
}
