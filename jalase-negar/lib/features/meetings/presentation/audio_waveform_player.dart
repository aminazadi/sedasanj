import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:just_audio/just_audio.dart';
import 'package:share_plus/share_plus.dart';

import '../../../app/theme.dart';
import '../../../core/utils/format.dart';

const _barCount = 84;
const _playbackRates = [1.0, 1.25, 1.5, 2.0];
const _wavHeaderSize = 44;

/// Peaks (0.12..1) of a PCM16 WAV file; runs in an isolate.
List<double> _buildPeaks(String path) {
  final bytes = File(path).readAsBytesSync();
  if (bytes.length <= _wavHeaderSize + 2) return const [];
  final data = ByteData.sublistView(bytes);
  final samples = (bytes.length - _wavHeaderSize) ~/ 2;
  final block = (samples ~/ _barCount).clamp(1, samples);
  final peaks = List<double>.filled(_barCount, 0);
  for (var i = 0; i < _barCount; i++) {
    final start = i * block;
    final end = (start + block).clamp(0, samples);
    var peak = 0;
    for (var s = start; s < end; s += 4) {
      final v = data.getInt16(_wavHeaderSize + s * 2, Endian.little).abs();
      if (v > peak) peak = v;
    }
    peaks[i] = peak / 32768;
  }
  final maximum = peaks.reduce((a, b) => a > b ? a : b).clamp(0.01, 1.0);
  return [for (final p in peaks) (p / maximum).clamp(0.12, 1.0)];
}

final _emptyWaveform = [
  for (var i = 0; i < _barCount; i++) 0.18 + ((i * 17) % 11) / 18,
];

/// Fixed bottom player that mirrors the web panel's waveform player.
class AudioWaveformPlayer extends StatefulWidget {
  const AudioWaveformPlayer({super.key, required this.path});

  final String path;

  @override
  State<AudioWaveformPlayer> createState() => _AudioWaveformPlayerState();
}

class _AudioWaveformPlayerState extends State<AudioWaveformPlayer> {
  final _player = AudioPlayer();
  List<double> _peaks = _emptyWaveform;
  double _rate = 1;
  bool _muted = false;
  bool _failed = false;
  double? _dragRatio;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant AudioWaveformPlayer old) {
    super.didUpdateWidget(old);
    if (old.path != widget.path) _load();
  }

  Future<void> _load() async {
    try {
      await _player.setFilePath(widget.path);
      if (mounted) setState(() => _failed = false);
    } catch (_) {
      if (mounted) setState(() => _failed = true);
      return;
    }
    try {
      final peaks = await compute(_buildPeaks, widget.path);
      if (mounted && peaks.isNotEmpty) setState(() => _peaks = peaks);
    } catch (_) {
      // Keep the placeholder waveform.
    }
  }

  @override
  void dispose() {
    _player.dispose();
    super.dispose();
  }

  void _toggle() {
    if (_player.playing) {
      _player.pause();
      return;
    }
    if (_player.processingState == ProcessingState.completed) {
      _player.seek(Duration.zero);
    }
    _player.play();
  }

  void _seekToRatio(double ratio) {
    final total = _player.duration;
    if (total == null || total == Duration.zero) return;
    _player.seek(total * ratio.clamp(0.0, 1.0));
  }

  void _cycleRate() {
    final next =
        _playbackRates[(_playbackRates.indexOf(_rate) + 1) %
            _playbackRates.length];
    _player.setSpeed(next);
    setState(() => _rate = next);
  }

  void _toggleMute() {
    _muted = !_muted;
    _player.setVolume(_muted ? 0 : 1);
    setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Material(
      color: Colors.white,
      elevation: 8,
      child: DecoratedBox(
        decoration: const BoxDecoration(
          border: Border(top: BorderSide(color: SsColors.line)),
        ),
        child: SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
            child: _failed ? _buildError(theme) : _buildPlayer(theme),
          ),
        ),
      ),
    );
  }

  Widget _buildError(ThemeData theme) => Text(
    'فایل صوتی قابل پخش نیست.',
    style: theme.textTheme.bodySmall?.copyWith(color: SsColors.danger),
  );

  Widget _buildPlayer(ThemeData theme) {
    return StreamBuilder<Duration>(
      stream: _player.positionStream,
      builder: (context, snapshot) {
        final total = _player.duration ?? Duration.zero;
        final position = snapshot.data ?? Duration.zero;
        final ratio =
            _dragRatio ??
            (total.inMilliseconds > 0
                ? (position.inMilliseconds / total.inMilliseconds).clamp(
                    0.0,
                    1.0,
                  )
                : 0.0);
        final shown = _dragRatio != null ? total * ratio : position;
        return Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _Waveform(
              peaks: _peaks,
              progress: ratio,
              onSeek: _seekToRatio,
              onDrag: (value) => setState(() => _dragRatio = value),
              onDragEnd: (value) {
                _seekToRatio(value);
                setState(() => _dragRatio = null);
              },
            ),
            const SizedBox(height: 8),
            _buildControls(theme, shown, total),
          ],
        );
      },
    );
  }

  Widget _buildControls(ThemeData theme, Duration position, Duration total) {
    return StreamBuilder<PlayerState>(
      stream: _player.playerStateStream,
      builder: (context, snapshot) {
        final state = snapshot.data;
        final playing =
            (state?.playing ?? false) &&
            state?.processingState != ProcessingState.completed;
        return Row(
          children: [
            SizedBox(
              width: 44,
              height: 44,
              child: IconButton.filled(
                tooltip: playing ? 'توقف پخش' : 'پخش فایل صوتی',
                style: IconButton.styleFrom(
                  backgroundColor: SsColors.primary,
                  foregroundColor: SsColors.canvas,
                  shape: const RoundedRectangleBorder(),
                ),
                onPressed: _toggle,
                icon: Icon(playing ? Icons.pause : Icons.play_arrow, size: 24),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                playing ? 'در حال پخش' : 'آماده پخش',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: SsColors.neutral,
                ),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              flex: 2,
              child: FittedBox(
                fit: BoxFit.scaleDown,
                alignment: AlignmentDirectional.centerEnd,
                child: Text(
                  '${formatDuration(position)} / ${formatDuration(total)}',
                  textDirection: TextDirection.ltr,
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: SsColors.neutral,
                    fontFeatures: const [FontFeature.tabularFigures()],
                  ),
                ),
              ),
            ),
            const SizedBox(width: 6),
            _ControlButton(
              tooltip: _muted ? 'فعال‌کردن صدا' : 'قطع صدا',
              onPressed: _toggleMute,
              child: Icon(
                _muted ? Icons.volume_off : Icons.volume_up,
                size: 18,
              ),
            ),
            _ControlButton(
              tooltip: 'افزایش سرعت پخش',
              onPressed: _cycleRate,
              child: Text(
                '${toPersianDigits(_rate.toString().replaceAll('.0', ''))}×',
                style: theme.textTheme.labelMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            _ControlButton(
              tooltip: 'اشتراک‌گذاری فایل صوتی',
              onPressed: () => SharePlus.instance.share(
                ShareParams(files: [XFile(widget.path)]),
              ),
              child: const Icon(Icons.ios_share, size: 18),
            ),
          ],
        );
      },
    );
  }
}

class _ControlButton extends StatelessWidget {
  const _ControlButton({
    required this.tooltip,
    required this.onPressed,
    required this.child,
  });

  final String tooltip;
  final VoidCallback onPressed;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: SizedBox(
        width: 42,
        height: 44,
        child: InkWell(
          onTap: onPressed,
          child: Center(
            child: Container(
              width: 36,
              height: 36,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: SsColors.canvas,
                border: Border.all(color: SsColors.line),
              ),
              child: child,
            ),
          ),
        ),
      ),
    );
  }
}

class _Waveform extends StatelessWidget {
  const _Waveform({
    required this.peaks,
    required this.progress,
    required this.onSeek,
    required this.onDrag,
    required this.onDragEnd,
  });

  final List<double> peaks;
  final double progress;
  final ValueChanged<double> onSeek;
  final ValueChanged<double> onDrag;
  final ValueChanged<double> onDragEnd;

  @override
  Widget build(BuildContext context) {
    return Directionality(
      textDirection: TextDirection.ltr,
      child: LayoutBuilder(
        builder: (context, box) {
          double ratioOf(double dx) => (dx / box.maxWidth).clamp(0.0, 1.0);
          return GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTapUp: (d) => onSeek(ratioOf(d.localPosition.dx)),
            onHorizontalDragUpdate: (d) => onDrag(ratioOf(d.localPosition.dx)),
            onHorizontalDragEnd: (_) => onDragEnd(progress),
            child: SizedBox(
              height: 56,
              width: double.infinity,
              child: CustomPaint(
                painter: _WaveformPainter(peaks: peaks, progress: progress),
              ),
            ),
          );
        },
      ),
    );
  }
}

class _WaveformPainter extends CustomPainter {
  _WaveformPainter({required this.peaks, required this.progress});

  final List<double> peaks;
  final double progress;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(
      Offset.zero & size,
      Paint()..color = SsColors.canvas.withValues(alpha: 0.6),
    );
    final midY = size.height / 2;
    canvas.drawLine(
      Offset(0, midY),
      Offset(size.width, midY),
      Paint()
        ..color = SsColors.accent.withValues(alpha: 0.6)
        ..strokeWidth = 1,
    );
    final slot = size.width / peaks.length;
    final active = (progress * peaks.length).round();
    for (var i = 0; i < peaks.length; i++) {
      final h = (peaks[i] * (size.height - 8)).clamp(6.0, size.height - 4);
      final paint = Paint()
        ..color = i < active
            ? SsColors.primary
            : SsColors.accent.withValues(alpha: 0.72);
      canvas.drawRect(
        Rect.fromCenter(
          center: Offset(slot * i + slot / 2, midY),
          width: (slot - 1.5).clamp(1.0, 6.0),
          height: h,
        ),
        paint,
      );
    }
    final x = (progress * size.width).clamp(1.0, size.width - 1);
    canvas.drawRect(
      Rect.fromLTWH(x - 1, 2, 2, size.height - 4),
      Paint()..color = SsColors.primary,
    );
  }

  @override
  bool shouldRepaint(_WaveformPainter old) =>
      old.progress != progress || old.peaks != peaks;
}
