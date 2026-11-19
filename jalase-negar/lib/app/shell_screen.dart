import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../features/onboarding/tour_overlay.dart';
import '../features/onboarding/tour_step.dart';
import '../features/people/application/people_providers.dart';
import '../features/meetings/application/meeting_providers.dart';
import '../features/meetings/application/meetings_search_controller.dart';
import '../features/meetings/presentation/meetings_header.dart';
import '../features/settings/application/connection_controller.dart';
import '../features/upload/upload_controller.dart';
import 'theme.dart';
import 'widgets/app_menu_drawer.dart';
import 'widgets/brand_logo.dart';
import 'widgets/ss_widgets.dart';

class ShellScreen extends ConsumerStatefulWidget {
  const ShellScreen({super.key, required this.child});

  final Widget child;

  @override
  ConsumerState<ShellScreen> createState() => _ShellScreenState();
}

class _ShellScreenState extends ConsumerState<ShellScreen>
    with SingleTickerProviderStateMixin {
  // 0 → header and bottom bar fully shown; 1 → fully hidden. A short scroll
  // in either direction commits to the opposite end, eased in smoothly —
  // it does not track the finger 1:1, so even a brief scroll plays the
  // whole transition.
  late final AnimationController _hidden = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 260),
  )..addListener(() => setState(() {}));

  /// Continuous scroll (logical pixels, same direction) that commits to
  /// fully hiding or showing the bars.
  static const _commitThreshold = 8.0;

  /// Scroll since the last commit (or direction reversal); not yet acted on.
  double _dragAccum = 0;

  @override
  void dispose() {
    _hidden.dispose();
    super.dispose();
  }

  bool _onScroll(ScrollNotification notification) {
    if (notification.metrics.axis != Axis.vertical) return false;
    if (notification is ScrollUpdateNotification) {
      final delta = notification.scrollDelta;
      if (delta == null || delta == 0) return false;
      // Excludes only a list snapping itself back from an overscroll once
      // the finger has already lifted — not overscroll in general, and not
      // a fling's own momentum (an in-range `ScrollUpdateNotification` with
      // no `dragDetails` is completely normal there, and is most of how
      // real scrolling happens; excluding every driver-less update, as an
      // earlier version of this did, meant scrolling barely reacted at
      // all). Overscroll itself stays in while a finger is still actively
      // dragging it, which is what lets a page with little or no real
      // scroll range — where any drag is immediately "out of range" — show
      // the bars again; ignoring all out-of-range scrolling, as an even
      // earlier version did, left such a page's bars stuck hidden for good.
      if (notification.dragDetails == null && notification.metrics.outOfRange) {
        return false;
      }
      if (_dragAccum != 0 && delta.sign != _dragAccum.sign) _dragAccum = 0;
      _dragAccum += delta;
      if (_dragAccum.abs() >= _commitThreshold) {
        _hidden.animateTo(
          _dragAccum > 0 ? 1 : 0,
          duration: const Duration(milliseconds: 260),
          curve: Curves.easeOutCubic,
        );
        _dragAccum = 0;
      }
    } else if (notification is ScrollEndNotification) {
      _dragAccum = 0;
    }
    return false;
  }

  int _currentIndex(BuildContext context) {
    final location = GoRouterState.of(context).uri.path;
    if (location == '/people') return 1;
    if (location == '/guide') return 3;
    if (location.startsWith('/settings')) return 2;
    return 0;
  }

  @override
  Widget build(BuildContext context) {
    // Keeps the upload queue alive for the whole app session.
    ref.watch(uploadQueueProvider.select((s) => s.running));
    // Resumes speaker analysis left over from an earlier run.
    ref.watch(speakerAnalysisProvider.select((s) => s.running));
    // Keeps people sync alive for the whole session.
    ref.watch(speakerSyncProvider.select((s) => s.running));
    final index = _currentIndex(context);
    // The meetings tab's search box lives in this header, not its body, so
    // it can take over the whole bar while active.
    final searching =
        index == 0 &&
        ref.watch(meetingsSearchProvider.select((s) => s.active));
    // Tabs other than the sessions list show their own title in the header
    // instead of the brand logo.
    final pageTitle = switch (index) {
      1 => 'افراد و صدا',
      2 => 'تنظیمات',
      3 => 'راهنما',
      _ => null,
    };

    final bottomInset = MediaQuery.paddingOf(context).bottom;
    final progress = _hidden.value;

    final scaffold = Scaffold(
      // Every tab scrolls behind the bar so it stays visible through the notch
      // under the record button; tabs pad their scroll content by
      // MediaQuery.paddingOf(context).bottom, which the Scaffold sets to the
      // bar height. That reserved height stays constant even as the bar
      // hides, so this padding never jumps mid-scroll.
      extendBody: true,
      drawer: const AppMenuDrawer(),
      appBar: _HidingAppBar(
        progress: progress,
        appBar: SsAppBar(
          // The menu button keeps the app's standard icon-button size (same
          // as every other AppBar icon button); only the dead space the
          // AppBar would otherwise reserve before the title is trimmed. While
          // searching there's no drawer button, and no leading widget at all
          // (not even an auto-implied one) so the field gets the full width;
          // its close button moves to the actions side instead, opposite
          // where the search/filter buttons it replaces were.
          leading: searching ? null : const DrawerButton(),
          automaticallyImplyLeading: !searching,
          titleSpacing: 0,
          actionsPadding: const EdgeInsetsDirectional.only(end: 16),
          centerTitle: false,
          title: searching
              ? const MeetingsSearchField()
              : pageTitle != null
              ? Text(pageTitle)
              : const SsBrandLogo(width: 104),
          actions: [
            if (searching) const MeetingsSearchCloseButton(),
            if (index == 0 && !searching) ...[
              const MeetingsSearchButton(),
              const MeetingsFilterButton(),
              const _HeaderAuth(),
            ],
            if (index == 1)
              SsAppBarAction(
                icon: Icons.person_add_alt_1,
                label: 'افزودن فرد',
                onPressed: () => context.push('/people/new'),
              ),
          ],
        ),
      ),
      body: NotificationListener<ScrollNotification>(
        onNotification: _onScroll,
        // The same `widget.child` instance every time, so this listener
        // (rebuilt each time the bars move) never forces the tab's own page
        // to rebuild along with it.
        child: widget.child,
      ),
      bottomNavigationBar: _HidingBottomBar(
        progress: progress,
        height: _SsBottomBar._bar + _SsBottomBar._lift + bottomInset,
        child: _SsBottomBar(
          selectedIndex: index,
          onSelected: (i) => context.go(switch (i) {
            0 => '/',
            1 => '/people',
            2 => '/settings',
            _ => '/guide',
          }),
        ),
      ),
    );

    // The floating record button sits above the whole Scaffold, not inside
    // its body: Scaffold always paints bottomNavigationBar above body (that
    // is how extendBody lets content show through it), so from inside the
    // body the button would be hit-test-blocked by the (now button-less,
    // but still fully hit-testable) bar chrome sitting above it.
    return Stack(
      children: [
        scaffold,
        _FloatingRecordButton(
          progress: progress,
          bottomInset: bottomInset,
          onTap: () => context.push('/record'),
        ),
      ],
    );
  }
}

/// Wraps the header so it can collapse upward as [progress] goes from 0
/// (fully shown) to 1 (fully hidden), without the AppBar itself ever being
/// laid out at anything but its own natural size — only how much of it is
/// clipped away changes, so nothing about its look changes at rest.
class _HidingAppBar extends StatelessWidget implements PreferredSizeWidget {
  const _HidingAppBar({required this.progress, required this.appBar});

  final double progress;
  final PreferredSizeWidget appBar;

  // Scaffold adds the top safe-area inset on top of this on its own, so it
  // is left out here (see AGENTS.md: confirmed against the Scaffold source
  // in the Flutter SDK, not guessed).
  @override
  Size get preferredSize =>
      Size.fromHeight(appBar.preferredSize.height * (1 - progress));

  @override
  Widget build(BuildContext context) {
    final fullHeight =
        appBar.preferredSize.height + MediaQuery.paddingOf(context).top;
    // Isolates the collapse animation's own repaints from the scrolling
    // page below, so sliding the header never adds a frame of work to it.
    return RepaintBoundary(
      child: ClipRect(
        child: OverflowBox(
          alignment: Alignment.bottomCenter,
          minHeight: fullHeight,
          maxHeight: fullHeight,
          child: appBar,
        ),
      ),
    );
  }
}

/// Slides the bottom bar's chrome (shape + tabs) down and out of view as
/// [progress] goes from 0 to 1. The slot [height] Scaffold reserves for it
/// never changes — only painting/hit-testing move — so this never disturbs
/// the bottom padding every tab already uses to clear the bar.
class _HidingBottomBar extends StatelessWidget {
  const _HidingBottomBar({
    required this.progress,
    required this.height,
    required this.child,
  });

  final double progress;
  final double height;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    // Isolated for the same reason as _HidingAppBar: the slide's repaints
    // never touch the scrolling page's own compositing layer.
    return RepaintBoundary(
      child: ClipRect(
        child: IgnorePointer(
          ignoring: progress >= 1,
          child: Transform.translate(
            offset: Offset(0, height * progress),
            child: child,
          ),
        ),
      ),
    );
  }
}

/// The record button, pulled out of the bottom bar so it can keep floating
/// once the bar slides away: as [progress] goes from 0 (docked, dead centre,
/// exactly where the bar used to show it) to 1, it migrates toward the
/// left and dips slightly lower, with one full, smooth turn, landing
/// upright.
class _FloatingRecordButton extends StatelessWidget {
  const _FloatingRecordButton({
    required this.progress,
    required this.bottomInset,
    required this.onTap,
  });

  final double progress;
  final double bottomInset;
  final VoidCallback onTap;

  /// Gap kept from the screen's left edge once fully floating.
  static const _floatMarginLeft = 8.0;

  /// How far it drops from its docked, raised height once fully floating —
  /// a deliberate step down, not a dive to the screen's edge: the diamond
  /// is large enough that going any lower starts to duck under scrolled
  /// content instead of floating clear above it.
  static const _floatDrop = 24.0;

  @override
  Widget build(BuildContext context) {
    const lift = _SsBottomBar._lift;
    const half = _SsBottomBar._half;
    const drop = _SsBottomBar._drop;
    const slotWidth = _SsBottomBar._slotWidth;
    const slotHeight = _SsBottomBar._lift + _SsBottomBar._bar;
    // The diamond's own centre within its slot (see _RecordSlotState), so
    // the spin below pivots on the diamond itself, not the wider slot box.
    const centerY = lift - 0.4 * half + drop;
    const pivot = Alignment(0, (centerY / slotHeight) * 2 - 1);

    // Moved by explicit pixel offsets, not by the slot box's own Alignment:
    // the box is exactly as tall as the button itself, leaving Align no
    // vertical slack to work with, so only a direct translate actually
    // moves it down.
    final screenWidth = MediaQuery.sizeOf(context).width;
    final dx = (_floatMarginLeft + slotWidth / 2 - screenWidth / 2) * progress;
    final dy = _floatDrop * progress;

    return Positioned(
      left: 0,
      right: 0,
      bottom: bottomInset,
      height: slotHeight,
      // Isolated like the bars themselves, so its own frequent repaints
      // (the move, and its pulse even at rest) never cost the page below.
      child: RepaintBoundary(
        child: Align(
          alignment: Alignment.topCenter,
          child: Transform.translate(
            offset: Offset(dx, dy),
            child: Transform.rotate(
              // One full turn over the move itself (not a fixed-time
              // flourish), so it always lands upright, however short or
              // long the scroll that triggered it was.
              angle: 2 * math.pi * progress,
              alignment: pivot,
              child: _RecordSlot(
                onTap: onTap,
                lift: lift,
                half: half,
                drop: drop,
                width: slotWidth,
                height: slotHeight,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// A "ورود" shortcut while signed out, or the account avatar once a
/// connection (personal or org) is paired.
class _HeaderAuth extends ConsumerWidget {
  const _HeaderAuth();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final connection = ref.watch(
      connectionControllerProvider.select((a) => a.value?.connection),
    );
    if (connection == null) {
      // A plain icon button, like the search/filter actions beside it, not
      // the bordered icon+label style of SsAppBarAction.
      return IconButton(
        icon: const Icon(Icons.login),
        tooltip: 'ورود',
        onPressed: () => context.push('/login'),
      );
    }
    return _HeaderAvatar(
      name: connection.userName,
      onTap: () => context.go('/settings'),
    );
  }
}

class _HeaderAvatar extends StatelessWidget {
  const _HeaderAvatar({required this.name, required this.onTap});

  final String name;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final trimmed = name.trim();
    final initial = trimmed.isEmpty ? null : trimmed.substring(0, 1);
    return Center(
      child: Semantics(
        button: true,
        label: trimmed.isEmpty ? 'حساب کاربری' : 'حساب کاربری: $trimmed',
        child: InkWell(
          onTap: onTap,
          customBorder: const CircleBorder(),
          child: CircleAvatar(
            // Same diameter as the standard header action's height so the
            // avatar reads as the same size control, not a smaller one.
            radius: 17,
            backgroundColor: SsColors.primary,
            child: initial == null
                ? const Icon(Icons.person, size: 18, color: SsColors.canvas)
                : Text(
                    initial,
                    style: const TextStyle(
                      fontFamily: 'Vazirmatn',
                      fontWeight: FontWeight.w700,
                      color: SsColors.canvas,
                    ),
                  ),
          ),
        ),
      ),
    );
  }
}

enum _Glyph { sessions, people, guide, settings, mic }

/// Hand-drawn 24-grid line icons so the bar does not depend on stock Material
/// glyphs (the old mic tab duplicated the record button). [progress] (0-1)
/// reveals every stroke along its own length, for a "drawn in" effect.
class _GlyphPainter extends CustomPainter {
  _GlyphPainter(this.glyph, this.color, {this.progress = 1});

  final _Glyph glyph;
  final Color color;
  final double progress;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 24);
    final line = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.8
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    final bar = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.4
      ..strokeCap = StrokeCap.round;
    final fill = Paint()..color = color;

    // Every stroke of the glyph, as one Path, so progress can reveal it
    // proportionally across all of its disconnected pieces.
    final strokes = Path();
    // Filled dots (not strokes), revealed only once the strokes are in.
    final dots = <(Offset center, double radius)>[];

    switch (glyph) {
      case _Glyph.sessions:
        // Voice waveform: five rounded bars, tallest in the middle.
        const bars = [6.0, 11.0, 17.0, 11.0, 6.0];
        for (var i = 0; i < bars.length; i++) {
          final x = 4 + i * 4.0;
          strokes
            ..moveTo(x, 12 - bars[i] / 2)
            ..lineTo(x, 12 + bars[i] / 2);
        }
      case _Glyph.people:
        // Two heads-and-shoulders: a front person and a smaller one behind.
        strokes.addOval(
          Rect.fromCircle(center: const Offset(10, 8), radius: 3.4),
        );
        strokes
          ..moveTo(3.5, 20)
          ..quadraticBezierTo(3.5, 13.5, 10, 13.5)
          ..quadraticBezierTo(16.5, 13.5, 16.5, 20);
        strokes.addArc(
          Rect.fromCircle(center: const Offset(16.5, 8.6), radius: 2.7),
          -1.9,
          3.9,
        );
        strokes
          ..moveTo(18.2, 13.9)
          ..quadraticBezierTo(20.5, 14.6, 20.5, 19);
      case _Glyph.guide:
        // A circle with a question mark.
        strokes.addOval(
          Rect.fromCircle(center: const Offset(12, 12), radius: 8.5),
        );
        strokes
          ..moveTo(9.4, 9.6)
          ..cubicTo(9.4, 6.6, 14.6, 6.6, 14.6, 9.6)
          ..cubicTo(14.6, 11.6, 12, 11.7, 12, 13.6);
        dots.add((const Offset(12, 16.6), 0.9));
      case _Glyph.settings:
        const rows = [(6.5, 15.0), (12.0, 8.5), (17.5, 16.0)];
        for (final (y, kx) in rows) {
          strokes
            ..moveTo(4, y)
            ..lineTo(kx - 2.7, y)
            ..moveTo(kx + 2.7, y)
            ..lineTo(20, y);
          strokes.addOval(Rect.fromCircle(center: Offset(kx, y), radius: 2.2));
        }
      case _Glyph.mic:
        strokes.addRRect(
          RRect.fromRectAndRadius(
            const Rect.fromLTWH(8.8, 2.8, 6.4, 11.4),
            const Radius.circular(3.2),
          ),
        );
        strokes.addArc(
          Rect.fromCircle(center: const Offset(12, 11), radius: 6.8),
          0.12,
          math.pi - 0.24,
        );
        strokes
          ..moveTo(12, 17.8)
          ..lineTo(12, 21)
          ..moveTo(8.6, 21)
          ..lineTo(15.4, 21);
    }

    _drawPartial(canvas, strokes, glyph == _Glyph.sessions ? bar : line, progress);
    // The dot only appears once the strokes are nearly done drawing.
    final dotT = ((progress - 0.75) / 0.25).clamp(0.0, 1.0);
    if (dotT > 0) {
      for (final (center, radius) in dots) {
        canvas.drawCircle(center, radius * dotT, fill);
      }
    }
  }

  /// Draws [path] up to the fraction [t] of its total length, proportionally
  /// across every one of its disconnected strokes.
  static void _drawPartial(Canvas canvas, Path path, Paint paint, double t) {
    if (t >= 1) {
      canvas.drawPath(path, paint);
      return;
    }
    if (t <= 0) return;
    final metrics = path.computeMetrics().toList();
    final total = metrics.fold<double>(0, (sum, m) => sum + m.length);
    var remaining = total * t;
    for (final metric in metrics) {
      if (remaining <= 0) break;
      final length = math.min(metric.length, remaining);
      canvas.drawPath(metric.extractPath(0, length), paint);
      remaining -= metric.length;
    }
  }

  @override
  bool shouldRepaint(_GlyphPainter old) =>
      old.glyph != glyph || old.color != color || old.progress != progress;
}

class _GlyphIcon extends StatelessWidget {
  const _GlyphIcon(this.glyph, this.color, {this.size = 27, this.progress = 1});

  final _Glyph glyph;
  final Color color;
  final double size;
  final double progress;

  @override
  Widget build(BuildContext context) => CustomPaint(
    size: Size.square(size),
    painter: _GlyphPainter(glyph, color, progress: progress),
  );
}

/// Bar silhouette: a straight top edge that drops along a 45° V under the
/// diamond record button, with the V's corners softened by [cornerRadius].
class _BarPainter extends CustomPainter {
  _BarPainter({required this.lift, required this.half, this.cornerRadius = 12});

  final double lift;

  /// Half the width of the V; equal to the diamond's half-diagonal so the V
  /// runs parallel to the diamond's lower edges.
  final double half;

  /// Radius applied where the flat edge meets the V and at the V's bottom
  /// vertex.
  final double cornerRadius;

  @override
  void paint(Canvas canvas, Size size) {
    final cx = size.width / 2;
    final edge = _roundedPolyline(
      [
        Offset(0, lift),
        Offset(cx - half, lift),
        Offset(cx, lift + half),
        Offset(cx + half, lift),
        Offset(size.width, lift),
      ],
      cornerRadius,
    );
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
        ..strokeJoin = StrokeJoin.round,
    );
  }

  /// A polyline through [points] with each interior vertex rounded to
  /// [radius] (clamped to half of its shortest adjacent segment).
  static Path _roundedPolyline(List<Offset> points, double radius) {
    final path = Path()..moveTo(points.first.dx, points.first.dy);
    for (var i = 1; i < points.length - 1; i++) {
      final prev = points[i - 1];
      final corner = points[i];
      final next = points[i + 1];
      final toPrev = prev - corner;
      final toNext = next - corner;
      final r = math.min(radius, math.min(toPrev.distance, toNext.distance) / 2);
      final start = corner + toPrev / toPrev.distance * r;
      final end = corner + toNext / toNext.distance * r;
      path.lineTo(start.dx, start.dy);
      path.quadraticBezierTo(corner.dx, corner.dy, end.dx, end.dy);
    }
    path.lineTo(points.last.dx, points.last.dy);
    return path;
  }

  @override
  bool shouldRepaint(_BarPainter old) =>
      old.lift != lift || old.half != half || old.cornerRadius != cornerRadius;
}

/// Brand bottom bar: canvas surface whose top edge dips into a V under a
/// raised diamond record button, with hand-drawn icons and a soft active pill.
class _SsBottomBar extends StatelessWidget {
  const _SsBottomBar({required this.selectedIndex, required this.onSelected});

  final int selectedIndex;
  final ValueChanged<int> onSelected;

  static const _bar = 72.0;
  static const _lift = 60.0;
  static const _half = 38.0;

  /// How much lower the diamond sits and how much deeper the notch is cut.
  static const _drop = 16.0;
  // Kept close to the V notch's own width (2 * (_half + _drop) = 108) so the
  // gap from a nav icon to the notch's edge lands close to the gap between
  // two nav icons, instead of the notch's slack stacking on top of it.
  static const _slotWidth = 116.0;

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.paddingOf(context).bottom;
    return SizedBox(
      height: _bar + _lift + bottom,
      child: Stack(
        children: [
          Positioned.fill(
            child: CustomPaint(
              painter: _BarPainter(
                lift: _lift,
                half: _half + _drop,
                cornerRadius: 12,
              ),
            ),
          ),
          Positioned(
            left: 0,
            right: 0,
            bottom: bottom,
            height: _bar,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
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
                  Expanded(
                    child: _NavTab(
                      glyph: _Glyph.people,
                      label: 'افراد',
                      selected: selectedIndex == 1,
                      onTap: () => onSelected(1),
                    ),
                  ),
                  const SizedBox(width: _slotWidth),
                  Expanded(
                    child: _NavTab(
                      glyph: _Glyph.settings,
                      label: 'تنظیمات',
                      selected: selectedIndex == 2,
                      onTap: () => onSelected(2),
                    ),
                  ),
                  Expanded(
                    child: _NavTab(
                      glyph: _Glyph.guide,
                      label: 'راهنما',
                      selected: selectedIndex == 3,
                      onTap: () => onSelected(3),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _NavTab extends StatefulWidget {
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

  @override
  State<_NavTab> createState() => _NavTabState();
}

class _NavTabState extends State<_NavTab> with SingleTickerProviderStateMixin {
  static const _anim = Duration(milliseconds: 280);
  static const _pillAnim = Duration(milliseconds: 320);
  static const _drawAnim = Duration(milliseconds: 420);

  // Starts fully drawn so a tab that's already active on first build doesn't
  // play the draw-in; only a fresh selection resets and replays it.
  late final AnimationController _draw = AnimationController(
    vsync: this,
    duration: _drawAnim,
    value: 1,
  );

  @override
  void didUpdateWidget(_NavTab old) {
    super.didUpdateWidget(old);
    if (widget.selected && !old.selected) {
      _draw
        ..value = 0
        ..forward();
    } else if (!widget.selected) {
      _draw.value = 1;
    }
  }

  @override
  void dispose() {
    _draw.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final selected = widget.selected;
    final color = selected ? SsColors.primary : SsColors.neutral;
    return Semantics(
      button: true,
      selected: selected,
      label: widget.label,
      child: InkWell(
        onTap: widget.onTap,
        splashFactory: NoSplash.splashFactory,
        highlightColor: Colors.transparent,
        hoverColor: Colors.transparent,
        child: Center(
          // The soft pill wraps the icon and its label together, and pops in
          // with a slight overshoot when the tab becomes active. A fixed
          // width (rather than hugging the label) keeps it the same size on
          // every tab, long label ("تنظیمات") or short ("افراد") alike.
          child: AnimatedContainer(
            duration: _pillAnim,
            curve: Curves.easeOutCubic,
            width: 68,
            margin: const EdgeInsets.symmetric(vertical: 6),
            padding: const EdgeInsets.symmetric(vertical: 6),
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: selected
                  ? SsColors.primary.withValues(alpha: 0.12)
                  : Colors.transparent,
              borderRadius: BorderRadius.circular(8),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                SizedBox(
                  width: 26,
                  height: 26,
                  child: AnimatedBuilder(
                    animation: _draw,
                    builder: (context, _) => TweenAnimationBuilder<Color?>(
                      duration: _anim,
                      curve: Curves.easeOutCubic,
                      tween: ColorTween(end: color),
                      builder: (context, c, _) => _GlyphIcon(
                        widget.glyph,
                        c ?? color,
                        size: 26,
                        progress: Curves.easeOutCubic.transform(_draw.value),
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 3),
                // Shrinks the label instead of clipping it when a cell is
                // too narrow for its full text (e.g. "تنظیمات" on a small
                // screen), rather than silently cutting off a letter.
                FittedBox(
                  fit: BoxFit.scaleDown,
                  child: AnimatedDefaultTextStyle(
                    duration: _anim,
                    style: TextStyle(
                      fontFamily: 'Vazirmatn',
                      fontSize: 12,
                      height: 1.2,
                      fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
                      color: color,
                    ),
                    child: Text(widget.label, maxLines: 1),
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

class _RecordSlot extends StatefulWidget {
  const _RecordSlot({
    required this.onTap,
    required this.lift,
    required this.half,
    required this.drop,
    required this.width,
    required this.height,
  });

  final VoidCallback onTap;
  final double lift;
  final double half;
  final double drop;
  final double width;
  final double height;

  @override
  State<_RecordSlot> createState() => _RecordSlotState();
}

class _RecordSlotState extends State<_RecordSlot>
    with SingleTickerProviderStateMixin {
  static const _diamondRadius = 12.0;

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
    final centerY = widget.lift - 0.4 * d + widget.drop;
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
                                borderRadius: BorderRadius.circular(
                                  _diamondRadius,
                                ),
                                border: Border.all(
                                  color: SsColors.danger.withValues(
                                    alpha: 0.35 * (1 - t),
                                  ),
                                ),
                              ),
                            ),
                          );
                        },
                      ),
                      AnimatedBuilder(
                        animation: _pulse,
                        builder: (context, _) {
                          final glow =
                              0.5 + 0.5 * math.sin(_pulse.value * 2 * math.pi);
                          return Container(
                            width: side * 0.9,
                            height: side * 0.9,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              boxShadow: [
                                BoxShadow(
                                  color: SsColors.danger.withValues(
                                    alpha: 0.25 + 0.3 * glow,
                                  ),
                                  blurRadius: 18 + 12 * glow,
                                  spreadRadius: 2 + 4 * glow,
                                ),
                              ],
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
                            borderRadius: BorderRadius.circular(
                              _diamondRadius,
                            ),
                            gradient: const LinearGradient(
                              begin: Alignment.topLeft,
                              end: Alignment.bottomRight,
                              colors: [
                                Color(0xFFE5484D),
                                SsColors.danger,
                                Color(0xFF8F0E2E),
                              ],
                              stops: [0, 0.55, 1],
                            ),
                            border: Border.all(
                              color: SsColors.danger,
                              width: 1.5,
                            ),
                            boxShadow: const [
                              BoxShadow(
                                color: Color(0x66BE123C),
                                blurRadius: 14,
                                offset: Offset(0, 5),
                              ),
                            ],
                          ),
                          child: ClipRRect(
                            borderRadius: BorderRadius.circular(
                              _diamondRadius,
                            ),
                            child: Stack(
                              fit: StackFit.expand,
                              children: [
                                const SsDots.onPrimary(
                                  child: SizedBox.expand(),
                                ),
                                // A soft light band sweeping across the
                                // diamond, once per pulse.
                                AnimatedBuilder(
                                  animation: _pulse,
                                  builder: (context, _) => FractionallySizedBox(
                                    alignment: Alignment(
                                      -2 + 4 * _pulse.value,
                                      0,
                                    ),
                                    widthFactor: 0.35,
                                    child: DecoratedBox(
                                      decoration: BoxDecoration(
                                        gradient: LinearGradient(
                                          colors: [
                                            Colors.white.withValues(alpha: 0),
                                            Colors.white.withValues(
                                              alpha: 0.35,
                                            ),
                                            Colors.white.withValues(alpha: 0),
                                          ],
                                        ),
                                      ),
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ),
                      // The mic glyph matches the "ضبط جلسه" (record) action
                      // and the nav bar's hand-drawn icon set, instead of a
                      // generic "+".
                      _GlyphIcon(_Glyph.mic, SsColors.canvas, size: 36),
                    ],
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
