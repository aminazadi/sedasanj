import 'dart:math' as math;
import 'dart:typed_data';

/// A speech region in seconds.
class SpeechRegion {
  const SpeechRegion(this.start, this.end);

  final double start;
  final double end;
}

/// Port of the server's energy VAD (`aiservice/asr_service/services/
/// speech_segmentation.py::vad_regions`).
///
/// Only the server-parity test mode uses it, so a transcript can be compared
/// with the server's one region by region; normal transcription uses Silero.
/// The whole channel must be in memory, so callers limit it to short clips.
///
/// 30 ms RMS frames; speech threshold is the largest of three times the 20th
/// percentile energy, 8 % of the peak energy and 1e-5; gaps up to 0.35 s are
/// bridged; regions shorter than [minSeconds] are dropped, the rest is padded
/// by [paddingSeconds] and regions closer than 0.35 s are merged.
List<SpeechRegion> energyVadRegions(
  Float32List mono,
  int sampleRate, {
  double minSeconds = 0.3,
  double paddingSeconds = 0.2,
}) {
  final duration = mono.length / math.max(sampleRate, 1);
  final frameSamples = math.max(1, (sampleRate * 0.03).toInt());
  final energy = <double>[];
  for (var index = 0; index < mono.length; index += frameSamples) {
    final end = math.min(mono.length, index + frameSamples);
    var sumSquares = 0.0;
    for (var i = index; i < end; i++) {
      sumSquares += mono[i] * mono[i];
    }
    energy.add(math.sqrt(sumSquares / (end - index)));
  }
  if (energy.isEmpty) return const [];
  final peak = energy.reduce(math.max);
  if (peak <= 1e-6) return const [];

  final threshold = math.max(
    math.max(_percentile(energy, 20) * 3.0, peak * 0.08),
    1e-5,
  );
  final bridge = math.max(1, (0.35 / 0.03).toInt());
  var lastActive = -bridge - 1;
  int? start;
  final raw = <SpeechRegion>[];
  for (var index = 0; index < energy.length; index++) {
    if (energy[index] >= threshold) {
      if (start == null && index - lastActive > bridge) start = index;
      lastActive = index;
    }
    if (start != null && index - lastActive > bridge) {
      raw.add(
        SpeechRegion(start * 0.03, math.min(duration, (lastActive + 1) * 0.03)),
      );
      start = null;
    }
  }
  if (start != null) {
    raw.add(
      SpeechRegion(start * 0.03, math.min(duration, (lastActive + 1) * 0.03)),
    );
  }
  return _mergeRegions(
    raw,
    minSeconds: minSeconds,
    paddingSeconds: paddingSeconds,
    duration: duration,
  );
}

List<SpeechRegion> _mergeRegions(
  List<SpeechRegion> regions, {
  required double minSeconds,
  required double paddingSeconds,
  required double duration,
}) {
  final padded = [
    for (final item in regions)
      if (item.end - item.start >= minSeconds)
        SpeechRegion(
          math.max(0.0, item.start - paddingSeconds),
          math.min(duration, item.end + paddingSeconds),
        ),
  ]..sort((a, b) => a.start.compareTo(b.start));
  final merged = <SpeechRegion>[];
  for (final item in padded) {
    if (merged.isNotEmpty && item.start <= merged.last.end + 0.35) {
      final previous = merged.last;
      merged[merged.length - 1] = SpeechRegion(
        previous.start,
        math.max(previous.end, item.end),
      );
    } else {
      merged.add(item);
    }
  }
  return merged;
}

/// numpy.percentile with linear interpolation.
double _percentile(List<double> values, double percent) {
  final sorted = [...values]..sort();
  final position = (sorted.length - 1) * percent / 100.0;
  final lower = position.floor();
  final upper = position.ceil();
  if (lower == upper) return sorted[lower];
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
}
