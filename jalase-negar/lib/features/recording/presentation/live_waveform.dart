import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../application/live_audio_waveform.dart';

/// Live wave driven by a stream of power levels (enrollment screens).
class LevelWaveform extends StatefulWidget {
  const LevelWaveform({super.key, required this.level, required this.active});

  final double level;
  final bool active;

  @override
  State<LevelWaveform> createState() => _LevelWaveformState();
}

class _LevelWaveformState extends State<LevelWaveform> {
  final _wave = LiveAudioWaveform(sampleRate: 16000);

  @override
  void didUpdateWidget(covariant LevelWaveform old) {
    super.didUpdateWidget(old);
    if (!widget.active) {
      if (old.active) _wave.clear();
    } else {
      _wave.addPower(widget.level);
    }
  }

  @override
  void dispose() {
    _wave.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) =>
      LiveWaveform(waveform: _wave, active: widget.active);
}

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
          child: CustomPaint(
            painter: _WavePainter(
              waveform,
              active,
              dangerColor: SsColors.of(context).danger,
              neutralColor: SsColors.of(context).neutral,
            ),
          ),
        ),
      ),
    );
  }
}

class _WavePainter extends CustomPainter {
  _WavePainter(
    this.waveform,
    this.active, {
    required this.dangerColor,
    required this.neutralColor,
  }) : super(repaint: active ? waveform : null);

  final LiveAudioWaveform waveform;
  final bool active;
  final Color dangerColor;
  final Color neutralColor;

  @override
  void paint(Canvas canvas, Size size) {
    final mid = size.height / 2;
    final color = active ? dangerColor : neutralColor;
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
      waveform != oldDelegate.waveform ||
      active != oldDelegate.active ||
      dangerColor != oldDelegate.dangerColor ||
      neutralColor != oldDelegate.neutralColor;
}
