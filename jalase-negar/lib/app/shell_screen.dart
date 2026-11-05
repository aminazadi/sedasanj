import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../features/onboarding/tour_overlay.dart';
import '../features/onboarding/tour_step.dart';
import '../features/people/application/people_providers.dart';
import '../features/upload/upload_controller.dart';
import 'theme.dart';
import 'widgets/brand_logo.dart';
import 'widgets/ss_widgets.dart';

class ShellScreen extends ConsumerWidget {
  const ShellScreen({super.key, required this.child});

  final Widget child;

  int _currentIndex(BuildContext context) {
    final location = GoRouterState.of(context).uri.path;
    if (location.startsWith('/settings')) return 1;
    return 0;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Keeps the upload queue alive for the whole app session.
    ref.watch(uploadQueueProvider.select((s) => s.running));
    // Keeps people sync alive for the whole session.
    ref.watch(speakerSyncProvider.select((s) => s.running));
    final index = _currentIndex(context);

    return Scaffold(
      // Every tab scrolls behind the bar so it stays visible through the notch
      // under the record button; tabs pad their scroll content by
      // MediaQuery.paddingOf(context).bottom, which the Scaffold sets to the
      // bar height.
      extendBody: true,
      appBar: SsAppBar(
        title: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Same animated wordmark as the web panel's sidebar.
            const Padding(
              padding: EdgeInsetsDirectional.only(start: 16),
              child: SsBrandLogo(width: 104),
            ),
          ],
        ),
        centerTitle: false,
        actions: [
          Padding(
            padding: const EdgeInsetsDirectional.only(end: 12),
            child: Center(
              child: Semantics(
                button: true,
                label: 'دانلود مدل‌ها',
                child: InkWell(
                  onTap: () => context.push('/models'),
                  child: Container(
                    height: 34,
                    padding: const EdgeInsets.symmetric(horizontal: 10),
                    decoration: BoxDecoration(
                      color: SsColors.ink.withValues(alpha: 0.06),
                      border: Border.all(
                        color: SsColors.ink.withValues(alpha: 0.25),
                      ),
                    ),
                    child: const Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.file_download_outlined, size: 19),
                        SizedBox(width: 6),
                        Text(
                          'دانلود مدل‌ها',
                          style: TextStyle(
                            fontFamily: 'Vazirmatn',
                            fontSize: 12.5,
                            fontWeight: FontWeight.w500,
                            color: SsColors.ink,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
      body: child,
      bottomNavigationBar: _SsBottomBar(
        selectedIndex: index,
        onSelected: (i) => context.go(i == 0 ? '/' : '/settings'),
        onRecord: () => context.push('/record'),
      ),
    );
  }
}

enum _Glyph { sessions, settings, mic }

/// Hand-drawn 24-grid line icons so the bar does not depend on stock Material
/// glyphs (the old mic tab duplicated the record button).
class _GlyphPainter extends CustomPainter {
  _GlyphPainter(this.glyph, this.color, {this.filled = false});

  final _Glyph glyph;
  final Color color;
  final bool filled;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 24);
    final line = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.8
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    final fill = Paint()..color = color;

    switch (glyph) {
      case _Glyph.sessions:
        // Voice waveform: five rounded bars, tallest in the middle.
        const bars = [6.0, 11.0, 17.0, 11.0, 6.0];
        final bar = Paint()
          ..color = color
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2.4
          ..strokeCap = StrokeCap.round;
        for (var i = 0; i < bars.length; i++) {
          final x = 4 + i * 4.0;
          canvas.drawLine(
            Offset(x, 12 - bars[i] / 2),
            Offset(x, 12 + bars[i] / 2),
            bar,
          );
        }
      case _Glyph.settings:
        const rows = [(6.5, 15.0), (12.0, 8.5), (17.5, 16.0)];
        for (final (y, kx) in rows) {
          canvas.drawLine(Offset(4, y), Offset(kx - 2.7, y), line);
          canvas.drawLine(Offset(kx + 2.7, y), Offset(20, y), line);
          if (filled) canvas.drawCircle(Offset(kx, y), 2.2, fill);
          canvas.drawCircle(Offset(kx, y), 2.2, filled ? fill : line);
        }
      case _Glyph.mic:
        final body = RRect.fromRectAndRadius(
          const Rect.fromLTWH(8.8, 2.8, 6.4, 11.4),
          const Radius.circular(3.2),
        );
        if (filled) {
          canvas.drawRRect(body, fill);
        } else {
          canvas.drawRRect(body, line);
        }
        canvas.drawArc(
          Rect.fromCircle(center: const Offset(12, 11), radius: 6.8),
          0.12,
          math.pi - 0.24,
          false,
          line,
        );
        canvas.drawLine(const Offset(12, 17.8), const Offset(12, 21), line);
        canvas.drawLine(const Offset(8.6, 21), const Offset(15.4, 21), line);
    }
  }

  @override
  bool shouldRepaint(_GlyphPainter old) =>
      old.glyph != glyph || old.color != color || old.filled != filled;
}

class _GlyphIcon extends StatelessWidget {
  const _GlyphIcon(
    this.glyph,
    this.color, {
    this.filled = false,
    this.size = 27,
  });

  final _Glyph glyph;
  final Color color;
  final bool filled;
  final double size;

  @override
  Widget build(BuildContext context) => CustomPaint(
    size: Size.square(size),
    painter: _GlyphPainter(glyph, color, filled: filled),
  );
}

/// Bar silhouette: a straight top edge that drops along a 45° V under the
/// diamond record button, leaving a thin gap between the V and the diamond.
class _BarPainter extends CustomPainter {
  _BarPainter({required this.lift, required this.half});

  final double lift;

  /// Half the width of the V; equal to the diamond's half-diagonal so the V
  /// runs parallel to the diamond's lower edges.
  final double half;

  @override
  void paint(Canvas canvas, Size size) {
    final cx = size.width / 2;
    final edge = Path()
      ..moveTo(0, lift)
      ..lineTo(cx - half, lift)
      ..lineTo(cx, lift + half)
      ..lineTo(cx + half, lift)
      ..lineTo(size.width, lift);
    final body = Path.from(edge)
      ..lineTo(size.width, size.height)
      ..lineTo(0, size.height)
      ..close();
    canvas.drawShadow(
      body,
      SsColors.primaryDark.withValues(alpha: 0.55),
      10,
      false,
    );
    canvas.drawPath(body, Paint()..color = SsColors.canvas);
    canvas.drawPath(
      edge,
      Paint()
        ..color = SsColors.line
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1
        ..strokeJoin = StrokeJoin.miter,
    );
  }

  @override
  bool shouldRepaint(_BarPainter old) => old.lift != lift || old.half != half;
}

/// Brand bottom bar: canvas surface whose top edge dips into a V under a
/// raised diamond record button, with hand-drawn icons and a soft active pill.
class _SsBottomBar extends StatelessWidget {
  const _SsBottomBar({
    required this.selectedIndex,
    required this.onSelected,
    required this.onRecord,
  });

  final int selectedIndex;
  final ValueChanged<int> onSelected;
  final VoidCallback onRecord;

  static const _bar = 72.0;
  static const _lift = 60.0;
  static const _half = 38.0;
  static const _slotWidth = 132.0;

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.paddingOf(context).bottom;
    return SizedBox(
      height: _bar + _lift + bottom,
      child: Stack(
        children: [
          Positioned.fill(
            child: CustomPaint(
              painter: _BarPainter(lift: _lift, half: _half),
            ),
          ),
          Positioned(
            left: 0,
            right: 0,
            bottom: bottom,
            height: _bar,
            child: Row(
              children: [
                Expanded(
                  child: TourTarget(
                    step: TourStep.meetings,
                    child: _NavTab(
                      glyph: _Glyph.sessions,
                      label: 'جلسات',
                      selected: selectedIndex == 0,
                      onTap: () => onSelected(0),
                    ),
                  ),
                ),
                const SizedBox(width: _slotWidth),
                Expanded(
                  child: _NavTab(
                    glyph: _Glyph.settings,
                    label: 'تنظیمات',
                    selected: selectedIndex == 1,
                    onTap: () => onSelected(1),
                  ),
                ),
              ],
            ),
          ),
          Positioned(
            top: 0,
            bottom: bottom,
            left: 0,
            right: 0,
            child: Align(
              alignment: Alignment.topCenter,
              child: _RecordSlot(
                onTap: onRecord,
                lift: _lift,
                half: _half,
                width: _slotWidth,
                height: _lift + _bar,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _NavTab extends StatelessWidget {
  const _NavTab({
    required this.glyph,
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final _Glyph glyph;
  final String label;
  final bool selected;
  final VoidCallback onTap;

  static const _anim = Duration(milliseconds: 280);

  @override
  Widget build(BuildContext context) {
    final color = selected ? SsColors.primary : SsColors.neutral;
    return Semantics(
      button: true,
      selected: selected,
      label: label,
      child: InkWell(
        onTap: onTap,
        splashFactory: NoSplash.splashFactory,
        highlightColor: Colors.transparent,
        hoverColor: Colors.transparent,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            TweenAnimationBuilder<Color?>(
              duration: _anim,
              curve: Curves.easeOutCubic,
              tween: ColorTween(end: color),
              builder: (context, c, _) => _GlyphIcon(glyph, c ?? color),
            ),
            const SizedBox(height: 4),
            AnimatedDefaultTextStyle(
              duration: _anim,
              style: TextStyle(
                fontFamily: 'Vazirmatn',
                fontSize: 12,
                height: 1.2,
                fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
                color: color,
              ),
              child: Text(label),
            ),
          ],
        ),
      ),
    );
  }
}

class _RecordSlot extends StatefulWidget {
  const _RecordSlot({
    required this.onTap,
    required this.lift,
    required this.half,
    required this.width,
    required this.height,
  });

  final VoidCallback onTap;
  final double lift;
  final double half;
  final double width;
  final double height;

  @override
  State<_RecordSlot> createState() => _RecordSlotState();
}

class _RecordSlotState extends State<_RecordSlot>
    with SingleTickerProviderStateMixin {
  late final AnimationController _pulse = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 2400),
  )..repeat();
  bool _down = false;

  @override
  void dispose() {
    _pulse.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final d = widget.half;
    // Square side whose 45° rotation has half-diagonal d.
    final side = d * math.sqrt2;
    // The diamond's centre sits above the bar's top edge, as in the sketch.
    final centerY = widget.lift - 0.4 * d;
    return Semantics(
      button: true,
      label: 'ضبط جلسه',
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTapDown: (_) => setState(() => _down = true),
        onTapCancel: () => setState(() => _down = false),
        onTapUp: (_) => setState(() => _down = false),
        onTap: widget.onTap,
        child: SizedBox(
          width: widget.width,
          height: widget.height,
          child: AnimatedScale(
            duration: const Duration(milliseconds: 120),
            scale: _down ? 0.94 : 1,
            alignment: Alignment(0, (centerY / widget.height) * 2 - 1),
            child: Stack(
              clipBehavior: Clip.none,
              children: [
                Positioned(
                  left: widget.width / 2 - d,
                  top: centerY - d,
                  width: 2 * d,
                  height: 2 * d,
                  child: Stack(
                    alignment: Alignment.center,
                    clipBehavior: Clip.none,
                    children: [
                      AnimatedBuilder(
                        animation: _pulse,
                        builder: (context, _) {
                          final t = Curves.easeOut.transform(_pulse.value);
                          final s = side + 12 * t;
                          return Transform.rotate(
                            angle: math.pi / 4,
                            child: Container(
                              width: s,
                              height: s,
                              decoration: BoxDecoration(
                                border: Border.all(
                                  color: SsColors.primary.withValues(
                                    alpha: 0.35 * (1 - t),
                                  ),
                                ),
                              ),
                            ),
                          );
                        },
                      ),
                      Transform.rotate(
                        angle: math.pi / 4,
                        child: Container(
                          width: side,
                          height: side,
                          decoration: BoxDecoration(
                            gradient: const LinearGradient(
                              begin: Alignment.topLeft,
                              end: Alignment.bottomRight,
                              colors: [
                                SsColors.primaryLight,
                                SsColors.primary,
                                SsColors.primaryDark,
                              ],
                              stops: [0, 0.55, 1],
                            ),
                            border: Border.all(
                              color: SsColors.primary,
                              width: 1.5,
                            ),
                            boxShadow: const [
                              BoxShadow(
                                color: Color(0x663E5C3B),
                                blurRadius: 14,
                                offset: Offset(0, 5),
                              ),
                            ],
                          ),
                          child: const SsDots.onPrimary(
                            child: SizedBox.expand(),
                          ),
                        ),
                      ),
                      const _GlyphIcon(
                        _Glyph.mic,
                        SsColors.canvas,
                        filled: true,
                        size: 34,
                      ),
                    ],
                  ),
                ),
                // Aligned with the other tabs' labels.
                Positioned(
                  left: 0,
                  right: 0,
                  top: widget.lift + 43,
                  child: const Text(
                    'ضبط جلسه',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontFamily: 'Vazirmatn',
                      fontSize: 12,
                      height: 1.2,
                      fontWeight: FontWeight.w600,
                      color: SsColors.primary,
                    ),
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
