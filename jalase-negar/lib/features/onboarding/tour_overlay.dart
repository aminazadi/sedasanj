import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/theme.dart';
import '../../app/widgets/ss_widgets.dart';
import '../../core/utils/format.dart';
import 'tour_progress.dart';
import 'tour_step.dart';

class TourOverlay extends ConsumerStatefulWidget {
  const TourOverlay({
    super.key,
    required this.step,
    required this.fromSettings,
    required this.child,
  });

  final TourStep step;
  final bool fromSettings;
  final Widget child;

  @override
  ConsumerState<TourOverlay> createState() => _TourOverlayState();
}

class _TourOverlayState extends ConsumerState<TourOverlay> {
  final _targets = {for (final step in TourStep.values) step: GlobalKey()};
  bool _saving = false;
  bool _saveFailed = false;

  void _goTo(int index) {
    if (_saving) return;
    if (_saveFailed) setState(() => _saveFailed = false);
    context.go(
      TourStep.values[index].location(fromSettings: widget.fromSettings),
    );
  }

  void _back() {
    if (_saving) return;
    final index = widget.step.index;
    if (index == 0) {
      _finish();
    } else {
      _goTo(index - 1);
    }
  }

  Future<void> _finish({bool persist = true}) async {
    if (_saving) return;
    setState(() {
      _saving = true;
      _saveFailed = false;
    });
    try {
      await ref.read(tourProgressProvider.notifier).finish(persist: persist);
    } catch (_) {
      if (mounted) {
        setState(() {
          _saving = false;
          _saveFailed = true;
        });
      }
      return;
    }
    if (mounted) context.go(widget.fromSettings ? '/guide' : '/');
  }

  @override
  Widget build(BuildContext context) {
    final step = widget.step;
    final anchor = _targets[step]!;
    final last = step == TourStep.done;
    final theme = Theme.of(context);
    final stage = toPersianDigits('${step.index + 1}');
    final total = toPersianDigits('${TourStep.values.length}');

    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _back();
      },
      child: Stack(
        fit: StackFit.expand,
        children: [
          GestureDetector(
            behavior: HitTestBehavior.opaque,
            excludeFromSemantics: true,
            onTapUp: (details) {
              final target = anchor.currentContext?.findRenderObject();
              if (last || target is! RenderBox || !target.hasSize) return;
              final bounds = (Offset.zero & target.size).inflate(4);
              if (bounds.contains(
                target.globalToLocal(details.globalPosition),
              )) {
                _goTo(step.index + 1);
              }
            },
            child: _TourBackdrop(
              anchor: anchor,
              child: ExcludeSemantics(
                child: ExcludeFocus(
                  child: IgnorePointer(
                    child: _TourFocus(
                      step: step,
                      anchor: anchor,
                      child: widget.child,
                    ),
                  ),
                ),
              ),
            ),
          ),
          SafeArea(
            minimum: const EdgeInsets.all(12),
            child: LayoutBuilder(
              builder: (context, constraints) => Align(
                alignment: step.panelAtTop
                    ? Alignment.topCenter
                    : step == TourStep.welcome || last
                    ? Alignment.center
                    : Alignment.bottomCenter,
                child: ConstrainedBox(
                  constraints: BoxConstraints(
                    maxWidth: 432,
                    maxHeight: constraints.maxHeight < 420
                        ? constraints.maxHeight
                        : constraints.maxHeight * 0.62,
                  ),
                  child: Material(
                    color: SsColors.canvas,
                    shape: const RoundedRectangleBorder(
                      side: BorderSide(color: SsColors.primary),
                    ),
                    child: SingleChildScrollView(
                      key: ValueKey(step),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          _TourHeading(step: step),
                          Padding(
                            padding: const EdgeInsets.fromLTRB(16, 10, 16, 12),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                Text(
                                  step.body,
                                  style: theme.textTheme.bodyMedium,
                                ),
                                const SizedBox(height: 12),
                                Semantics(
                                  label: 'مرحلهٔ $stage از $total',
                                  child: ExcludeSemantics(
                                    child: Row(
                                      children: [
                                        for (final item in TourStep.values)
                                          Expanded(
                                            child: Padding(
                                              padding:
                                                  const EdgeInsets.symmetric(
                                                    horizontal: 2,
                                                  ),
                                              child: ColoredBox(
                                                color: item.index <= step.index
                                                    ? SsColors.primary
                                                    : SsColors.line,
                                                child: const SizedBox(
                                                  height: 3,
                                                ),
                                              ),
                                            ),
                                          ),
                                        const SizedBox(width: 8),
                                        Text(
                                          '$stage از $total',
                                          style: theme.textTheme.labelMedium,
                                        ),
                                      ],
                                    ),
                                  ),
                                ),
                                if (_saveFailed) ...[
                                  const SizedBox(height: 8),
                                  Semantics(
                                    liveRegion: true,
                                    child: Text(
                                      'وضعیت راهنما ذخیره نشد. دوباره همان دکمه را '
                                      'بزنید یا بدون ذخیره ادامه دهید. (JN-TOUR-0001)',
                                      style: theme.textTheme.bodySmall
                                          ?.copyWith(
                                            color: theme.colorScheme.error,
                                          ),
                                    ),
                                  ),
                                  TextButton(
                                    onPressed: () => _finish(persist: false),
                                    child: const Text('ادامه بدون ذخیره'),
                                  ),
                                ],
                                const SizedBox(height: 10),
                                Wrap(
                                  alignment: WrapAlignment.spaceBetween,
                                  spacing: 8,
                                  runSpacing: 4,
                                  children: [
                                    FilledButton(
                                      autofocus: true,
                                      onPressed: _saving
                                          ? null
                                          : last
                                          ? _finish
                                          : () => _goTo(step.index + 1),
                                      child: Text(
                                        last
                                            ? 'پایان راهنما'
                                            : step == TourStep.welcome
                                            ? 'شروع راهنما'
                                            : 'مرحلهٔ بعد',
                                      ),
                                    ),
                                    if (step != TourStep.welcome)
                                      OutlinedButton(
                                        onPressed: _saving ? null : _back,
                                        child: const Text('قبلی'),
                                      ),
                                    if (!last)
                                      TextButton(
                                        onPressed: _saving ? null : _finish,
                                        child: const Text('رد کردن راهنما'),
                                      ),
                                  ],
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _TourHeading extends StatelessWidget {
  const _TourHeading({required this.step});

  final TourStep step;

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: SsColors.selected,
      child: SsDots(
        color: const Color(0x334B6E48),
        fadeToEnd: true,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          child: Row(
            children: [
              Transform.rotate(
                angle: math.pi / 4,
                child: DecoratedBox(
                  decoration: const BoxDecoration(color: SsColors.primary),
                  child: SizedBox.square(
                    dimension: 28,
                    child: Transform.rotate(
                      angle: -math.pi / 4,
                      child: Icon(step.icon, color: SsColors.canvas, size: 18),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Semantics(
                  header: true,
                  liveRegion: true,
                  child: Text(
                    step.title,
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _TourFocus extends InheritedWidget {
  const _TourFocus({
    required this.step,
    required this.anchor,
    required super.child,
  });

  final TourStep step;
  final GlobalKey anchor;

  @override
  bool updateShouldNotify(_TourFocus oldWidget) => step != oldWidget.step;
}

/// Draws attention to a live control while the tour blocks its real action.
class TourTarget extends StatelessWidget {
  const TourTarget({super.key, required this.step, required this.child});

  final TourStep step;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final focus = context.dependOnInheritedWidgetOfExactType<_TourFocus>();
    if (focus == null || focus.step != step) return child;
    return SizedBox(key: focus.anchor, child: child);
  }
}

class _TourBackdrop extends SingleChildRenderObjectWidget {
  const _TourBackdrop({required this.anchor, required super.child});

  final GlobalKey anchor;

  @override
  _TourBackdropBox createRenderObject(BuildContext context) =>
      _TourBackdropBox(anchor);

  @override
  void updateRenderObject(BuildContext context, _TourBackdropBox renderObject) {
    renderObject
      ..anchor = anchor
      ..markNeedsPaint();
  }
}

class _TourBackdropBox extends RenderProxyBox {
  _TourBackdropBox(this.anchor);

  GlobalKey anchor;

  @override
  void paint(PaintingContext context, Offset offset) {
    super.paint(context, offset);
    final bounds = offset & size;
    final veil = Path()..addRect(bounds);
    final target = anchor.currentContext?.findRenderObject();
    if (target is RenderBox && target.attached && target.hasSize) {
      final spotlight = MatrixUtils.transformRect(
        target.getTransformTo(this),
        Offset.zero & target.size,
      ).shift(offset).inflate(4).intersect(bounds);
      if (!spotlight.isEmpty) {
        veil
          ..fillType = PathFillType.evenOdd
          ..addRect(spotlight);
        context.canvas.drawRect(
          spotlight.deflate(1),
          Paint()
            ..color = SsColors.primary
            ..style = PaintingStyle.stroke
            ..strokeWidth = 2,
        );
      }
    }
    context.canvas.drawPath(veil, Paint()..color = const Color(0x70334433));
  }
}
