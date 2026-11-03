import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

// Port of the panel's `BrandLogo` / `logo-motion.ts`: the SedaSanj wordmark is
// "written" by nine pen strokes that reveal the artwork through a mask, with
// gold and green sparks flying off the pen. Geometry and timings are the same.

const double _kLogoW = 520;
const double _kLogoH = 189;

/// Same default as `LOGO_MOTION_DURATION` in the web panel.
const double kLogoMotionSeconds = 1.6;
const double _kTimeline = 3.65;

const String _bodyData =
    'M 305.667 92.500 C 307.457 93.524 309.771 93.000 311.833 93.000 C 316.112 93.000 320.452 92.442 324.667 93.178 C 326.504 93.654 328.292 94.714 329.511 96.168 C 330.616 97.901 331.107 100.119 330.933 102.167 C 330.323 105.087 327.418 107.768 324.500 108.388 C 318.764 109.114 312.667 107.260 307.167 109.042 C 303.468 110.858 301.661 115.746 301.137 119.833 C 300.910 121.680 300.475 123.657 301.083 125.415 C 302.425 126.548 304.586 126.034 306.333 125.860 C 308.665 125.777 311.000 125.833 313.333 125.833 C 319.842 125.833 326.535 126.487 332.833 124.847 C 334.880 124.211 336.842 123.265 338.667 122.141 C 339.911 121.319 341.050 120.184 342.500 119.833 C 345.023 121.839 347.810 123.621 350.833 124.736 C 356.222 126.326 362.123 126.490 367.667 125.579 C 371.768 124.624 375.646 122.545 379.000 120.000 C 380.668 120.812 381.926 122.293 383.500 123.275 C 385.402 124.359 387.546 124.990 389.667 125.530 C 394.041 126.325 398.554 125.833 403.000 125.833 C 410.667 125.833 418.333 125.833 426.000 125.833 C 432.167 125.833 438.333 125.833 444.500 125.833 C 451.141 125.833 458.201 125.572 464.167 122.655 C 469.841 119.423 474.428 113.665 476.582 107.500 C 478.269 101.076 477.353 93.737 474.656 87.667 C 471.902 82.366 467.092 77.820 461.667 75.322 C 455.989 73.096 449.598 73.167 443.500 73.167 C 436.369 73.167 428.906 73.500 422.333 76.266 C 414.429 80.151 407.599 86.584 402.598 93.833 C 400.862 96.399 399.300 99.087 397.865 101.833 C 396.962 103.498 396.437 105.638 394.827 106.635 C 392.928 106.738 391.196 104.741 390.430 103.000 C 389.591 100.059 390.000 96.892 390.000 93.833 C 390.000 91.594 390.952 87.923 388.826 87.218 C 382.735 87.143 375.564 88.820 371.664 93.501 C 369.923 96.037 370.547 99.567 369.619 102.500 C 368.564 105.090 366.037 107.342 363.333 108.056 C 359.400 108.778 354.423 106.725 352.303 103.333 C 350.408 99.690 350.728 95.256 349.514 91.333 C 347.611 86.206 344.049 81.237 339.333 78.467 C 333.195 75.288 325.746 75.333 318.833 75.333 C 316.222 75.333 313.611 75.333 311.000 75.333 C 309.406 75.334 307.713 75.079 306.229 75.660 C 304.969 77.298 305.667 79.767 305.667 81.833 C 305.667 85.389 305.667 88.944 305.667 92.500 Z M 418.167 106.333 C 419.516 101.227 423.690 96.504 428.500 94.322 C 433.604 92.377 439.371 93.000 444.833 93.000 C 448.008 93.000 451.369 92.521 454.333 93.657 C 456.475 94.703 458.163 97.007 458.681 99.333 C 458.890 102.012 456.926 105.069 454.500 106.225 C 450.299 107.852 445.505 106.833 441.000 106.833 C 436.167 106.833 431.333 106.833 426.500 106.833 C 423.717 106.833 420.616 107.654 418.167 106.333 Z M 47.667 88.000 C 51.426 88.751 55.333 88.167 59.167 88.167 C 66.278 88.167 73.389 88.167 80.500 88.167 C 83.611 88.167 86.722 88.167 89.833 88.167 C 92.408 88.167 95.813 88.989 96.877 91.333 C 97.157 92.410 97.100 93.633 96.686 94.666 C 95.888 95.869 94.572 96.858 93.167 97.189 C 87.481 97.834 81.722 97.167 76.000 97.167 C 70.233 97.167 64.225 97.274 58.833 99.321 C 52.523 102.086 46.694 107.345 43.953 113.667 C 41.831 119.165 41.545 125.700 43.274 131.333 C 45.364 136.416 49.282 141.191 54.167 143.710 C 57.997 145.362 62.328 145.831 66.500 145.834 C 68.523 145.861 70.705 146.434 72.565 145.639 C 73.575 144.114 73.000 141.997 73.000 140.167 C 73.000 136.944 73.000 133.722 73.000 130.500 C 71.786 129.604 70.009 130.006 68.500 129.995 C 66.982 129.914 65.431 129.418 64.168 128.572 C 62.848 127.377 61.890 125.604 61.699 123.833 C 61.729 122.286 62.403 120.710 63.371 119.503 C 66.890 115.961 73.174 117.167 78.167 117.167 C 84.279 117.167 90.438 117.544 96.500 116.756 C 98.382 116.436 100.143 115.603 101.999 115.157 C 104.276 115.786 105.366 118.478 107.167 120.008 C 110.360 122.529 114.117 124.416 118.000 125.630 C 124.343 127.092 131.329 126.649 137.500 124.576 C 140.849 123.162 143.852 120.967 146.667 118.667 C 148.697 119.120 150.098 121.021 151.833 122.169 C 154.695 123.872 157.890 125.136 161.167 125.731 C 166.302 126.439 171.756 126.117 176.667 124.455 C 180.128 123.125 183.099 120.751 186.167 118.667 C 188.088 119.599 189.573 121.246 191.333 122.455 C 193.930 124.029 196.841 125.216 199.833 125.732 C 204.581 126.382 209.596 126.076 214.167 124.638 C 217.300 123.350 220.002 121.193 222.833 119.333 C 224.481 120.171 225.788 121.560 227.333 122.575 C 229.921 124.033 232.745 125.194 235.667 125.731 C 244.090 126.894 253.747 124.202 260.166 118.626 C 263.727 115.209 266.289 110.586 267.618 105.833 C 268.761 100.391 268.333 94.727 268.333 89.167 C 268.333 85.722 268.333 82.278 268.333 78.833 C 268.333 76.812 268.912 74.524 267.882 72.785 C 265.899 71.628 263.262 72.682 261.000 73.074 C 256.268 74.011 250.686 76.400 248.785 80.833 C 246.378 87.235 248.708 94.541 247.903 101.333 C 247.182 103.999 244.386 106.308 241.667 106.788 C 238.290 106.989 233.988 104.461 233.216 101.167 C 232.682 96.083 233.000 90.945 233.000 85.833 C 233.000 84.278 233.000 82.722 233.000 81.167 C 233.000 80.113 233.132 78.716 232.288 78.086 C 225.714 77.120 217.322 80.375 214.068 86.167 C 211.936 90.840 213.883 96.541 212.548 101.500 C 211.496 104.472 207.977 106.733 204.833 106.974 C 201.542 106.816 197.801 104.050 197.087 100.833 C 196.579 95.971 197.000 91.056 197.000 86.167 C 197.000 83.772 197.771 81.029 196.500 79.000 C 189.956 79.000 181.945 80.906 178.290 86.333 C 175.946 90.752 177.661 96.440 176.026 101.167 C 174.506 104.488 170.472 106.814 166.833 107.131 C 162.760 106.991 158.296 103.705 157.023 99.833 C 156.146 95.249 156.833 90.500 156.833 85.833 C 156.833 83.941 157.058 81.975 156.500 80.167 C 152.604 79.551 148.612 80.000 144.667 80.000 C 142.132 80.000 139.001 78.917 137.083 80.575 C 136.517 82.236 136.833 84.079 136.833 85.833 C 136.833 90.278 137.519 94.811 136.631 99.167 C 135.336 103.543 130.395 107.735 125.833 107.586 C 121.980 107.136 117.850 104.641 116.124 101.167 C 114.429 96.664 115.646 91.489 114.435 86.833 C 112.652 81.236 108.740 75.843 103.667 72.882 C 98.075 69.870 91.184 70.000 84.833 70.000 C 78.766 70.000 72.484 69.413 66.667 71.138 C 62.303 72.831 58.706 76.224 55.454 79.590 C 53.741 81.312 52.003 83.010 50.320 84.762 C 49.360 85.775 48.144 86.689 47.667 88.000 Z M 275.833 125.833 L 295.167 125.333 L 294.667 42.167 C 290.828 42.167 286.831 43.077 283.500 44.986 C 280.449 46.947 277.833 49.868 276.325 53.167 C 274.771 57.462 275.333 62.266 275.333 66.833 C 275.333 73.667 275.333 80.500 275.333 87.333 C 275.333 95.667 275.333 104.000 275.333 112.333 C 275.333 115.111 275.333 117.889 275.333 120.667 C 275.333 122.397 275.012 124.310 275.833 125.833 Z';
const String _topDotData =
    'M 147.333 54.000 C 145.144 54.441 142.845 54.927 141.000 56.186 C 139.025 57.765 137.455 60.170 137.059 62.667 C 136.860 65.371 137.664 68.303 139.254 70.499 C 140.928 72.328 143.372 73.665 145.833 73.972 C 148.113 74.058 150.533 73.578 152.500 72.421 C 154.872 70.611 156.667 67.635 156.973 64.667 C 157.029 62.137 156.086 59.446 154.468 57.501 C 152.611 55.612 149.936 54.493 147.333 54.000 Z';
const String _bottomDotData =
    'M 88.833 125.833 C 86.381 126.359 83.858 127.312 82.012 129.011 C 80.330 130.880 79.220 133.486 79.171 136.000 C 79.346 140.586 84.417 145.392 89.000 145.640 C 91.637 145.429 94.351 144.279 96.272 142.460 C 97.983 140.510 99.021 137.761 98.990 135.167 C 98.793 132.603 97.396 130.022 95.495 128.292 C 93.601 126.872 91.162 126.257 88.833 125.833 Z';

/// Minimal SVG path parser: the logo only uses absolute M, L, C and Z.
Path _parsePath(String data) {
  final path = Path();
  final tokens = RegExp(
    r'[MLCZ]|-?\d*\.?\d+',
  ).allMatches(data).map((m) => m[0]!).toList();
  var i = 0;
  String? cmd;
  double n() => double.parse(tokens[i++]);
  while (i < tokens.length) {
    final t = tokens[i];
    if (RegExp(r'[MLCZ]').hasMatch(t)) {
      cmd = t;
      i++;
      if (cmd == 'Z') {
        path.close();
        continue;
      }
    }
    switch (cmd) {
      case 'M':
        path.moveTo(n(), n());
        cmd = 'L';
      case 'L':
        path.lineTo(n(), n());
      case 'C':
        path.cubicTo(n(), n(), n(), n(), n(), n());
      default:
        throw FormatException('Unsupported logo path command: $cmd');
    }
  }
  return path;
}

class _Pen {
  const _Pen(
    this.name,
    this.clip,
    this.path,
    this.width,
    this.start,
    this.time, {
    this.ease = Curves.linear,
    this.finish = false,
    this.dot = false,
  });

  final String name;
  final Rect clip;
  final String path;
  final double width;
  final double start;
  final double time;
  final Curve ease;
  final bool finish;
  final bool dot;
}

const _pens = <_Pen>[
  _Pen(
    'sad',
    Rect.fromLTRB(340, 70, 482, 130),
    'M405 116 C411 101 417 90 430 85 C436 82 444 83 452 83 C462 83 468 90 468 99 C468 110 462 116 451 116 C437 116 419 116 403 116 C391 116 381 115 380 103 C380 100 380 96 379 96 C378 96 379 104 375 110 C369 119 358 118 351 112 C345 107 342 101 340 95',
    24,
    0.06,
    1.07,
    ease: Curves.easeInOutSine,
  ),
  _Pen(
    'dal',
    Rect.fromLTRB(300, 72, 348, 130),
    'M308 84 L323 84 C348 85 348 117 322 117 L310 117',
    24,
    1.03,
    0.42,
  ),
  _Pen(
    'alef',
    Rect.fromLTRB(273, 38, 299, 130),
    'M286 51 L285 119',
    27,
    1.4,
    0.3,
  ),
  _Pen(
    'sin',
    Rect.fromLTRB(155, 71, 273, 130),
    'M258 82 L258 99 C258 123 223 124 223 89 C223 124 185 125 185 90 C185 120 160 121 153 107',
    26,
    1.67,
    0.75,
    finish: true,
  ),
  _Pen(
    'nun',
    Rect.fromLTRB(100, 77, 160, 131),
    'M147 87 L147 98 C147 123 111 124 105 101',
    25,
    2.32,
    0.35,
  ),
  _Pen(
    'jim-head',
    Rect.fromLTRB(39, 67, 116, 113),
    'M57 81 L86 80 C111 80 112 106 88 107 L66 107',
    25,
    2.62,
    0.34,
  ),
  _Pen(
    'jim-bowl',
    Rect.fromLTRB(39, 98, 105, 148),
    'M84 107 L68 107 C43 108 47 138 65 138 L70 138',
    24,
    2.9,
    0.31,
  ),
  _Pen(
    'nun-dot',
    Rect.fromLTRB(134, 51, 160, 76),
    'M147 64 L147 64.01',
    24,
    2.64,
    0.19,
    ease: Curves.easeOutSine,
    dot: true,
  ),
  _Pen(
    'jim-dot',
    Rect.fromLTRB(76, 123, 102, 149),
    'M89 136 L89 136.01',
    24,
    3.22,
    0.19,
    ease: Curves.easeOutSine,
    dot: true,
  ),
];

class _Geometry {
  _Geometry._() {
    body.fillType = PathFillType.evenOdd;
    for (final pen in _pens) {
      final p = _parsePath(pen.path);
      final metric = p.computeMetrics().first;
      paths.add(p);
      metrics.add(metric);
    }
  }

  static final _Geometry instance = _Geometry._();

  final Path body = _parsePath(_bodyData);
  final Path topDot = _parsePath(_topDotData);
  final Path bottomDot = _parsePath(_bottomDotData);
  final List<Path> paths = [];
  final List<ui.PathMetric> metrics = [];
}

class _Spark {
  _Spark(this.x, this.y, this.vx, this.vy, this.radius, this.life, this.color);

  double x, y, vx, vy;
  final double radius, life;
  final Color color;
  double age = 0;
}

/// Drives the pen timeline and the sparks. Time starts when [start] is called.
class _LogoMotion extends ChangeNotifier {
  _LogoMotion({required this.speed, required this.onComplete});

  final double speed;
  final VoidCallback? onComplete;
  final _geo = _Geometry.instance;
  final _rng = math.Random();
  final sparks = <_Spark>[];
  late final List<double> progress = List.filled(_pens.length, 0);
  late final List<double> _previous = List.filled(_pens.length, 0);
  late final List<double> _emission = List.filled(_pens.length, 0);
  final List<double> coverage = List.filled(_pens.length, 0);
  double finishRect = 0;
  bool completed = false;
  double _tail = 0;
  double _t = 0;
  Duration _last = Duration.zero;
  Ticker? _ticker;

  void start(TickerProvider vsync) {
    _ticker = vsync.createTicker(_tick)..start();
  }

  void showFinished() {
    for (var i = 0; i < _pens.length; i++) {
      progress[i] = 1;
      coverage[i] = 1;
    }
    finishRect = 1;
    completed = true;
    onComplete?.call();
  }

  void _tick(Duration elapsed) {
    final dt = math.min((elapsed - _last).inMicroseconds / 1e6, 0.04);
    _last = elapsed;
    _t += dt;
    for (var i = 0; i < _pens.length; i++) {
      final pen = _pens[i];
      final raw = ((_t - pen.start * speed) / (pen.time * speed)).clamp(
        0.0,
        1.0,
      );
      progress[i] = pen.ease.transform(raw);
      if (pen.finish) {
        final f = ((_t - (pen.start + pen.time - 0.1) * speed) / (0.1 * speed))
            .clamp(0.0, 1.0);
        coverage[i] = Curves.easeInOutSine.transform(f);
      }
    }
    finishRect = Curves.easeOut.transform(
      ((_t - 3.41 * speed) / (0.08 * speed)).clamp(0.0, 1.0),
    );
    _emit();
    _advance(dt);
    if (!completed && _t >= _kTimeline * speed) {
      completed = true;
      onComplete?.call();
    }
    if (completed) {
      _tail += dt;
      if (sparks.isEmpty || _tail > 1.1) {
        _ticker?.stop();
      }
    }
    notifyListeners();
  }

  void _emit() {
    for (var i = 0; i < _pens.length; i++) {
      final pen = _pens[i];
      final metric = _geo.metrics[i];
      final dp = progress[i] - _previous[i];
      _emission[i] += pen.dot ? dp * 28 : dp * metric.length / 2.5;
      final count = math.min(7, _emission[i].floor());
      _emission[i] -= count;
      for (var k = 0; k < count && sparks.length < 160; k++) {
        final p = _previous[i] + dp * (k + 1) / count;
        final tangent = metric.getTangentForOffset(
          metric.length * p.clamp(0.0, 1.0),
        );
        if (tangent == null) continue;
        _spawn(tangent.position, tangent.vector, pen.width, pen.dot);
      }
      _previous[i] = progress[i];
    }
  }

  void _spawn(Offset point, Offset tangent, double width, bool dot) {
    final mag = tangent.distance == 0 ? 1.0 : tangent.distance;
    final side = _rng.nextBool() ? -1.0 : 1.0;
    var nx = -tangent.dy / mag * side;
    var ny = tangent.dx / mag * side;
    if (dot) {
      final a = _rng.nextDouble() * math.pi * 2;
      nx = math.cos(a);
      ny = math.sin(a);
    }
    var distance = width / 2 + 3;
    var x = point.dx + nx * distance;
    var y = point.dy + ny * distance;
    for (var a = 0; a < 5 && _geo.body.contains(Offset(x, y)); a++) {
      distance += 5;
      x = point.dx + nx * distance;
      y = point.dy + ny * distance;
    }
    sparks.add(
      _Spark(
        x,
        y,
        nx * (18 + _rng.nextDouble() * 32) - 6,
        ny * (18 + _rng.nextDouble() * 30),
        1 + _rng.nextDouble() * 2.3,
        0.48 + _rng.nextDouble() * 0.5,
        _rng.nextDouble() > 0.25
            ? const Color(0xFFA98540)
            : const Color(0xFF4B6E48),
      ),
    );
  }

  void _advance(double dt) {
    for (var i = sparks.length - 1; i >= 0; i--) {
      final s = sparks[i];
      s.age += dt;
      if (s.age >= s.life) {
        sparks.removeAt(i);
        continue;
      }
      final decay = math.exp(-1.7 * dt);
      s.vx *= decay;
      s.vy *= decay;
      s.x += s.vx * dt;
      s.y += s.vy * dt;
    }
  }

  @override
  void dispose() {
    _ticker?.dispose();
    super.dispose();
  }
}

class _LogoPainter extends CustomPainter {
  _LogoPainter(this.motion, this.color) : super(repaint: motion);

  final _LogoMotion motion;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final geo = _Geometry.instance;
    canvas.save();
    canvas.scale(size.width / _kLogoW);
    const bounds = Rect.fromLTWH(0, 0, _kLogoW, _kLogoH);

    Paint white([double opacity = 1]) =>
        Paint()..color = Colors.white.withValues(alpha: opacity);

    Paint stroke(_Pen pen, double w) => Paint()
      ..color = Colors.white
      ..style = PaintingStyle.stroke
      ..strokeWidth = w
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;

    void drawPens(bool dots, bool topDot) {
      for (var i = 0; i < _pens.length; i++) {
        final pen = _pens[i];
        if (pen.dot != dots) continue;
        if (dots && (pen.name == 'nun-dot') != topDot) continue;
        final p = motion.progress[i];
        canvas.save();
        canvas.clipRect(pen.clip);
        if (pen.dot) {
          if (p > 0) {
            final c = geo.metrics[i].getTangentForOffset(0)!.position;
            canvas.drawCircle(c, pen.width * p / 2, white());
          }
        } else if (p > 0) {
          final metric = geo.metrics[i];
          canvas.drawPath(
            metric.extractPath(0, metric.length * p),
            stroke(pen, pen.width),
          );
        }
        canvas.restore();
        if (pen.finish && motion.coverage[i] > 0) {
          canvas.drawRect(pen.clip, white(motion.coverage[i]));
        }
      }
    }

    // Artwork is revealed only where the pen strokes (the mask) have passed:
    // draw it, then composite the mask layer with dstIn.
    final maskPaint = Paint()..blendMode = BlendMode.dstIn;

    canvas.saveLayer(bounds, Paint());
    canvas.drawPath(geo.body, Paint()..color = color);
    canvas.saveLayer(bounds, maskPaint);
    drawPens(false, false);
    if (motion.finishRect > 0) {
      canvas.drawRect(bounds, white(motion.finishRect));
    }
    canvas.restore();
    canvas.restore();

    canvas.saveLayer(bounds, Paint());
    canvas.drawPath(geo.topDot, Paint()..color = color);
    canvas.saveLayer(bounds, maskPaint);
    drawPens(true, true);
    canvas.restore();
    canvas.restore();

    canvas.saveLayer(bounds, Paint());
    canvas.drawPath(geo.bottomDot, Paint()..color = color);
    canvas.saveLayer(bounds, maskPaint);
    drawPens(true, false);
    canvas.restore();
    canvas.restore();

    for (final s in motion.sparks) {
      final remaining = 1 - s.age / s.life;
      final fadeIn = math.min(s.age / 0.06, 1.0);
      final alpha = remaining * remaining * fadeIn * 0.85;
      canvas.drawCircle(
        Offset(s.x, s.y),
        s.radius * (0.65 + remaining * 0.35),
        Paint()..color = s.color.withValues(alpha: alpha.clamp(0.0, 1.0)),
      );
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(_LogoPainter old) =>
      old.color != color || old.motion != motion;
}

class _StaticLogoPainter extends CustomPainter {
  const _StaticLogoPainter(this.color);

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final geo = _Geometry.instance;
    canvas.scale(size.width / _kLogoW);
    final paint = Paint()..color = color;
    canvas.drawPath(geo.body, paint);
    canvas.drawPath(geo.topDot, paint);
    canvas.drawPath(geo.bottomDot, paint);
  }

  @override
  bool shouldRepaint(_StaticLogoPainter old) => old.color != color;
}

/// The SedaSanj wordmark. With [animated] it is written stroke by stroke with
/// sparks, exactly like the web panel's `BrandLogo animated`.
class SsBrandLogo extends StatefulWidget {
  const SsBrandLogo({
    super.key,
    required this.width,
    this.color = const Color(0xFF101113),
    this.animated = true,
    this.seconds = kLogoMotionSeconds,
    this.onComplete,
  });

  final double width;
  final Color color;
  final bool animated;
  final double seconds;
  final VoidCallback? onComplete;

  @override
  State<SsBrandLogo> createState() => _SsBrandLogoState();
}

class _SsBrandLogoState extends State<SsBrandLogo>
    with SingleTickerProviderStateMixin {
  _LogoMotion? _motion;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!widget.animated || _motion != null) return;
    final motion = _LogoMotion(
      speed: math.max(widget.seconds, 0.5) / _kTimeline,
      onComplete: widget.onComplete,
    );
    _motion = motion;
    if (MediaQuery.disableAnimationsOf(context)) {
      WidgetsBinding.instance.addPostFrameCallback(
        (_) => motion.showFinished(),
      );
    } else {
      motion.start(this);
    }
  }

  @override
  void dispose() {
    _motion?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final size = Size(widget.width, widget.width * _kLogoH / _kLogoW);
    final motion = _motion;
    return Semantics(
      label: 'صدا سنج',
      image: true,
      child: ExcludeSemantics(
        child: RepaintBoundary(
          child: CustomPaint(
            size: size,
            painter: motion == null
                ? _StaticLogoPainter(widget.color)
                : _LogoPainter(motion, widget.color),
          ),
        ),
      ),
    );
  }
}
