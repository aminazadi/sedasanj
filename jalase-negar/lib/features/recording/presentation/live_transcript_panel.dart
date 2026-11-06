import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../application/live_transcript_session.dart';

/// Live transcript of what is being said during recording.
///
/// New lines are typed out character by character and scroll into view unless
/// the person has scrolled up to re-read. Typing speeds up when several lines
/// wait, so the screen never falls behind the recognizer.
class LiveTranscriptPanel extends StatefulWidget {
  const LiveTranscriptPanel({super.key, required this.state});

  final ValueListenable<LiveTranscriptState> state;

  @override
  State<LiveTranscriptPanel> createState() => _LiveTranscriptPanelState();
}

class _LiveTranscriptPanelState extends State<LiveTranscriptPanel> {
  final ScrollController _scroll = ScrollController();
  bool _stickToEnd = true;

  /// Lines at the end of the list that are not fully typed yet; the first of
  /// them is shown up to [_typedChars] characters.
  int _pending = 0;
  int _typedChars = 0;
  List<String> _lastLines = const [];
  Timer? _typer;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_onScroll);
  }

  @override
  void dispose() {
    _typer?.cancel();
    _scroll.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (!_scroll.hasClients) return;
    final position = _scroll.position;
    _stickToEnd = position.pixels >= position.maxScrollExtent - 48;
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
    _typer ??= Timer.periodic(const Duration(milliseconds: 30), (_) => _tick());
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
    // About 65 characters a second, more when text is queued.
    var step = 2 + waiting ~/ 60;
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
    if (!_stickToEnd) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_scroll.hasClients) return;
      _scroll.jumpTo(_scroll.position.maxScrollExtent);
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
        if (_pending > 0) _followEnd();
        return Semantics(
          container: true,
          label: 'متن زنده‌ی جلسه',
          child: DecoratedBox(
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.6),
              border: Border.all(color: SsColors.line),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _Header(live: live),
                const Divider(height: 1, color: SsColors.line),
                Expanded(
                  child: live.lines.isEmpty
                      ? _EmptyHint(live: live)
                      : ListView.separated(
                          controller: _scroll,
                          padding: const EdgeInsets.all(12),
                          itemCount: visible,
                          separatorBuilder: (_, _) => const SizedBox(height: 8),
                          itemBuilder: (context, index) {
                            final line = live.lines[index];
                            final typing = index >= shownCount;
                            return Text(
                              typing
                                  ? line.substring(
                                      0,
                                      math.min(_typedChars, line.length),
                                    )
                                  : line,
                              style: textTheme.bodyMedium?.copyWith(
                                height: 1.7,
                              ),
                            );
                          },
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
