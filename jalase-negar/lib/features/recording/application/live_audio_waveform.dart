import 'dart:math' as math;

import 'package:flutter/foundation.dart';

/// A short history of measured PCM amplitudes in equal-duration windows.
class LiveAudioWaveform extends ChangeNotifier {
  LiveAudioWaveform({required int sampleRate})
    : assert(sampleRate >= 50),
      _samplesPerBar = sampleRate ~/ 50;

  static const barCount = 48;

  /// Quietest level drawn (dBFS); bars are 0 here and full at 0 dBFS.
  static const floorDb = -60.0;

  /// Maps an RMS level (0..1, full scale = 1) to a bar height 0..1 on a dB
  /// scale, so ordinary speech (about -30 dBFS) sits mid-height and only a
  /// signal near full scale fills the bar. A linear `rms * 5` filled the bar
  /// at -14 dBFS, which made a normal digital input look over-sensitive.
  static double barFor(double rms) {
    if (rms <= 0) return 0;
    final db = 20 * math.log(rms) / math.ln10;
    return ((db - floorDb) / -floorDb).clamp(0.0, 1.0);
  }

  /// Largest sample (0..1) seen since [clear]; 1.0 means the signal hit full
  /// scale and was cut.
  double peak = 0;

  /// True once a sample reached full scale in this recording.
  bool get clipped => peak >= 0.999;

  final int _samplesPerBar;
  final _bars = Float32List(barCount);
  int _writtenBars = 0;
  int _samples = 0;
  int _sumOfSquares = 0;
  int? _trailingByte;

  double amplitudeAt(int index) => _bars[(_writtenBars + index) % barCount];

  void addPcm(Uint8List pcm) {
    if (pcm.isEmpty) return;
    final data = ByteData.sublistView(pcm);
    final previousBar = _writtenBars;
    var offset = 0;
    final trailingByte = _trailingByte;
    if (trailingByte != null) {
      final value = trailingByte | (pcm.first << 8);
      _addSample(value.toSigned(16));
      offset++;
    }
    for (; offset + 1 < pcm.length; offset += 2) {
      _addSample(data.getInt16(offset, Endian.little));
    }
    _trailingByte = offset < pcm.length ? pcm[offset] : null;
    if (_writtenBars != previousBar) notifyListeners();
  }

  /// Pushes one bar from a mean-square power reading (0..1), for callers that
  /// only receive a level and not raw PCM.
  void addPower(double power) {
    final rms = math.sqrt(power.clamp(0.0, 1.0));
    _bars[_writtenBars % barCount] = barFor(rms);
    _writtenBars++;
    notifyListeners();
  }

  void _addSample(int sample) {
    _sumOfSquares += sample * sample;
    final level = sample.abs() / 32768;
    if (level > peak) peak = level;
    _samples++;
    if (_samples < _samplesPerBar) return;
    final rms = math.sqrt(_sumOfSquares / _samples) / 32768;
    _bars[_writtenBars % barCount] = barFor(rms);
    _writtenBars++;
    _samples = 0;
    _sumOfSquares = 0;
  }

  void clear() {
    _bars.fillRange(0, barCount, 0);
    _writtenBars = 0;
    _samples = 0;
    _sumOfSquares = 0;
    _trailingByte = null;
    peak = 0;
    notifyListeners();
  }
}
