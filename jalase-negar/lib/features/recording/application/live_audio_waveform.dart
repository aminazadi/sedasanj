import 'dart:math' as math;

import 'package:flutter/foundation.dart';

/// A short history of measured PCM amplitudes in equal-duration windows.
class LiveAudioWaveform extends ChangeNotifier {
  LiveAudioWaveform({required int sampleRate})
    : assert(sampleRate >= 50),
      _samplesPerBar = sampleRate ~/ 50;

  static const barCount = 48;

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

  void _addSample(int sample) {
    _sumOfSquares += sample * sample;
    _samples++;
    if (_samples < _samplesPerBar) return;
    final rms = math.sqrt(_sumOfSquares / _samples) / 32768;
    _bars[_writtenBars % barCount] = (rms * 5).clamp(0.0, 1.0);
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
    notifyListeners();
  }
}
