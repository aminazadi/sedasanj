import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme.dart';

/// Dotted background used across the SedaSanj panel (radial dots every 7px).
class SsDots extends StatelessWidget {
  const SsDots({
    super.key,
    this.color = const Color(0x1F898989),
    this.fadeToEnd = false,
    this.child,
  });

  /// Light dots for use on the green brand surface.
  const SsDots.onPrimary({super.key, this.fadeToEnd = false, this.child})
    : color = const Color(0x1AF2F0EF);

  final Color color;

  /// Fades the dots out towards the end edge (section title band).
  final bool fadeToEnd;
  final Widget? child;

  @override
  Widget build(BuildContext context) {
    Widget dots = CustomPaint(
      painter: _DotsPainter(color),
      child: const SizedBox.expand(),
    );
    if (fadeToEnd) {
      dots = ShaderMask(
        blendMode: BlendMode.dstIn,
        shaderCallback: (rect) => LinearGradient(
          begin: AlignmentDirectional.centerStart,
          end: AlignmentDirectional.centerEnd,
          colors: const [Colors.black, Color(0x8C000000), Colors.transparent],
          stops: const [0, 0.45, 1],
        ).createShader(rect, textDirection: Directionality.of(context)),
        child: dots,
      );
    }
    if (child == null) return dots;
    return Stack(
      fit: StackFit.passthrough,
      children: [
        Positioned.fill(child: dots),
        child!,
      ],
    );
  }
}

class _DotsPainter extends CustomPainter {
  _DotsPainter(this.color);

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()..color = color;
    const gap = 7.0;
    for (var y = gap / 2; y < size.height; y += gap) {
      for (var x = gap / 2; x < size.width; x += gap) {
        canvas.drawCircle(Offset(x, y), 0.6, paint);
      }
    }
  }

  @override
  bool shouldRepaint(_DotsPainter old) => old.color != color;
}

/// App bar on the canvas surface: dot pattern plus the office line art,
/// mirrored onto the end side and fading out towards the title.
class SsAppBar extends AppBar {
  SsAppBar({
    super.key,
    super.title,
    super.actions,
    super.leading,
    super.leadingWidth,
    super.bottom,
    super.centerTitle,
    super.automaticallyImplyLeading,
    super.titleSpacing,
    super.actionsPadding,
  }) : super(
         // Same bottom border and drop shadow as the bottom nav bar's own
         // painted edge, so the two bars read as a matching pair.
         flexibleSpace: const DecoratedBox(
           decoration: BoxDecoration(
             color: SsColors.canvas,
             border: Border(bottom: BorderSide(color: SsColors.line)),
             boxShadow: [
               BoxShadow(
                 color: Color(0x403E5C3B),
                 blurRadius: 10,
                 offset: Offset(0, 4),
               ),
             ],
           ),
           child: Stack(
             fit: StackFit.expand,
             children: [SsDots(), _AppBarArt()],
           ),
         ),
       );
}

/// Compact square header action shared by the main navigation tabs.
class SsAppBarAction extends StatelessWidget {
  const SsAppBarAction({
    super.key,
    required this.icon,
    required this.label,
    required this.onPressed,
  });

  final IconData icon;
  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: TextButton.icon(
        onPressed: onPressed,
        style: TextButton.styleFrom(
          foregroundColor: SsColors.ink,
          backgroundColor: SsColors.ink.withValues(alpha: 0.06),
          side: BorderSide(color: SsColors.ink.withValues(alpha: 0.25)),
          shape: const RoundedRectangleBorder(),
          minimumSize: const Size(0, 34),
          padding: const EdgeInsets.symmetric(horizontal: 10),
          iconSize: 19,
          textStyle: const TextStyle(
            fontFamily: 'Vazirmatn',
            fontSize: 12.5,
            fontWeight: FontWeight.w500,
          ),
        ),
        icon: Icon(icon),
        label: Text(label),
      ),
    );
  }
}

class _AppBarArt extends StatelessWidget {
  const _AppBarArt();

  @override
  Widget build(BuildContext context) {
    return Stack(
      fit: StackFit.expand,
      children: [
        Opacity(
          opacity: 0.5,
          child: Transform.flip(
            flipX: true,
            child: Image.asset(
              'assets/images/brand/office-line-art.webp',
              fit: BoxFit.cover,
              alignment: const AlignmentDirectional(-1, 0.45),
              colorBlendMode: BlendMode.multiply,
              color: SsColors.canvas,
            ),
          ),
        ),
        DecoratedBox(
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: AlignmentDirectional.centerStart,
              end: AlignmentDirectional.centerEnd,
              colors: [
                SsColors.canvas,
                SsColors.canvas.withValues(alpha: 0.85),
                SsColors.canvas.withValues(alpha: 0.1),
              ],
              stops: const [0, 0.4, 1],
            ),
          ),
        ),
      ],
    );
  }
}

/// Bordered panel with an optional dotted title band (matches `.panel-shell .card`).
class SsCard extends StatelessWidget {
  const SsCard({
    super.key,
    this.title,
    this.trailing,
    this.padding = const EdgeInsets.all(16),
    this.onTap,
    this.selected = false,
    this.ripple = false,
    this.elevated = false,
    this.color,
    required this.child,
  });

  final String? title;
  final Widget? trailing;
  final EdgeInsetsGeometry padding;
  final VoidCallback? onTap;
  final bool selected;

  /// Soft ink ripple on tap (the theme disables splashes by default).
  final bool ripple;

  /// Soft shadow under the card.
  final bool elevated;
  final Color? color;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final body = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        if (title != null) SsSectionTitle(title: title!, trailing: trailing),
        Padding(padding: padding, child: child),
      ],
    );
    final card = Material(
      color: color ?? (selected ? SsColors.selected : SsColors.canvas),
      shape: Border.fromBorderSide(
        BorderSide(color: selected ? SsColors.primary : SsColors.line),
      ),
      clipBehavior: Clip.antiAlias,
      child: onTap == null
          ? body
          : InkWell(
              onTap: onTap,
              splashFactory: ripple ? InkRipple.splashFactory : null,
              splashColor: ripple
                  ? SsColors.primary.withValues(alpha: 0.08)
                  : null,
              highlightColor: ripple
                  ? SsColors.primary.withValues(alpha: 0.04)
                  : null,
              child: body,
            ),
    );
    if (!elevated) return card;
    return DecoratedBox(
      decoration: BoxDecoration(
        boxShadow: [
          BoxShadow(
            color: SsColors.ink.withValues(alpha: 0.06),
            blurRadius: 14,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: card,
    );
  }
}

/// Section heading: dotted band fading out, separated from the body by a rule.
class SsSectionTitle extends StatelessWidget {
  const SsSectionTitle({super.key, required this.title, this.trailing});

  final String title;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: SsColors.line)),
      ),
      child: Stack(
        children: [
          const Positioned.fill(
            child: SsDots(color: Color(0x47898989), fadeToEnd: true),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    title,
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                ),
                if (trailing != null) trailing!,
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Empty state using the shared SedaSanj illustration.
class SsEmptyState extends StatelessWidget {
  const SsEmptyState({super.key, required this.title, this.hint, this.action});

  final String title;
  final String? hint;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Image.asset(
              'assets/images/brand/empty-state.webp',
              width: 180,
              fit: BoxFit.contain,
            ),
            const SizedBox(height: 16),
            Text(title, style: theme.textTheme.titleMedium),
            if (hint != null) ...[
              const SizedBox(height: 4),
              Text(hint!, style: theme.textTheme.bodySmall),
            ],
            if (action != null) ...[const SizedBox(height: 16), action!],
          ],
        ),
      ),
    );
  }
}

/// Square status badge replacing rounded pills / gradient chips.
class SsBadge extends StatelessWidget {
  const SsBadge(
    this.label, {
    super.key,
    this.color = SsColors.primary,
    this.icon,
    this.leading,
  });

  final String label;
  final Color color;
  final IconData? icon;

  /// Replaces [icon], e.g. the animated [SsProcessingMark].
  final Widget? leading;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        border: Border.all(color: color.withValues(alpha: 0.5)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (leading != null) ...[
            leading!,
            const SizedBox(width: 5),
          ] else if (icon != null) ...[
            Icon(icon, size: 13, color: color),
            const SizedBox(width: 4),
          ],
          Text(
            label,
            style: TextStyle(
              fontFamily: 'Vazirmatn',
              fontSize: 11,
              fontWeight: FontWeight.w500,
              height: 1.4,
              color: color,
            ),
          ),
        ],
      ),
    );
  }
}

/// Four-square processing mark, ported from the web panel's
/// `ProcessingIndicator` (`.assistant-conversation-processing`): a 2x2 grid of
/// squares that pulse in turn.
class SsProcessingMark extends StatefulWidget {
  const SsProcessingMark({super.key, this.size = 14});

  final double size;

  @override
  State<SsProcessingMark> createState() => _SsProcessingMarkState();
}

class _SsProcessingMarkState extends State<SsProcessingMark>
    with SingleTickerProviderStateMixin {
  static const _period = Duration(milliseconds: 1100);
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: _period,
  );

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (MediaQuery.disableAnimationsOf(context)) {
      _c.stop();
    } else if (!_c.isAnimating) {
      _c.repeat();
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'در حال پردازش',
      child: ExcludeSemantics(
        child: RepaintBoundary(
          child: CustomPaint(
            size: Size.square(widget.size),
            painter: _ProcessingMarkPainter(_c),
          ),
        ),
      ),
    );
  }
}

class _ProcessingMarkPainter extends CustomPainter {
  _ProcessingMarkPainter(this.animation) : super(repaint: animation);

  final AnimationController animation;

  // Square colours and animation delays (seconds), as in index.css.
  static const _colors = [
    Color(0xFFB2AC88),
    Color(0xFF7A8B73),
    Color(0xFFD8D3B9),
    Color(0xFF4B6E48),
  ];
  static const _delays = [0.0, -0.82, -0.55, -0.27];
  static const _ease = Cubic(0.4, 0, 0.2, 1);

  /// Keyframes 0%/100%: opacity .28 scale .56; 38%: 1 / 1; 64%: .72 / .8.
  static (double, double) _frame(double p) {
    double lerp(double a, double b, double t) =>
        a + (b - a) * _ease.transform(t);
    if (p < 0.38) return (lerp(0.28, 1, p / 0.38), lerp(0.56, 1, p / 0.38));
    if (p < 0.64) {
      final t = (p - 0.38) / 0.26;
      return (lerp(1, 0.72, t), lerp(1, 0.8, t));
    }
    final t = (p - 0.64) / 0.36;
    return (lerp(0.72, 0.28, t), lerp(0.8, 0.56, t));
  }

  @override
  void paint(Canvas canvas, Size size) {
    final gap = size.width / 12;
    final cell = (size.width - gap) / 2;
    final seconds = animation.value * 1.1;
    for (var i = 0; i < 4; i++) {
      final phase = (((seconds - _delays[i]) / 1.1) % 1 + 1) % 1;
      final (opacity, scale) = animation.isAnimating
          ? _frame(phase)
          : (1.0, 1.0);
      final cx = (i % 2) * (cell + gap) + cell / 2;
      final cy = (i ~/ 2) * (cell + gap) + cell / 2;
      final half = cell * scale / 2;
      canvas.drawRect(
        Rect.fromLTRB(cx - half, cy - half, cx + half, cy + half),
        Paint()..color = _colors[i].withValues(alpha: opacity),
      );
    }
  }

  @override
  bool shouldRepaint(_ProcessingMarkPainter old) => false;
}

/// Square (no corner radius) on/off switch in the brand style.
class SsSwitch extends StatelessWidget {
  const SsSwitch({super.key, required this.value, required this.onChanged});

  final bool value;
  final ValueChanged<bool>? onChanged;

  @override
  Widget build(BuildContext context) {
    final enabled = onChanged != null;
    final on = SsColors.primary.withValues(alpha: enabled ? 1 : 0.4);
    final off = SsColors.neutral.withValues(alpha: enabled ? 1 : 0.5);
    return Semantics(
      toggled: value,
      enabled: enabled,
      child: InkWell(
        onTap: enabled ? () => onChanged!(!value) : null,
        child: SizedBox(
          width: 48,
          height: 36,
          child: Center(
            child: Ink(
              width: 40,
              height: 22,
              padding: const EdgeInsets.all(3),
              decoration: BoxDecoration(
                color: value ? on : SsColors.canvas,
                border: Border.all(color: value ? on : off),
              ),
              child: Align(
                alignment: value
                    ? AlignmentDirectional.centerEnd
                    : AlignmentDirectional.centerStart,
                child: ColoredBox(
                  color: value ? SsColors.canvas : off,
                  child: const SizedBox.square(dimension: 14),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// A list row with a title, an optional subtitle and a [SsSwitch].
class SsSwitchTile extends StatelessWidget {
  const SsSwitchTile({
    super.key,
    required this.value,
    required this.onChanged,
    required this.title,
    this.subtitle,
  });

  final bool value;
  final ValueChanged<bool>? onChanged;
  final Widget title;
  final Widget? subtitle;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      title: title,
      subtitle: subtitle,
      trailing: SsSwitch(value: value, onChanged: onChanged),
      onTap: onChanged == null ? null : () => onChanged!(!value),
    );
  }
}

/// Diamond (45° square) button, the same shape as the recording screen's
/// record/pause/stop controls and the bottom bar's record diamond. [half] is
/// the diamond's half-diagonal.
class SsDiamondButton extends StatefulWidget {
  const SsDiamondButton({
    super.key,
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
  State<SsDiamondButton> createState() => _SsDiamondButtonState();
}

class _SsDiamondButtonState extends State<SsDiamondButton>
    with SingleTickerProviderStateMixin {
  // Same radius as the bottom bar's own record diamond.
  static const _diamondRadius = 12.0;

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
  void didUpdateWidget(covariant SsDiamondButton oldWidget) {
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
    // The pulsing start button is the record button: red, like the bar's.
    final red = widget.danger || widget.pulse;
    final main = red ? SsColors.danger : SsColors.primary;
    final colors = red
        ? const [Color(0xFFE5484D), SsColors.danger, Color(0xFF8F0E2E)]
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
                  Container(
                    width: side * 0.9,
                    height: side * 0.9,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      boxShadow: [
                        BoxShadow(
                          color: main.withValues(
                            alpha:
                                0.25 +
                                0.3 *
                                    (0.5 +
                                        0.5 *
                                            math.sin(
                                              _pulse.value * 2 * math.pi,
                                            )),
                          ),
                          blurRadius:
                              18 +
                              12 *
                                  (0.5 +
                                      0.5 *
                                          math.sin(_pulse.value * 2 * math.pi)),
                          spreadRadius: 3,
                        ),
                      ],
                    ),
                  ),
                if (animate)
                  Builder(
                    builder: (context) {
                      // Same single ring as the bottom bar's record diamond.
                      final t = Curves.easeOut.transform(_pulse.value);
                      final ringSize = side + 12 * t;
                      return Positioned(
                        left: (2 * d + 8 - ringSize) / 2,
                        top: (2 * d + 8 - ringSize) / 2,
                        width: ringSize,
                        height: ringSize,
                        child: Transform.rotate(
                          angle: math.pi / 4,
                          child: DecoratedBox(
                            decoration: BoxDecoration(
                              borderRadius: BorderRadius.circular(
                                _diamondRadius,
                              ),
                              border: Border.all(
                                color: main.withValues(alpha: 0.35 * (1 - t)),
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
                        borderRadius: BorderRadius.circular(_diamondRadius),
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
                      child: widget.pulse
                          ? ClipRRect(
                              borderRadius: BorderRadius.circular(
                                _diamondRadius,
                              ),
                              child: Stack(
                                fit: StackFit.expand,
                                children: [
                                  const SsDots.onPrimary(
                                    child: SizedBox.expand(),
                                  ),
                                  FractionallySizedBox(
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
                                ],
                              ),
                            )
                          : null,
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
