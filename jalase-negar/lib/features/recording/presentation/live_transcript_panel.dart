import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../application/live_transcript_session.dart';

/// Live transcript of what is being said during recording.
///
/// Only what is being typed right now is on screen: the last few lines scroll
/// up smoothly, older ones fade away at the top, and the newest words fade in
/// behind a blinking caret. The whole text is still saved with the meeting.
/// Typing is fast and speeds up further when lines wait, so the screen never
/// falls behind the recognizer.
class LiveTranscriptPanel extends StatefulWidget {
  const LiveTranscriptPanel({
    super.key,
    required this.state,
    this.bare = false,
  });

  final ValueListenable<LiveTranscriptState> state;

  /// Just the text: no frame, no header, no background. The recording screen
  /// uses it at the top of the page.
  final bool bare;

  @override
  State<LiveTranscriptPanel> createState() => _LiveTranscriptPanelState();
}

class _LiveTranscriptPanelState extends State<LiveTranscriptPanel> {
  final ScrollController _scroll = ScrollController();

  /// Lines kept on screen; older ones are not built at all.
  static const int _shownLines = 6;

  /// Lines at the end of the list that are not fully typed yet; the first of
  /// them is shown up to [_typedChars] characters.
  int _pending = 0;
  int _typedChars = 0;
  List<String> _lastLines = const [];
  Timer? _typer;

  @override
  void initState() {
    super.initState();
  }

  @override
  void dispose() {
    _typer?.cancel();
    _scroll.dispose();
    super.dispose();
  }

  /// Works out how many lines are new since the last build. The lines list is
  /// rebuilt (and trimmed at its cap) on every update, so the new ones are
  /// found after the last line seen before, compared by identity.
  void _noteLines(List<String> lines) {
    final old = _lastLines;
    _lastLines = lines;
    if (identical(old, lines)) return;
    var added = 0;
    if (old.isEmpty) {
      // First build with existing text (screen reopened): show it as it is.
      added = 0;
    } else {
      final at = lines.lastIndexWhere((l) => identical(l, old.last));
      added = at < 0 ? 0 : lines.length - 1 - at;
    }
    if (_lastSeenOnce && old.isEmpty) added = lines.length;
    _lastSeenOnce = true;
    if (added > 0) {
      _pending = math.min(lines.length, _pending + added);
      _startTyping();
    } else {
      _pending = math.min(_pending, lines.length);
    }
  }

  bool _lastSeenOnce = false;

  void _startTyping() {
    _typer ??= Timer.periodic(const Duration(milliseconds: 16), (_) => _tick());
  }

  void _tick() {
    if (!mounted) return;
    if (_pending == 0) {
      _typer?.cancel();
      _typer = null;
      return;
    }
    final lines = _lastLines;
    var waiting = 0;
    for (var i = lines.length - _pending; i < lines.length; i++) {
      waiting += lines[i].length;
    }
    waiting -= _typedChars;
    // About 250 characters a second, much more when text is queued.
    var step = 4 + waiting ~/ 12;
    setState(() {
      while (step > 0 && _pending > 0) {
        final line = lines[lines.length - _pending];
        final room = line.length - _typedChars;
        if (step < room) {
          _typedChars += step;
          step = 0;
        } else {
          step -= room;
          _typedChars = 0;
          _pending--;
        }
      }
    });
    _followEnd();
  }

  void _followEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_scroll.hasClients) return;
      final end = _scroll.position.maxScrollExtent;
      if ((end - _scroll.position.pixels).abs() < 0.5) return;
      _scroll.animateTo(
        end,
        duration: const Duration(milliseconds: 320),
        curve: Curves.easeOutQuart,
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return ValueListenableBuilder<LiveTranscriptState>(
      valueListenable: widget.state,
      builder: (context, live, _) {
        _noteLines(live.lines);
        final shownCount = live.lines.length - _pending;
        final visible = _pending == 0 ? live.lines.length : shownCount + 1;
        final first = math.max(0, visible - _shownLines);
        if (_pending > 0) _followEnd();
        return Semantics(
          container: true,
          label: 'متن زنده‌ی جلسه',
          child: DecoratedBox(
            decoration: widget.bare
                ? const BoxDecoration()
                : BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.6),
                    border: Border.all(color: SsColors.line),
                  ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (!widget.bare) ...[
                  _Header(live: live),
                  const Divider(height: 1, color: SsColors.line),
                ],
                Expanded(
                  child: live.lines.isEmpty
                      ? _EmptyHint(live: live)
                      : ShaderMask(
                          blendMode: BlendMode.dstIn,
                          shaderCallback: (rect) {
                            // Older lines fade out at the top, but only once
                            // the text has scrolled: the first lines of a
                            // meeting must stay fully readable.
                            final scrolled =
                                _scroll.hasClients && _scroll.offset > 1;
                            final fade = widget.bare ? 72.0 : 0.4 * rect.height;
                            final end = (fade / rect.height).clamp(0.0, 1.0);
                            return LinearGradient(
                              begin: Alignment.topCenter,
                              end: Alignment.bottomCenter,
                              colors: [
                                scrolled ? Colors.transparent : Colors.black,
                                Colors.black,
                              ],
                              stops: [0, end],
                            ).createShader(rect);
                          },
                          child: ListView.separated(
                            controller: _scroll,
                            physics: const NeverScrollableScrollPhysics(),
                            padding: EdgeInsets.fromLTRB(
                              widget.bare ? 4 : 12,
                              widget.bare ? 8 : 28,
                              widget.bare ? 4 : 12,
                              widget.bare ? 4 : 12,
                            ),
                            itemCount: visible - first,
                            separatorBuilder: (_, _) =>
                                const SizedBox(height: 10),
                            itemBuilder: (context, i) {
                              final index = first + i;
                              final line = live.lines[index];
                              final typing = index >= shownCount;
                              final fromEnd = visible - 1 - index;
                              return _Entrance(
                                key: ValueKey(index),
                                child: AnimatedOpacity(
                                  duration: const Duration(milliseconds: 350),
                                  opacity: switch (fromEnd) {
                                    0 => 1.0,
                                    1 => 0.82,
                                    2 => 0.68,
                                    _ => 0.55,
                                  },
                                  child: _FadingLine(
                                    text: typing
                                        ? line.substring(
                                            0,
                                            math.min(_typedChars, line.length),
                                          )
                                        : line,
                                    typing: typing && index == visible - 1,
                                    style:
                                        (widget.bare
                                                ? textTheme.bodyLarge
                                                : textTheme.bodyMedium)
                                            ?.copyWith(height: 1.8),
                                  ),
                                ),
                              );
                            },
                          ),
                        ),
                ),
                if (live.note != null && live.lines.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
                    child: Text(
                      live.note!,
                      style: textTheme.bodySmall?.copyWith(
                        color: live.phase == LivePhase.failed
                            ? SsColors.danger
                            : SsColors.warning,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }
}

/// A new line slides up a few pixels while it fades in, so text arrives
/// instead of jumping onto the screen. Plays once, when the line is first
/// built.
class _Entrance extends StatelessWidget {
  const _Entrance({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    if (MediaQuery.disableAnimationsOf(context)) return child;
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: const Duration(milliseconds: 420),
      curve: Curves.easeOutCubic,
      builder: (context, t, child) => Opacity(
        opacity: t,
        child: Transform.translate(
          offset: Offset(0, (1 - t) * 14),
          child: child,
        ),
      ),
      child: child,
    );
  }
}

/// One line whose newest words fade in, followed by a blinking caret while it
/// is being typed. Fading is per word (never inside a word) so Persian letters
/// keep joining.
class _FadingLine extends StatefulWidget {
  const _FadingLine({
    required this.text,
    required this.typing,
    required this.style,
  });

  final String text;
  final bool typing;
  final TextStyle? style;

  @override
  State<_FadingLine> createState() => _FadingLineState();
}

class _FadingLineState extends State<_FadingLine>
    with SingleTickerProviderStateMixin {
  late final AnimationController _blink;

  @override
  void initState() {
    super.initState();
    _blink = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 700),
    );
    if (widget.typing) _blink.repeat(reverse: true);
  }

  @override
  void didUpdateWidget(_FadingLine old) {
    super.didUpdateWidget(old);
    if (widget.typing && !_blink.isAnimating) {
      _blink.repeat(reverse: true);
    } else if (!widget.typing && _blink.isAnimating) {
      _blink.stop();
    }
  }

  @override
  void dispose() {
    _blink.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final base = widget.style ?? const TextStyle();
    final color = base.color ?? SsColors.ink;
    final spans = <InlineSpan>[];
    if (widget.typing) {
      final words = widget.text.split(' ');
      const fading = 4;
      for (var i = 0; i < words.length; i++) {
        final fromEnd = words.length - 1 - i;
        final alpha = fromEnd >= fading
            ? 1.0
            : 0.35 + 0.65 * (1 - fromEnd / fading);
        spans.add(
          TextSpan(
            text: i == 0 ? words[i] : ' ${words[i]}',
            style: TextStyle(color: color.withValues(alpha: alpha)),
          ),
        );
      }
      spans.add(
        WidgetSpan(
          alignment: PlaceholderAlignment.middle,
          child: FadeTransition(
            opacity: _blink,
            child: Container(
              width: 2,
              height: 16,
              margin: const EdgeInsetsDirectional.only(start: 3),
              color: SsColors.primary,
            ),
          ),
        ),
      );
    } else {
      spans.add(TextSpan(text: widget.text));
    }
    return Text.rich(TextSpan(style: base, children: spans));
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.live});

  final LiveTranscriptState live;

  @override
  Widget build(BuildContext context) {
    final (label, color) = switch (live.phase) {
      LivePhase.preparing => ('در حال آماده‌سازی…', SsColors.warning),
      LivePhase.listening when live.speaking => (
        'در حال شنیدن…',
        SsColors.primary,
      ),
      LivePhase.listening => ('زنده', SsColors.success),
      LivePhase.lagging => ('کمی عقب است', SsColors.warning),
      LivePhase.failed => ('متوقف شد', SsColors.danger),
      LivePhase.off => ('خاموش', SsColors.neutral),
    };
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: Row(
        children: [
          const Icon(Icons.subtitles_outlined, size: 18, color: SsColors.ink),
          const SizedBox(width: 8),
          Text('متن زنده', style: Theme.of(context).textTheme.titleSmall),
          const Spacer(),
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 6),
          Text(
            label,
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: color),
          ),
        ],
      ),
    );
  }
}

class _EmptyHint extends StatelessWidget {
  const _EmptyHint({required this.live});

  final LiveTranscriptState live;

  @override
  Widget build(BuildContext context) {
    final text =
        live.note ??
        switch (live.phase) {
          LivePhase.preparing =>
            'مدل در حال آماده‌سازی است؛ ضبط از همین حالا انجام می‌شود.',
          LivePhase.failed => 'متن زنده در دسترس نیست.',
          _ =>
            'شروع به صحبت کنید؛ متن هر جمله پس از یک مکث کوتاه اینجا ظاهر می‌شود.',
        };
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Text(
          text,
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.bodySmall,
        ),
      ),
    );
  }
}
