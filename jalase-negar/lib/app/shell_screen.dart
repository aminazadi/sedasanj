import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../features/upload/upload_controller.dart';
import 'theme.dart';
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
    final index = _currentIndex(context);

    return Scaffold(
      appBar: SsAppBar(
        title: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(index == 0 ? 'جلسه‌نگار' : 'تنظیمات'),
            const SizedBox(width: 8),
            const SsBadge('آزمایشی', color: SsColors.accent),
          ],
        ),
        centerTitle: false,
        actions: [
          // Info/Team icon
          IconButton(
            tooltip: 'تولیدکنندگان',
            icon: const Icon(Icons.info_outline),
            onPressed: () => context.push('/team'),
          ),
          // Models icon
          IconButton(
            tooltip: 'مدل‌ها',
            icon: const Icon(Icons.download_for_offline_outlined),
            onPressed: () => context.push('/models'),
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
        final card = RRect.fromRectAndRadius(
          const Rect.fromLTWH(3, 3, 18, 18),
          const Radius.circular(5),
        );
        canvas.drawRRect(card, line);
        const bars = [3.0, 6.0, 9.0, 5.5, 3.0];
        for (var i = 0; i < bars.length; i++) {
          final x = 7.4 + i * 2.3;
          canvas.drawLine(
            Offset(x, 12 - bars[i] / 2),
            Offset(x, 12 + bars[i] / 2),
            line,
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

/// Bar silhouette with a smooth round notch for the record button.
class _BarPainter extends CustomPainter {
  _BarPainter({
    required this.lift,
    required this.notchHalf,
    required this.depth,
  });

  final double lift;
  final double notchHalf;
  final double depth;

  Path _path(Size size) {
    final cx = size.width / 2;
    final top = lift;
    return Path()
      ..moveTo(0, top)
      ..lineTo(cx - notchHalf - 14, top)
      ..cubicTo(
        cx - notchHalf + 4,
        top,
        cx - notchHalf + 2,
        top + depth,
        cx,
        top + depth,
      )
      ..cubicTo(
        cx + notchHalf - 2,
        top + depth,
        cx + notchHalf - 4,
        top,
        cx + notchHalf + 14,
        top,
      )
      ..lineTo(size.width, top)
      ..lineTo(size.width, size.height)
      ..lineTo(0, size.height)
      ..close();
  }

  @override
  void paint(Canvas canvas, Size size) {
    final path = _path(size);
    canvas.drawShadow(
      path,
      SsColors.primaryDark.withValues(alpha: 0.55),
      10,
      false,
    );
    canvas.drawPath(path, Paint()..color = SsColors.canvas);
    // Hairline follows the silhouette but not the sides/bottom.
    final edge = Path()
      ..moveTo(0, lift)
      ..addPath(path, Offset.zero);
    canvas.drawPath(
      edge,
      Paint()
        ..color = SsColors.line
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1,
    );
  }

  @override
  bool shouldRepaint(_BarPainter old) =>
      old.lift != lift || old.notchHalf != notchHalf || old.depth != depth;
}

/// Brand bottom bar: canvas surface with a sculpted notch holding a raised
/// green record button, hand-drawn icons and a soft active pill.
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
  static const _lift = 30.0;

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.paddingOf(context).bottom;
    return SizedBox(
      height: _bar + _lift + bottom,
      child: Stack(
        children: [
          Positioned.fill(
            child: CustomPaint(
              painter: _BarPainter(lift: _lift, notchHalf: 44, depth: 40),
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
                  child: _NavTab(
                    glyph: _Glyph.sessions,
                    label: 'جلسات',
                    selected: selectedIndex == 0,
                    onTap: () => onSelected(0),
                  ),
                ),
                Expanded(
                  child: _RecordSlot(onTap: onRecord, lift: _lift),
                ),
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
            AnimatedContainer(
              duration: _anim,
              curve: Curves.easeOutCubic,
              width: 54,
              height: 32,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: selected ? SsColors.selected : Colors.transparent,
                borderRadius: BorderRadius.circular(16),
                border: Border.all(
                  color: selected ? SsColors.line : Colors.transparent,
                ),
              ),
              child: _GlyphIcon(glyph, color, filled: selected),
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
  const _RecordSlot({required this.onTap, required this.lift});

  final VoidCallback onTap;
  final double lift;

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
    const size = 64.0;
    return Semantics(
      button: true,
      label: 'ضبط جلسه',
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTapDown: (_) => setState(() => _down = true),
        onTapCancel: () => setState(() => _down = false),
        onTapUp: (_) => setState(() => _down = false),
        onTap: widget.onTap,
        child: OverflowBox(
          maxHeight: 140,
          alignment: Alignment.bottomCenter,
          child: AnimatedScale(
            duration: const Duration(milliseconds: 120),
            scale: _down ? 0.93 : 1,
            alignment: Alignment.bottomCenter,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                SizedBox(
                  width: size + 24,
                  height: size + 24,
                  child: Stack(
                    alignment: Alignment.center,
                    children: [
                      AnimatedBuilder(
                        animation: _pulse,
                        builder: (context, _) {
                          final t = Curves.easeOut.transform(_pulse.value);
                          return Container(
                            width: size + 20 * t,
                            height: size + 20 * t,
                            decoration: BoxDecoration(
                              borderRadius: BorderRadius.circular(22 + 8 * t),
                              border: Border.all(
                                color: SsColors.primary.withValues(
                                  alpha: 0.35 * (1 - t),
                                ),
                              ),
                            ),
                          );
                        },
                      ),
                      Container(
                        width: size,
                        height: size,
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(22),
                          gradient: const LinearGradient(
                            begin: Alignment.topCenter,
                            end: Alignment.bottomCenter,
                            colors: [
                              SsColors.primaryLight,
                              SsColors.primary,
                              SsColors.primaryDark,
                            ],
                            stops: [0, 0.55, 1],
                          ),
                          border: Border.all(
                            color: SsColors.accent,
                            width: 1.5,
                          ),
                          boxShadow: const [
                            BoxShadow(
                              color: Color(0x663E5C3B),
                              blurRadius: 16,
                              offset: Offset(0, 6),
                            ),
                          ],
                        ),
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(20.5),
                          child: const SsDots.onPrimary(
                            child: Center(
                              child: _GlyphIcon(
                                _Glyph.mic,
                                SsColors.canvas,
                                filled: true,
                                size: 30,
                              ),
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 1),
                const Text(
                  'ضبط جلسه',
                  style: TextStyle(
                    fontFamily: 'Vazirmatn',
                    fontSize: 12,
                    height: 1.2,
                    fontWeight: FontWeight.w600,
                    color: SsColors.primary,
                  ),
                ),
                const SizedBox(height: 6),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
