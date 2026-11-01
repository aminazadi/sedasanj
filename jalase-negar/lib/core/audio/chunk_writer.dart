import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'wav.dart';

/// A closed, self-contained WAV chunk of a meeting recording.
class ChunkInfo {
  const ChunkInfo({
    required this.seq,
    required this.path,
    required this.startMs,
    required this.endMs,
    required this.bytes,
  });

  final int seq;
  final String path;
  final int startMs;
  final int endMs;
  final int bytes;
}

/// Splits a mono PCM16 stream into WAV chunks of about [minCutMs]..[maxMs].
///
/// A chunk is cut at the first quiet stretch of at least [silenceMs] after
/// [minCutMs] so words are not split; [maxMs] forces a cut when the room never
/// goes quiet. All times are derived from the number of samples written, never
/// from the wall clock, so they match the audio exactly.
class ChunkWriter {
  ChunkWriter({
    required this.dir,
    required this.onChunk,
    this.sampleRate = 16000,
    this.minCutMs = 45000,
    this.maxMs = 90000,
    this.silenceMs = 300,
    this.silenceRms = 0.01,
    this.startSeq = 0,
    this.startOffsetMs = 0,
  }) : _seq = startSeq,
       _chunkStartMs = startOffsetMs;

  final Directory dir;
  final void Function(ChunkInfo chunk) onChunk;
  final int sampleRate;
  final int minCutMs;
  final int maxMs;
  final int silenceMs;

  /// Normalized RMS (0..1) below which a buffer counts as silence.
  final double silenceRms;
  final int startSeq;
  final int startOffsetMs;

  WavFileWriter? _writer;
  String? _path;
  int _seq;
  int _chunkStartMs;
  int _chunkSamples = 0;
  int _quietSamples = 0;
  int _totalSamples = 0;
  Future<void> _queue = Future.value();

  /// Total audio written so far, derived from samples.
  Duration get duration => Duration(
    milliseconds: startOffsetMs + _totalSamples * 1000 ~/ sampleRate,
  );

  int get nextSeq => _seq;

  static String fileName(int seq) => '${seq.toString().padLeft(6, '0')}.wav';

  /// Appends PCM16 mono bytes. Safe to call without awaiting: calls are
  /// serialized, and a failure is rethrown by the next [add] / [close].
  Future<void> add(Uint8List pcm16) {
    _queue = _queue.then((_) => _add(pcm16));
    return _queue;
  }

  Future<void> _add(Uint8List pcm16) async {
    final samples = pcm16.length ~/ 2;
    if (samples == 0) return;
    if (_writer == null) await _openChunk();
    await _writer!.add(pcm16);
    _chunkSamples += samples;
    _totalSamples += samples;

    if (_rms(pcm16, samples) < silenceRms) {
      _quietSamples += samples;
    } else {
      _quietSamples = 0;
    }
    final chunkMs = _chunkSamples * 1000 ~/ sampleRate;
    final quietMs = _quietSamples * 1000 ~/ sampleRate;
    if (chunkMs >= maxMs || (chunkMs >= minCutMs && quietMs >= silenceMs)) {
      await _closeChunk();
    }
  }

  Future<void> _openChunk() async {
    await dir.create(recursive: true);
    _path = '${dir.path}/${fileName(_seq)}';
    _writer = await WavFileWriter.open(
      File(_path!),
      sampleRate: sampleRate,
      channels: 1,
    );
    _chunkSamples = 0;
    _quietSamples = 0;
  }

  Future<void> _closeChunk() async {
    final writer = _writer;
    final path = _path;
    if (writer == null || path == null) return;
    _writer = null;
    _path = null;
    await writer.close();
    final endMs = _chunkStartMs + _chunkSamples * 1000 ~/ sampleRate;
    final info = ChunkInfo(
      seq: _seq,
      path: path,
      startMs: _chunkStartMs,
      endMs: endMs,
      bytes: 44 + _chunkSamples * 2,
    );
    _seq += 1;
    _chunkStartMs = endMs;
    _chunkSamples = 0;
    _quietSamples = 0;
    onChunk(info);
  }

  /// Closes the chunk in progress (if any) and flushes everything to disk.
  Future<void> close() {
    _queue = _queue.then((_) => _closeChunk());
    return _queue;
  }

  static double _rms(Uint8List pcm16, int samples) {
    final data = ByteData.sublistView(pcm16);
    var sum = 0.0;
    for (var i = 0; i < samples; i++) {
      final v = data.getInt16(i * 2, Endian.little) / 32768.0;
      sum += v * v;
    }
    return sqrt(sum / samples);
  }
}
