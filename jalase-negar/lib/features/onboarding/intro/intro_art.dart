import 'dart:math' as math;

import 'package:flutter/material.dart';

// Live illustrations for the first-run intro slides. They follow the panel's
// call-state art (CallStateArt.tsx): layered cards with a little thickness, a
// pedestal with a soft green glow, circuit lines with ring nodes and waveform
// clusters, all drawn on the same 480 x 340 board.

const double kIntroArtW = 480;
const double kIntroArtH = 340;

/// Loop length of every scene; scenes are written to repeat seamlessly.
const Duration kIntroArtLoop = Duration(seconds: 6);

/// Frame shown when animations are off.
const double kIntroArtStill = 0.85;

const _green = Color(0xFF4B6E48);
const _tan = Color(0xFFB2AC88);
const _cream = Color(0xFFF2F0EF);
const _rose = Color(0xFFB5543F);
const _soft = Color(0xFFE2EADD);
const _bar = Color(0xFFD3DCCD);
const _side = Color(0xFFDDE5D8);

enum IntroScene { welcome, models, record, liveText, mic, send, ready }

class IntroArt extends StatelessWidget {
  const IntroArt({
    super.key,
    required this.scene,
    required this.animation,
    this.still = false,
  });

  final IntroScene scene;
  final Animation<double> animation;

  /// Paints one fixed frame (reduced-motion setting).
  final bool still;

  @override
  Widget build(BuildContext context) {
    return ExcludeSemantics(
      child: AspectRatio(
        aspectRatio: kIntroArtW / kIntroArtH,
        child: RepaintBoundary(
          child: CustomPaint(painter: _ScenePainter(scene, animation, still)),
        ),
      ),
    );
  }
}

class _ScenePainter extends CustomPainter {
  _ScenePainter(this.scene, this.animation, this.still)
    : super(repaint: still ? null : animation);

  final IntroScene scene;
  final Animation<double> animation;
  final bool still;

  @override
  void paint(Canvas canvas, Size size) {
    final t = still ? kIntroArtStill : animation.value;
    final k = math.min(size.width / kIntroArtW, size.height / kIntroArtH);
    canvas.translate(
      (size.width - kIntroArtW * k) / 2,
      (size.height - kIntroArtH * k) / 2,
    );
    canvas.scale(k);
    _stage(canvas, t);
    switch (scene) {
      case IntroScene.welcome:
        _welcome(canvas, t);
      case IntroScene.models:
        _models(canvas, t);
      case IntroScene.record:
        _record(canvas, t);
      case IntroScene.liveText:
        _liveText(canvas, t);
      case IntroScene.mic:
        _micQuality(canvas, t);
      case IntroScene.send:
        _send(canvas, t);
      case IntroScene.ready:
        _ready(canvas, t);
    }
  }

  @override
  bool shouldRepaint(_ScenePainter old) =>
      old.scene != scene || old.still != still || old.animation != animation;
}

// ---------------------------------------------------------------- helpers

Paint _stroke(Color c, double w, {double a = 1}) => Paint()
  ..style = PaintingStyle.stroke
  ..strokeWidth = w
  ..strokeCap = StrokeCap.round
  ..strokeJoin = StrokeJoin.round
  ..color = c.withValues(alpha: a);

Paint _fill(Color c, {double a = 1}) => Paint()..color = c.withValues(alpha: a);

double _seg(double t, double a, double b) =>
    ((t - a) / (b - a)).clamp(0.0, 1.0);

double _ease(double x) => Curves.easeInOutCubic.transform(x);

double _wave(double t, double cycles, [double phase = 0]) =>
    0.5 + 0.5 * math.sin(2 * math.pi * (t * cycles) + phase);

void _dash(Canvas c, Path p, Paint paint, double on, double off) {
  for (final m in p.computeMetrics()) {
    for (var d = 0.0; d < m.length; d += on + off) {
      c.drawPath(m.extractPath(d, math.min(d + on, m.length)), paint);
    }
  }
}

void _plus(Canvas c, Offset o, double r, Paint paint) {
  c.drawLine(o.translate(0, -r), o.translate(0, r), paint);
  c.drawLine(o.translate(-r, 0), o.translate(r, 0), paint);
}

void _text(
  Canvas c,
  String s,
  Offset center,
  double size,
  Color color, {
  double scale = 1,
  double alpha = 1,
}) {
  final tp = TextPainter(
    text: TextSpan(
      text: s,
      style: TextStyle(
        fontFamily: 'Vazirmatn',
        fontSize: size,
        fontWeight: FontWeight.w600,
        color: color.withValues(alpha: alpha),
      ),
    ),
    textDirection: TextDirection.rtl,
  )..layout();
  c.save();
  c.translate(center.dx, center.dy);
  c.scale(scale);
  tp.paint(c, Offset(-tp.width / 2, -tp.height / 2));
  c.restore();
  tp.dispose();
}

/// Layered card: a thick offset edge, a pale gradient face and a green outline.
void _card(
  Canvas c,
  Rect r, {
  double radius = 8,
  bool bar = false,
  bool ghost = false,
}) {
  final rr = RRect.fromRectAndRadius(r, Radius.circular(radius));
  c.drawRRect(rr.shift(const Offset(5, 5)), _fill(_side));
  c.drawRRect(rr.shift(const Offset(5, 5)), _stroke(_green, 1.6, a: 0.7));
  c.drawRRect(
    rr,
    Paint()
      ..shader = const LinearGradient(
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
        colors: [Color(0xFFFDFDFB), Color(0xFFEEF2EA)],
      ).createShader(r),
  );
  if (ghost) {
    _dash(c, Path()..addRRect(rr), _stroke(_tan, 2.4), 5, 4);
  } else {
    c.drawRRect(rr, _stroke(_green, 2.4));
  }
  if (bar) {
    c.drawCircle(Offset(r.left + 12, r.top + 11), 2.6, _fill(_green));
    c.drawCircle(Offset(r.left + 21, r.top + 11), 2.6, _fill(_green, a: 0.6));
    c.drawCircle(Offset(r.left + 30, r.top + 11), 2.6, _fill(_green, a: 0.6));
    c.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromLTWH(r.right - 38, r.top + 8, 28, 6),
        const Radius.circular(3),
      ),
      _fill(_bar),
    );
    c.drawLine(
      Offset(r.left, r.top + 22),
      Offset(r.right, r.top + 22),
      _stroke(_tan, 1.2, a: 0.7),
    );
  }
}

void _mic(Canvas c, Offset o, double s) {
  final capsule = RRect.fromRectAndRadius(
    Rect.fromCenter(
      center: o.translate(0, -10 * s),
      width: 30 * s,
      height: 52 * s,
    ),
    Radius.circular(15 * s),
  );
  c.drawRRect(capsule, _fill(_soft));
  c.drawRRect(capsule, _stroke(_green, 2.6));
  // Grille lines on the capsule.
  for (final dy in [-16.0, -8.0, 0.0]) {
    c.drawLine(
      o.translate(-6 * s, dy * s),
      o.translate(6 * s, dy * s),
      _stroke(_green, 1.6, a: 0.45),
    );
  }
  c.drawArc(
    Rect.fromCenter(
      center: o.translate(0, -2 * s),
      width: 56 * s,
      height: 56 * s,
    ),
    0,
    math.pi,
    false,
    _stroke(_green, 2.6),
  );
  c.drawLine(
    o.translate(0, 26 * s),
    o.translate(0, 38 * s),
    _stroke(_green, 2.6),
  );
  c.drawLine(
    o.translate(-14 * s, 38 * s),
    o.translate(14 * s, 38 * s),
    _stroke(_green, 2.6),
  );
}

void _check(Canvas c, Offset center, double size, double progress, Paint p) {
  final path = Path()
    ..moveTo(center.dx - size * 0.5, center.dy + size * 0.02)
    ..lineTo(center.dx - size * 0.12, center.dy + size * 0.4)
    ..lineTo(center.dx + size * 0.55, center.dy - size * 0.36);
  for (final m in path.computeMetrics()) {
    c.drawPath(m.extractPath(0, m.length * progress), p);
  }
}

void _barsRow(
  Canvas c, {
  required double x,
  required double y,
  required int count,
  required double gap,
  required double maxH,
  required double t,
  double energy = 1,
  Color color = _green,
  double alpha = 0.75,
  double width = 3.4,
}) {
  final p = _stroke(color, width, a: alpha);
  for (var i = 0; i < count; i++) {
    final h = (2 + maxH * (0.25 + 0.75 * _wave(t, 3, i * 0.8))) * energy + 1.5;
    c.drawLine(
      Offset(x + i * gap, y - h / 2),
      Offset(x + i * gap, y + h / 2),
      p,
    );
  }
}

// ------------------------------------------------------------------ stage

void _stage(Canvas c, double t) {
  // Pedestal glow: a unit radial gradient stretched into a wide ellipse.
  c.save();
  c.translate(240, 300);
  c.scale(196, 24);
  c.drawCircle(
    Offset.zero,
    1,
    Paint()
      ..shader = RadialGradient(
        colors: [_green.withValues(alpha: 0.28), _green.withValues(alpha: 0)],
      ).createShader(Rect.fromCircle(center: Offset.zero, radius: 1)),
  );
  c.restore();

  final routes = <Path>[
    Path()
      ..moveTo(60, 64)
      ..relativeLineTo(50, 0)
      ..relativeCubicTo(14, 0, 16, 12, 30, 12),
    Path()
      ..moveTo(420, 218)
      ..relativeLineTo(-48, 0)
      ..relativeCubicTo(-14, 0, -16, -12, -30, -12),
    Path()
      ..moveTo(72, 238)
      ..relativeLineTo(38, 0)
      ..relativeCubicTo(12, 0, 16, -10, 30, -10),
    Path()
      ..moveTo(414, 82)
      ..relativeLineTo(-40, 0)
      ..relativeCubicTo(-12, 0, -16, 10, -30, 10),
  ];
  for (final r in routes) {
    c.drawPath(r, _stroke(_tan, 1.6, a: 0.9));
  }
  // A pulse travels along every circuit line towards the card.
  for (var i = 0; i < routes.length; i++) {
    final m = routes[i].computeMetrics().first;
    final u = (t * 2 + i * 0.27) % 1;
    final tan = m.getTangentForOffset(m.length * u);
    if (tan != null) {
      final a = math.sin(u * math.pi);
      c.drawCircle(tan.position, 2.8, _fill(_green, a: a));
    }
  }
  const nodes = [
    (Offset(60, 64), 6.0),
    (Offset(420, 218), 6.0),
    (Offset(72, 238), 5.0),
    (Offset(414, 82), 5.0),
  ];
  for (final (o, r) in nodes) {
    c.drawCircle(o, r, _fill(_cream));
    c.drawCircle(o, r, _stroke(_green, 2));
  }

  for (final x in [40.0, 440.0]) {
    const heights = [10.0, 20.0, 30.0, 18.0, 12.0];
    for (var i = 0; i < 5; i++) {
      final s = 0.55 + 0.45 * _wave(t, 2, i * 0.9 + (x > 240 ? 1.4 : 0));
      final h = heights[i] * s;
      final bx = x + (i - 2) * 6.0;
      c.drawLine(
        Offset(bx, 150 - h),
        Offset(bx, 150 + h),
        _stroke(_green, 4.5, a: 0.5),
      );
    }
  }

  _plus(
    c,
    const Offset(392, 44),
    6,
    _stroke(_green, 2, a: 0.5 + 0.5 * _wave(t, 2)),
  );
  _plus(
    c,
    const Offset(92, 56),
    4.5,
    _stroke(_tan, 2, a: 0.5 + 0.5 * _wave(t, 2, 2)),
  );
}

// ----------------------------------------------------------------- scenes

void _welcome(Canvas c, double t) {
  const r = Rect.fromLTWH(150, 46, 180, 206);
  _card(c, r, radius: 10, bar: true);
  c.save();
  c.clipRRect(RRect.fromRectAndRadius(r, const Radius.circular(10)));
  const center = Offset(240, 136);
  for (var k = 0; k < 3; k++) {
    final p = (t * 1.5 + k / 3) % 1;
    c.drawCircle(center, 34 + p * 50, _stroke(_tan, 2, a: (1 - p) * 0.7));
  }
  c.restore();
  _mic(c, center.translate(0, 4), 1.3);
  _barsRow(c, x: 172, y: 222, count: 18, gap: 8.4, maxH: 18, t: t);
}

void _models(Canvas c, double t) {
  const r = Rect.fromLTWH(140, 50, 200, 200);
  _card(c, r, radius: 10, bar: true);
  final progress = _ease(_seg(t, 0.05, 0.75));
  for (var i = 0; i < 2; i++) {
    final top = 84.0 + i * 74;
    final row = RRect.fromRectAndRadius(
      Rect.fromLTWH(156, top, 168, 58),
      const Radius.circular(8),
    );
    c.drawRRect(row, _fill(_soft, a: 0.7));
    c.drawRRect(row, _stroke(_green, 1.8, a: 0.8));
    // Model glyph: speech bars for the VAD, chip for the listening model.
    final icon = RRect.fromRectAndRadius(
      Rect.fromLTWH(166, top + 10, 24, 24),
      const Radius.circular(6),
    );
    c.drawRRect(icon, _fill(_green));
    final glyph = _stroke(_cream, 2);
    if (i == 0) {
      for (var b = 0; b < 4; b++) {
        final h = [4.0, 9.0, 6.0, 3.0][b];
        c.drawLine(
          Offset(172 + b * 4.2, top + 22 - h),
          Offset(172 + b * 4.2, top + 22 + h),
          glyph,
        );
      }
    } else {
      c.drawRect(Rect.fromLTWH(172, top + 16, 12, 12), glyph);
      for (final d in [175.0, 181.0]) {
        c.drawLine(Offset(d, top + 13), Offset(d, top + 16), glyph);
        c.drawLine(Offset(d, top + 28), Offset(d, top + 31), glyph);
      }
    }
    c.drawLine(
      Offset(200, top + 18),
      Offset(i == 0 ? 262 : 276, top + 18),
      _stroke(_bar, 5),
    );

    final track = RRect.fromRectAndRadius(
      Rect.fromLTWH(198, top + 36, 108, 7),
      const Radius.circular(3.5),
    );
    c.drawRRect(track, _fill(_bar));
    final done = i == 0 ? 1.0 : progress;
    if (done > 0) {
      c.drawRRect(
        RRect.fromRectAndRadius(
          Rect.fromLTWH(198, top + 36, 108 * done, 7),
          const Radius.circular(3.5),
        ),
        _fill(_green),
      );
    }
    final badge = Offset(306, top + 17);
    if (done >= 1) {
      c.drawCircle(badge, 9, _fill(_green));
      _check(c, badge, 9, 1, _stroke(_cream, 2.2));
    } else {
      // Download arrow bobbing while the model is on its way.
      final bob = 2 * math.sin(2 * math.pi * t * 4);
      final a = _stroke(_green, 2.4);
      c.drawLine(badge.translate(0, -6 + bob), badge.translate(0, 5 + bob), a);
      c.drawLine(badge.translate(-5, 0 + bob), badge.translate(0, 5 + bob), a);
      c.drawLine(badge.translate(5, 0 + bob), badge.translate(0, 5 + bob), a);
    }
  }

  // "Works offline" badge: wifi arcs struck through.
  const o = Offset(386, 140);
  c.drawCircle(o, 18, _fill(_cream));
  c.drawCircle(o, 18, _stroke(_green, 2.4));
  for (final rad in [5.0, 9.0, 13.0]) {
    c.drawArc(
      Rect.fromCircle(center: o.translate(0, 7), radius: rad),
      -math.pi * 0.75,
      math.pi / 2,
      false,
      _stroke(_green, 2),
    );
  }
  c.drawCircle(o.translate(0, 7), 1.8, _fill(_green));
  c.drawLine(o.translate(-11, -11), o.translate(11, 12), _stroke(_cream, 5));
  c.drawLine(o.translate(-11, -11), o.translate(11, 12), _stroke(_rose, 2.4));
}

void _record(Canvas c, double t) {
  const phone = Rect.fromLTWH(180, 30, 120, 236);
  _card(c, phone, radius: 22);
  c.drawRRect(
    RRect.fromRectAndRadius(
      const Rect.fromLTWH(226, 42, 28, 5),
      const Radius.circular(2.5),
    ),
    _fill(_bar),
  );

  const center = Offset(240, 120);
  final counting = t < 0.75;
  c.drawCircle(center, 38, _stroke(_tan, 3, a: 0.5));
  if (counting) {
    final digitIndex = (t / 0.25).floor().clamp(0, 2);
    final sub = (t % 0.25) / 0.25;
    final sweep = 2 * math.pi * (1 - sub);
    c.drawArc(
      Rect.fromCircle(center: center, radius: 38),
      -math.pi / 2,
      sweep,
      false,
      _stroke(_green, 3.4),
    );
    final pop = 1 + 0.28 * (1 - _ease(_seg(sub, 0, 0.3)));
    final fade = 1 - _seg(sub, 0.85, 1) * 0.6;
    _text(c, '۳۲۱'[digitIndex], center, 46, _green, scale: pop, alpha: fade);
  } else {
    final blink = 0.5 + 0.5 * math.sin(2 * math.pi * t * 6);
    c.drawCircle(center, 38, _stroke(_rose, 3.4));
    c.drawCircle(center, 15 + 2 * blink, _fill(_rose));
  }

  // Timer pill + live waveform.
  final recording = _ease(_seg(t, 0.75, 0.85));
  c.drawRRect(
    RRect.fromRectAndRadius(
      const Rect.fromLTWH(212, 170, 56, 14),
      const Radius.circular(7),
    ),
    _fill(_soft),
  );
  c.drawCircle(
    const Offset(222, 177),
    3,
    _fill(_rose, a: 0.35 + 0.65 * recording),
  );
  c.drawLine(const Offset(232, 177), const Offset(258, 177), _stroke(_bar, 4));
  _barsRow(
    c,
    x: 200,
    y: 206,
    count: 11,
    gap: 8,
    maxH: 20,
    t: t,
    energy: 0.12 + 0.88 * recording,
    alpha: 0.5 + 0.4 * recording,
  );

  // Record button with a tap ripple at the start of the loop.
  const btn = Offset(240, 242);
  c.drawCircle(btn, 15, _stroke(_green, 2.4));
  final press = 1 - 0.18 * (1 - _seg(t, 0, 0.08)) * (t < 0.08 ? 1 : 0);
  c.drawCircle(btn, 9.5 * press, _fill(_rose));
  if (t < 0.2) {
    final p = t / 0.2;
    c.drawCircle(btn, 15 + p * 16, _stroke(_rose, 2, a: (1 - p) * 0.6));
  }
}

/// A single, large clip-on (lavalier) microphone on a soft disc, with its
/// cable ending in a 3.5 mm jack, sound arcs reaching the windscreen and the
/// three recommended brands as chips underneath.
void _micQuality(Canvas c, double t) {
  const centre = Offset(240, 138);
  // Soft backdrop disc.
  c.drawCircle(
    centre,
    112,
    Paint()
      ..shader = RadialGradient(
        colors: [_soft, _soft.withValues(alpha: 0.0)],
      ).createShader(Rect.fromCircle(center: centre, radius: 112)),
  );
  c.drawCircle(centre, 100, _stroke(_tan, 1.6, a: 0.8));
  c.drawCircle(centre, 78, _stroke(_green, 1.2, a: 0.25));

  // Sound arcs arriving from the upper right.
  for (var i = 0; i < 3; i++) {
    final k = (t * 1.5 + i / 3) % 1;
    c.drawArc(
      Rect.fromCircle(center: const Offset(262, 108), radius: 50 + k * 56),
      -math.pi * 0.42,
      math.pi * 0.34,
      false,
      _stroke(_green, 2.6, a: math.sin(k * math.pi) * 0.6),
    );
  }

  // Cable: a calm S curve from the capsule to the jack.
  final cable = Path()
    ..moveTo(205, 150)
    ..cubicTo(170, 190, 215, 222, 262, 214)
    ..cubicTo(300, 207, 322, 226, 350, 244);
  c.drawPath(cable, _stroke(_green, 3.2));
  final m = cable.computeMetrics().first;
  final u = (t * 1.6) % 1;
  final tan = m.getTangentForOffset(m.length * u);
  if (tan != null) {
    c.drawCircle(tan.position, 3.6, _fill(_green, a: math.sin(u * math.pi)));
  }
  // 3.5 mm jack.
  c.save();
  c.translate(350, 244);
  c.rotate(0.62);
  final jack = RRect.fromRectAndRadius(
    const Rect.fromLTWH(0, -6, 26, 12),
    const Radius.circular(3),
  );
  c.drawRRect(jack, _fill(_soft));
  c.drawRRect(jack, _stroke(_green, 2));
  c.drawLine(const Offset(26, 0), const Offset(38, 0), _stroke(_green, 4));
  c.drawLine(const Offset(10, -6), const Offset(10, 6), _stroke(_green, 1.6));
  c.drawLine(const Offset(16, -6), const Offset(16, 6), _stroke(_green, 1.6));
  c.restore();

  // The microphone, drawn big: clip, metal capsule, foam windscreen.
  c.save();
  c.translate(240, 128);
  c.rotate(-0.5);
  c.scale(3.4);
  // Clip underneath.
  final clip = RRect.fromRectAndRadius(
    const Rect.fromLTWH(-16, 5, 26, 7),
    const Radius.circular(3),
  );
  c.drawRRect(clip.shift(const Offset(0.8, 0.8)), _fill(_side));
  c.drawRRect(clip, _fill(_tan));
  c.drawRRect(clip, _stroke(_green, 0.9));
  // Capsule with a metallic gradient.
  const capRect = Rect.fromLTWH(-24, -6, 34, 12);
  final cap = RRect.fromRectAndRadius(capRect, const Radius.circular(6));
  c.drawRRect(
    cap,
    Paint()
      ..shader = const LinearGradient(
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
        colors: [Color(0xFFFFFFFF), Color(0xFFD6DFD0), Color(0xFFAEBBA7)],
      ).createShader(capRect),
  );
  c.drawRRect(cap, _stroke(_green, 1));
  c.drawLine(
    const Offset(-14, -4),
    const Offset(-14, 4),
    _stroke(_green, 0.7, a: 0.5),
  );
  c.drawLine(
    const Offset(-10, -4),
    const Offset(-10, 4),
    _stroke(_green, 0.7, a: 0.5),
  );
  // Foam windscreen.
  const foamRect = Rect.fromLTWH(6, -9, 24, 18);
  final foam = RRect.fromRectAndRadius(foamRect, const Radius.circular(9));
  c.drawRRect(
    foam,
    Paint()
      ..shader = const LinearGradient(
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
        colors: [Color(0xFF6A6C63), Color(0xFF3F4139)],
      ).createShader(foamRect),
  );
  c.drawRRect(foam, _stroke(_green, 0.9));
  for (var i = 0; i < 9; i++) {
    final x = 11.0 + (i % 3) * 7;
    final y = -4.0 + (i ~/ 3) * 4.5;
    c.drawCircle(Offset(x, y), 0.7, _fill(const Color(0xFF9A9C92)));
  }
  c.restore();

  // Brand chips.
  const labels = ['RØDE', 'BOYA', 'Holyland'];
  const widths = [78.0, 78.0, 104.0];
  var x = 240 - (78 + 78 + 104 + 24) / 2;
  for (var i = 0; i < 3; i++) {
    final r = Rect.fromLTWH(x, 280, widths[i], 28);
    final rr = RRect.fromRectAndRadius(r, const Radius.circular(14));
    c.drawRRect(rr, _fill(_cream));
    c.drawRRect(rr, _stroke(_green, 2));
    _text(c, labels[i], r.center, 13, _green);
    x += widths[i] + 12;
  }

  // Small check on the disc.
  final badge = _ease(_seg(t, 0.15, 0.45));
  const bc = Offset(166, 96);
  c.drawCircle(bc, 17, _fill(_soft));
  c.drawCircle(bc, 17, _stroke(_green, 2.4));
  _check(c, bc, 17, badge, _stroke(_green, 3));
}

void _liveText(Canvas c, double t) {
  const r = Rect.fromLTWH(140, 46, 200, 208);
  _card(c, r, radius: 10, bar: true);

  // Closed-caption badge.
  const cc = Rect.fromLTWH(154, 66, 30, 18);
  c.drawRRect(
    RRect.fromRectAndRadius(cc, const Radius.circular(4)),
    _fill(_green),
  );
  _text(c, 'CC', cc.center, 9.5, _cream);

  const widths = [138.0, 112.0, 148.0, 90.0, 126.0];
  const right = 324.0;
  for (var i = 0; i < widths.length; i++) {
    final y = 108.0 + i * 24;
    final start = 0.04 + i * 0.17;
    final p = _ease(_seg(t, start, start + 0.15));
    if (p <= 0) continue;
    final current = p < 1 || (i == widths.length - 1);
    final len = widths[i] * p;
    c.drawLine(
      Offset(right, y),
      Offset(right - len, y),
      _stroke(current ? _green : _bar, 5, a: current ? 0.85 : 1),
    );
    if (p < 1 || i == widths.length - 1) {
      final blink = (t * 8).floor().isEven ? 1.0 : 0.25;
      c.drawLine(
        Offset(right - len - 5, y - 8),
        Offset(right - len - 5, y + 8),
        _stroke(_green, 2, a: blink),
      );
    }
  }

  _barsRow(c, x: 160, y: 232, count: 19, gap: 8.4, maxH: 14, t: t, alpha: 0.6);
}

void _send(Canvas c, double t) {
  const phone = Rect.fromLTWH(92, 104, 80, 138);
  _card(c, phone, radius: 16);
  _mic(c, const Offset(132, 150), 0.62);
  _barsRow(c, x: 110, y: 214, count: 6, gap: 8.4, maxH: 14, t: t);

  const panel = Rect.fromLTWH(296, 62, 148, 180);
  _card(c, panel, radius: 10, bar: true);
  final fill = _seg(t, 0.35, 0.95);
  c.drawLine(
    const Offset(312, 96),
    Offset(312 + 52 * _ease(_seg(fill, 0, 0.2)), 96),
    _stroke(_green, 5),
  );
  for (var i = 0; i < 5; i++) {
    final y = 120.0 + i * 20;
    final p = _ease(_seg(fill, 0.15 + i * 0.16, 0.32 + i * 0.16));
    c.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromLTWH(312, y - 3, 6, 6),
        const Radius.circular(1.5),
      ),
      _fill(_green, a: p),
    );
    c.drawLine(
      Offset(326, y),
      Offset(326 + [88.0, 70.0, 96.0, 58.0, 80.0][i] * p, y),
      _stroke(_bar, 4.5),
    );
  }

  // Cloud between the phone and the panel.
  final cloud = Path.combine(
    PathOperation.union,
    Path.combine(
      PathOperation.union,
      Path()
        ..addOval(Rect.fromCircle(center: const Offset(222, 104), radius: 13)),
      Path()
        ..addOval(Rect.fromCircle(center: const Offset(240, 95), radius: 18)),
    ),
    Path.combine(
      PathOperation.union,
      Path()
        ..addOval(Rect.fromCircle(center: const Offset(259, 104), radius: 13)),
      Path()..addRRect(
        RRect.fromRectAndRadius(
          const Rect.fromLTWH(222, 100, 37, 17),
          const Radius.circular(8),
        ),
      ),
    ),
  );
  c.drawPath(cloud, _fill(_cream));
  c.drawPath(cloud, _stroke(_green, 2.4));
  final lift = 2 * math.sin(2 * math.pi * t * 3);
  final arrow = _stroke(_green, 2.4);
  c.drawLine(Offset(240, 109 + lift), Offset(240, 95 + lift), arrow);
  c.drawLine(Offset(234, 100 + lift), Offset(240, 94 + lift), arrow);
  c.drawLine(Offset(246, 100 + lift), Offset(240, 94 + lift), arrow);

  final up = Path()
    ..moveTo(176, 150)
    ..cubicTo(198, 150, 204, 122, 222, 116);
  final down = Path()
    ..moveTo(262, 112)
    ..cubicTo(280, 116, 284, 140, 296, 140);
  _dash(c, up, _stroke(_tan, 2), 5, 5);
  _dash(c, down, _stroke(_tan, 2), 5, 5);
  final um = up.computeMetrics().first;
  final dm = down.computeMetrics().first;
  for (var i = 0; i < 3; i++) {
    final u = (t * 1.5 + i / 3) % 1;
    final (m, v) = u < 0.5 ? (um, u * 2) : (dm, (u - 0.5) * 2);
    final tan = m.getTangentForOffset(m.length * v);
    if (tan != null) {
      c.drawCircle(tan.position, 4, _fill(_green));
      c.drawCircle(tan.position, 7, _stroke(_green, 1.4, a: 0.35));
    }
  }
}

void _ready(Canvas c, double t) {
  const r = Rect.fromLTWH(150, 52, 180, 196);
  _card(c, r, radius: 10, bar: true);
  for (var i = 0; i < 2; i++) {
    final y = 204.0 + i * 20;
    c.drawLine(
      Offset(166, y),
      Offset(166 + [132.0, 96.0][i], y),
      _stroke(_bar, 5),
    );
  }

  const center = Offset(240, 128);
  for (var k = 0; k < 2; k++) {
    final p = (t * 1.2 + k / 2) % 1;
    c.drawCircle(center, 42 + p * 40, _stroke(_green, 2, a: (1 - p) * 0.45));
  }
  c.drawCircle(center, 44, _fill(_green));
  c.drawCircle(center, 44, _stroke(_cream, 4, a: 0.35));
  final draw = _ease(_seg((t * 1.2) % 1, 0.05, 0.4));
  _check(c, center, 38, draw, _stroke(_cream, 7));

  // Sparks drifting outward from the badge.
  for (var i = 0; i < 8; i++) {
    final angle = i * math.pi / 4 + 0.4;
    final p = (t * 1.2 + i * 0.07) % 1;
    final dist = 58 + p * 44;
    final o = center + Offset(math.cos(angle) * dist, math.sin(angle) * dist);
    final a = math.sin(p * math.pi);
    if (i.isEven) {
      _plus(c, o, 4, _stroke(i % 4 == 0 ? _green : _tan, 2, a: a));
    } else {
      c.drawCircle(o, 2.4, _fill(_tan, a: a));
    }
  }
}
