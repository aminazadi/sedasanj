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
        ).createShader(rect),
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

/// App bar with the green brand gradient and light dot pattern.
class SsAppBar extends AppBar {
  SsAppBar({
    super.key,
    super.title,
    super.actions,
    super.leading,
    super.bottom,
    super.centerTitle,
    super.automaticallyImplyLeading,
  }) : super(
         flexibleSpace: const DecoratedBox(
           decoration: BoxDecoration(
             gradient: LinearGradient(
               begin: Alignment.topCenter,
               end: Alignment.bottomCenter,
               colors: [
                 SsColors.primaryLight,
                 SsColors.primary,
                 SsColors.primaryDark,
               ],
               stops: [0, 0.55, 1],
             ),
           ),
           child: SsDots.onPrimary(),
         ),
       );
}

/// Hero band: dotted canvas with the office line art fading in from the start side.
class SsPageHeader extends StatelessWidget {
  const SsPageHeader({
    super.key,
    required this.title,
    this.description,
    this.trailing,
  });

  final String title;
  final String? description;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      decoration: const BoxDecoration(
        color: SsColors.canvas,
        border: Border.fromBorderSide(BorderSide(color: SsColors.line)),
      ),
      child: Stack(
        children: [
          const Positioned.fill(child: SsDots()),
          Positioned.fill(
            child: Opacity(
              opacity: 0.35,
              child: Image.asset(
                'assets/images/brand/office-line-art.webp',
                fit: BoxFit.cover,
                alignment: AlignmentDirectional.centerStart,
                colorBlendMode: BlendMode.multiply,
                color: SsColors.canvas,
              ),
            ),
          ),
          Positioned.fill(
            child: DecoratedBox(
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  begin: AlignmentDirectional.centerEnd,
                  end: AlignmentDirectional.centerStart,
                  colors: [
                    SsColors.canvas,
                    SsColors.canvas.withValues(alpha: 0.9),
                    SsColors.canvas.withValues(alpha: 0.2),
                  ],
                  stops: const [0, 0.42, 1],
                ),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(title, style: theme.textTheme.titleLarge),
                      if (description != null) ...[
                        const SizedBox(height: 2),
                        Text(description!, style: theme.textTheme.bodySmall),
                      ],
                    ],
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

/// Bordered panel with an optional dotted title band (matches `.panel-shell .card`).
class SsCard extends StatelessWidget {
  const SsCard({
    super.key,
    this.title,
    this.trailing,
    this.padding = const EdgeInsets.all(16),
    this.onTap,
    this.selected = false,
    required this.child,
  });

  final String? title;
  final Widget? trailing;
  final EdgeInsetsGeometry padding;
  final VoidCallback? onTap;
  final bool selected;
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
    return Material(
      color: selected ? SsColors.selected : SsColors.canvas,
      shape: Border.fromBorderSide(
        BorderSide(color: selected ? SsColors.primary : SsColors.line),
      ),
      clipBehavior: Clip.hardEdge,
      child: onTap == null ? body : InkWell(onTap: onTap, child: body),
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
  const SsBadge(this.label, {super.key, this.color = SsColors.primary});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        border: Border.all(color: color.withValues(alpha: 0.5)),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontFamily: 'Vazirmatn',
          fontSize: 11,
          fontWeight: FontWeight.w500,
          color: color,
        ),
      ),
    );
  }
}
