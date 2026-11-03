import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../application/live_transcript_session.dart';

/// Live draft of what is being said, shown under the waveform while recording.
///
/// New lines scroll into view unless the person has scrolled up to re-read.
class LiveTranscriptPanel extends StatefulWidget {
  const LiveTranscriptPanel({super.key, required this.state});

  final ValueListenable<LiveTranscriptState> state;

  @override
  State<LiveTranscriptPanel> createState() => _LiveTranscriptPanelState();
}

class _LiveTranscriptPanelState extends State<LiveTranscriptPanel> {
  final ScrollController _scroll = ScrollController();
  int _shownLines = 0;
  bool _stickToEnd = true;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_onScroll);
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (!_scroll.hasClients) return;
    final position = _scroll.position;
    _stickToEnd = position.pixels >= position.maxScrollExtent - 48;
  }

  void _followEnd(int lineCount) {
    if (lineCount == _shownLines) return;
    _shownLines = lineCount;
    if (!_stickToEnd) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 220),
        curve: Curves.easeOut,
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return ValueListenableBuilder<LiveTranscriptState>(
      valueListenable: widget.state,
      builder: (context, live, _) {
        _followEnd(live.lines.length);
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
                          itemCount: live.lines.length,
                          separatorBuilder: (_, _) => const SizedBox(height: 8),
                          itemBuilder: (context, index) => Text(
                            live.lines[index],
                            style: textTheme.bodyMedium?.copyWith(height: 1.7),
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
                if (live.lines.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
                    child: Text(
                      'پیش‌نویس زنده؛ بعد از ضبط می‌توانید «رونویسی کامل» بگیرید.',
                      style: textTheme.bodySmall,
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
