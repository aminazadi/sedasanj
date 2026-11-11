import 'dart:math' as math;
import 'dart:typed_data';

/// Root-mean-square level of mono PCM16 bytes, 0..1 (full scale = 1).
double pcm16Rms(Uint8List bytes) {
  final n = bytes.length ~/ 2;
  if (n == 0) return 0;
  final view = ByteData.sublistView(bytes);
  var sum = 0.0;
  for (var i = 0; i < n; i++) {
    final s = view.getInt16(i * 2, Endian.little) / 32768.0;
    sum += s * s;
  }
  return math.sqrt(sum / n);
}

/// Decides which microphones really carry a voice in a short window, so that
/// speech leaking from a neighbour's microphone is not transcribed twice.
///
/// With one close microphone per person, the person talking is loudest on
/// their own channel. A channel is an *owner* of the window when it is above
/// [floor] and within [marginDb] of the loudest channel. Two people talking at
/// the same time are both kept when their levels are close.
class ChannelGate {
  const ChannelGate({this.marginDb = 9.0, this.floor = 0.004});

  /// How far below the loudest channel a channel may be and still count as
  /// real speech. Typical bleed between close mics is 12-20 dB down.
  final double marginDb;

  /// Below this RMS a channel is treated as silence.
  final double floor;

  /// Owners among [rms] (one value per channel, 0..1).
  Set<int> owners(List<double> rms) {
    var loudest = 0.0;
    for (final r in rms) {
      if (r > loudest) loudest = r;
    }
    if (loudest < floor) return const <int>{};
    final threshold = loudest * math.pow(10, -marginDb / 20);
    return {
      for (var c = 0; c < rms.length; c++)
        if (rms[c] >= floor && rms[c] >= threshold) c,
    };
  }
}
