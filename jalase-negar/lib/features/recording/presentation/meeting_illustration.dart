import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_svg/flutter_svg.dart';

class MeetingIllustration extends StatefulWidget {
  const MeetingIllustration({
    super.key,
    required this.dispersed,
    required this.onDispersed,
  });

  final bool dispersed;
  final VoidCallback onDispersed;

  @override
  State<MeetingIllustration> createState() => _MeetingIllustrationState();
}

class _MeetingIllustrationState extends State<MeetingIllustration>
    with SingleTickerProviderStateMixin {
  final _artKey = GlobalKey();
  late final AnimationController _wind;
  _WindPainter? _particles;

  @override
  void initState() {
    super.initState();
    _wind =
        AnimationController(
          vsync: this,
          duration: const Duration(milliseconds: 900),
        )..addStatusListener((status) {
          if (status == AnimationStatus.completed) {
            _removeParticles();
            widget.onDispersed();
          }
        });
  }

  @override
  void didUpdateWidget(covariant MeetingIllustration oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.dispersed == widget.dispersed) return;
    if (!widget.dispersed) {
      _wind.stop();
      _removeParticles();
      return;
    }
    if (MediaQuery.disableAnimationsOf(context)) {
      _finishAfterFrame();
      return;
    }

    final art = _artKey.currentContext?.findRenderObject();
    if (art is RenderRepaintBoundary && art.hasSize && !art.size.isEmpty) {
      try {
        final snapshot = art.toImageSync();
        _particles = _WindPainter(snapshot, art.size, _wind);
        _wind.forward(from: 0);
        return;
      } catch (_) {
        // Fall through to the immediate transition if capture is unavailable.
      }
    }
    debugPrint('JN-REC-0001: Reopen the recording screen to retry the effect.');
    _finishAfterFrame();
  }

  void _finishAfterFrame() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && widget.dispersed) widget.onDispersed();
    });
  }

  void _removeParticles() {
    final particles = _particles;
    if (particles == null) return;
    setState(() => _particles = null);
    particles.image.dispose();
  }

  @override
  void dispose() {
    _wind.dispose();
    _particles?.image.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final particles = _particles;
    return ExcludeSemantics(
      child: Center(
        heightFactor: 1,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 270),
          child: AspectRatio(
            aspectRatio: 480 / 340,
            child: widget.dispersed
                ? (particles == null ? null : CustomPaint(painter: particles))
                : RepaintBoundary(
                    key: _artKey,
                    child: SvgPicture.asset(
                      'assets/images/brand/meeting-recording.svg',
                      fit: BoxFit.contain,
                    ),
                  ),
          ),
        ),
      ),
    );
  }
}

class _WindPainter extends CustomPainter {
  _WindPainter(this.image, this.originalSize, this.wind) : super(repaint: wind);

  final ui.Image image;
  final Size originalSize;
  final Animation<double> wind;
  late final _tiles = _createTiles();
  final _paint = Paint()..filterQuality = FilterQuality.low;

  List<_Tile> _createTiles() {
    final random = math.Random(20);
    final tiles = <_Tile>[];
    const side = 6.0;
    for (var y = 0.0; y < originalSize.height; y += side) {
      for (var x = 0.0; x < originalSize.width; x += side) {
        tiles.add(
          _Tile(
            Rect.fromLTWH(
              x,
              y,
              math.min(side, originalSize.width - x),
              math.min(side, originalSize.height - y),
            ),
            delay:
                (1 - x / originalSize.width) * 0.32 + random.nextDouble() * 0.1,
            drift: Offset(
              -64 - random.nextDouble() * 100,
              -14 - random.nextDouble() * 64,
            ),
            spin: (random.nextDouble() - 0.5) * 2,
          ),
        );
      }
    }
    return tiles;
  }

  @override
  void paint(Canvas canvas, Size size) {
    // Keep the fragments anchored to the idle artwork even if the body resizes.
    canvas.translate(
      (size.width - originalSize.width) / 2,
      (size.height - originalSize.height) / 2,
    );
    final transforms = <RSTransform>[];
    final sources = <Rect>[];
    final colors = <Color>[];
    for (final tile in _tiles) {
      final progress = ((wind.value - tile.delay) / (1 - tile.delay)).clamp(
        0.0,
        1.0,
      );
      final sweep = Curves.easeInSine.transform(progress);
      final fade = Curves.easeInOutSine.transform(progress);
      final drift = Offset(tile.drift.dx * sweep, tile.drift.dy * fade);
      final rect = tile.source;
      sources.add(rect);
      transforms.add(
        RSTransform.fromComponents(
          rotation: tile.spin * sweep,
          scale: 1 - fade * 0.7,
          anchorX: rect.width / 2,
          anchorY: rect.height / 2,
          translateX: rect.center.dx + drift.dx,
          translateY: rect.center.dy + drift.dy,
        ),
      );
      colors.add(Colors.white.withValues(alpha: 1 - fade));
    }
    canvas.drawAtlas(
      image,
      transforms,
      sources,
      colors,
      BlendMode.modulate,
      null,
      _paint,
    );
  }

  @override
  bool shouldRepaint(_WindPainter oldDelegate) => image != oldDelegate.image;
}

class _Tile {
  const _Tile(
    this.source, {
    required this.delay,
    required this.drift,
    required this.spin,
  });

  final Rect source;
  final double delay;
  final Offset drift;
  final double spin;
}
