import 'dart:io';
import 'dart:typed_data';

/// Incremental PCM16 WAV writer.
///
/// Writes a placeholder header on [open], appends raw PCM16 chunks with [add]
/// and patches the RIFF/data sizes on [close]. Chunks are buffered and flushed
/// in large blocks to keep flash-friendly write patterns during long
/// recordings.
class WavFileWriter {
  WavFileWriter._(this._raf, this.sampleRate, this.channels);

  static const int _headerSize = 44;
  static const int _flushThresholdBytes = 256 * 1024;

  final RandomAccessFile _raf;
  final int sampleRate;
  final int channels;

  final BytesBuilder _buffer = BytesBuilder(copy: true);
  int _dataBytes = 0;
  bool _closed = false;

  /// Serializes RandomAccessFile operations: callers may not await [add],
  /// so writes are chained instead of issued concurrently.
  Future<void> _queue = Future.value();

  static Future<WavFileWriter> open(
    File file, {
    required int sampleRate,
    required int channels,
  }) async {
    final raf = await file.open(mode: FileMode.write);
    final writer = WavFileWriter._(raf, sampleRate, channels);
    await raf.writeFrom(writer._buildHeader(0));
    return writer;
  }

  int get dataBytes => _dataBytes;

  Duration get duration => Duration(
    milliseconds: (_dataBytes * 1000) ~/ (sampleRate * channels * 2),
  );

  Future<void> add(Uint8List pcm16) {
    if (_closed) return Future.value();
    _buffer.add(pcm16);
    _dataBytes += pcm16.length;
    if (_buffer.length >= _flushThresholdBytes) {
      _flush();
    }
    return _queue;
  }

  void _flush() {
    if (_buffer.isEmpty) return;
    final bytes = _buffer.takeBytes();
    _queue = _queue.then((_) => _raf.writeFrom(bytes));
  }

  Future<void> close() async {
    if (_closed) return;
    _closed = true;
    _flush();
    await _queue;
    await _raf.setPosition(0);
    await _raf.writeFrom(_buildHeader(_dataBytes));
    await _raf.close();
  }

  Uint8List _buildHeader(int dataBytes) {
    final byteRate = sampleRate * channels * 2;
    final header = ByteData(_headerSize);
    void writeAscii(int offset, String s) {
      for (var i = 0; i < s.length; i++) {
        header.setUint8(offset + i, s.codeUnitAt(i));
      }
    }

    writeAscii(0, 'RIFF');
    header.setUint32(4, 36 + dataBytes, Endian.little);
    writeAscii(8, 'WAVE');
    writeAscii(12, 'fmt ');
    header.setUint32(16, 16, Endian.little);
    header.setUint16(20, 1, Endian.little); // PCM
    header.setUint16(22, channels, Endian.little);
    header.setUint32(24, sampleRate, Endian.little);
    header.setUint32(28, byteRate, Endian.little);
    header.setUint16(32, channels * 2, Endian.little);
    header.setUint16(34, 16, Endian.little);
    writeAscii(36, 'data');
    header.setUint32(40, dataBytes, Endian.little);
    return header.buffer.asUint8List();
  }
}

/// Parsed metadata of a PCM16 WAV file.
class WavInfo {
  const WavInfo({
    required this.sampleRate,
    required this.channels,
    required this.dataOffset,
    required this.dataBytes,
  });

  final int sampleRate;
  final int channels;
  final int dataOffset;
  final int dataBytes;

  int get frameCount => dataBytes ~/ (channels * 2);

  Duration get duration =>
      Duration(milliseconds: (frameCount * 1000) ~/ sampleRate);
}

/// Reads WAV metadata by walking RIFF chunks; only PCM16 is supported.
Future<WavInfo> readWavInfo(String path) async {
  final raf = await File(path).open();
  try {
    final head = await raf.read(12);
    if (head.length < 12 ||
        String.fromCharCodes(head, 0, 4) != 'RIFF' ||
        String.fromCharCodes(head, 8, 12) != 'WAVE') {
      throw const FormatException('Not a RIFF/WAVE file');
    }
    int? sampleRate;
    int? channels;
    var offset = 12;
    final fileLength = await raf.length();
    while (offset + 8 <= fileLength) {
      await raf.setPosition(offset);
      final chunkHead = await raf.read(8);
      final id = String.fromCharCodes(chunkHead, 0, 4);
      final size = ByteData.sublistView(
        chunkHead,
        4,
        8,
      ).getUint32(0, Endian.little);
      if (id == 'fmt ') {
        final fmt = await raf.read(16);
        final bd = ByteData.sublistView(fmt);
        final format = bd.getUint16(0, Endian.little);
        final bits = bd.getUint16(14, Endian.little);
        if (format != 1 || bits != 16) {
          throw const FormatException('Only PCM16 WAV is supported');
        }
        channels = bd.getUint16(2, Endian.little);
        sampleRate = bd.getUint32(4, Endian.little);
      } else if (id == 'data') {
        if (sampleRate == null || channels == null) {
          throw const FormatException('data chunk before fmt chunk');
        }
        return WavInfo(
          sampleRate: sampleRate,
          channels: channels,
          dataOffset: offset + 8,
          dataBytes: size,
        );
      }
      offset += 8 + size + (size & 1);
    }
    throw const FormatException('No data chunk found');
  } finally {
    await raf.close();
  }
}

/// Extracts one channel of a PCM16 WAV into a new mono PCM16 WAV.
///
/// Streams through the source so arbitrarily long recordings never need to be
/// resident in memory.
Future<void> extractChannelToWav({
  required String sourcePath,
  required String targetPath,
  required int channel,
}) async {
  final info = await readWavInfo(sourcePath);
  if (channel < 0 || channel >= info.channels) {
    throw RangeError.range(channel, 0, info.channels - 1, 'channel');
  }
  final source = await File(sourcePath).open();
  final writer = await WavFileWriter.open(
    File(targetPath),
    sampleRate: info.sampleRate,
    channels: 1,
  );
  try {
    await source.setPosition(info.dataOffset);
    final frameBytes = info.channels * 2;
    const framesPerChunk = 64 * 1024;
    var remaining = info.dataBytes;
    while (remaining > 0) {
      final toRead = remaining < framesPerChunk * frameBytes
          ? remaining
          : framesPerChunk * frameBytes;
      final chunk = await source.read(toRead);
      if (chunk.isEmpty) break;
      remaining -= chunk.length;
      final frames = chunk.length ~/ frameBytes;
      final mono = Uint8List(frames * 2);
      for (var f = 0; f < frames; f++) {
        final src = f * frameBytes + channel * 2;
        mono[f * 2] = chunk[src];
        mono[f * 2 + 1] = chunk[src + 1];
      }
      await writer.add(mono);
    }
  } finally {
    await writer.close();
    await source.close();
  }
}

/// Writes a copy of a PCM16 WAV with the inclusive time range
/// `[removeStart, removeEnd)` removed. The operation is streamed so long
/// meeting recordings do not need to fit in memory.
Future<WavInfo> removeWavSegment({
  required String sourcePath,
  required String targetPath,
  required Duration removeStart,
  required Duration removeEnd,
}) async {
  final info = await readWavInfo(sourcePath);
  final startFrame =
      (removeStart.inMicroseconds * info.sampleRate) ~/
      Duration.microsecondsPerSecond;
  final endFrame =
      (removeEnd.inMicroseconds * info.sampleRate) ~/
      Duration.microsecondsPerSecond;
  final firstFrame = startFrame.clamp(0, info.frameCount);
  final lastFrame = endFrame.clamp(firstFrame, info.frameCount);
  final frameBytes = info.channels * 2;
  final source = await File(sourcePath).open();
  final writer = await WavFileWriter.open(
    File(targetPath),
    sampleRate: info.sampleRate,
    channels: info.channels,
  );

  Future<void> copyFrames(int from, int to) async {
    if (to <= from) return;
    await source.setPosition(info.dataOffset + from * frameBytes);
    var remaining = (to - from) * frameBytes;
    const chunkBytes = 256 * 1024;
    while (remaining > 0) {
      final chunk = await source.read(
        remaining < chunkBytes ? remaining : chunkBytes,
      );
      if (chunk.isEmpty) break;
      remaining -= chunk.length;
      await writer.add(chunk);
    }
  }

  try {
    await copyFrames(0, firstFrame);
    await copyFrames(lastFrame, info.frameCount);
  } finally {
    await writer.close();
    await source.close();
  }
  return WavInfo(
    sampleRate: info.sampleRate,
    channels: info.channels,
    dataOffset: 44,
    dataBytes: writer.dataBytes,
  );
}

/// A chunk of mono Float32 samples produced by [readChannelSamples].
class ChannelChunk {
  const ChannelChunk({required this.samples, required this.sourceFrames});

  /// Samples at the requested target sample rate, in [-1, 1].
  final Float32List samples;

  /// Number of source frames consumed to produce [samples].
  final int sourceFrames;
}

/// Streaming linear resampler that preserves continuity across chunks.
class LinearResampler {
  LinearResampler({required this.srcRate, required this.dstRate})
    : _step = srcRate / dstRate;

  final int srcRate;
  final int dstRate;
  final double _step;

  double _nextPos = 0;
  int _base = 0;
  double _prev = 0;
  bool _hasPrev = false;

  Float32List process(Float32List input) {
    if (srcRate == dstRate) return input;
    if (input.isEmpty) return Float32List(0);
    final lastIndex = _base + input.length - 1;
    final out = <double>[];
    while (_nextPos <= lastIndex) {
      final idx = _nextPos.floor();
      final frac = _nextPos - idx;
      final double s0;
      if (idx < _base) {
        s0 = _hasPrev ? _prev : input[0];
      } else {
        s0 = input[idx - _base];
      }
      final s1 = idx + 1 <= lastIndex ? input[idx + 1 - _base] : s0;
      out.add(s0 + (s1 - s0) * frac);
      _nextPos += _step;
    }
    _prev = input.last;
    _hasPrev = true;
    _base += input.length;
    return Float32List.fromList(out);
  }
}

/// Streams one channel of a PCM16 WAV as Float32 chunks, optionally
/// resampled to [targetSampleRate], without loading the file into memory.
Stream<ChannelChunk> readChannelSamples(
  String path, {
  required WavInfo info,
  required int channel,
  required int targetSampleRate,
  int chunkFrames = 64 * 1024,
}) async* {
  if (channel < 0 || channel >= info.channels) {
    throw RangeError.range(channel, 0, info.channels - 1, 'channel');
  }
  final resampler = LinearResampler(
    srcRate: info.sampleRate,
    dstRate: targetSampleRate,
  );
  final source = await File(path).open();
  try {
    await source.setPosition(info.dataOffset);
    final frameBytes = info.channels * 2;
    var remaining = info.dataBytes;
    while (remaining > 0) {
      final toRead = remaining < chunkFrames * frameBytes
          ? remaining
          : chunkFrames * frameBytes;
      final chunk = await source.read(toRead);
      if (chunk.isEmpty) break;
      remaining -= chunk.length;
      final frames = chunk.length ~/ frameBytes;
      final bd = ByteData.sublistView(chunk);
      final mono = Float32List(frames);
      for (var f = 0; f < frames; f++) {
        mono[f] =
            bd.getInt16((f * info.channels + channel) * 2, Endian.little) /
            32768.0;
      }
      yield ChannelChunk(
        samples: resampler.process(mono),
        sourceFrames: frames,
      );
    }
  } finally {
    await source.close();
  }
}

/// Converts interleaved PCM16 bytes of [channels] channels into per-channel
/// Float32 samples in [-1, 1].
List<Float32List> pcm16ToChannelFloats(Uint8List pcm, int channels) {
  final frames = pcm.length ~/ (channels * 2);
  final bd = ByteData.sublistView(pcm);
  final out = List<Float32List>.generate(
    channels,
    (_) => Float32List(frames),
    growable: false,
  );
  for (var f = 0; f < frames; f++) {
    for (var c = 0; c < channels; c++) {
      out[c][f] = bd.getInt16((f * channels + c) * 2, Endian.little) / 32768.0;
    }
  }
  return out;
}

/// Rewrites the RIFF/data sizes of a PCM16 WAV whose writer never got to
/// close it (crash, kill). The data size becomes whatever is on disk after
/// the 44-byte header, rounded down to whole frames. Returns the audio
/// duration, or null when the file is too short to hold a header.
Future<Duration?> repairWavHeader(String path) async {
  final file = File(path);
  if (!await file.exists()) return null;
  final raf = await file.open(mode: FileMode.append);
  try {
    final length = await raf.length();
    if (length < 44) return null;
    await raf.setPosition(22);
    final fmt = await raf.read(14);
    final view = ByteData.sublistView(Uint8List.fromList(fmt));
    final channels = view.getUint16(0, Endian.little);
    final sampleRate = view.getUint32(2, Endian.little);
    if (channels < 1 || sampleRate < 1) return null;
    final frameBytes = channels * 2;
    final dataBytes = ((length - 44) ~/ frameBytes) * frameBytes;
    final sizes = ByteData(4)..setUint32(0, 36 + dataBytes, Endian.little);
    await raf.setPosition(4);
    await raf.writeFrom(sizes.buffer.asUint8List());
    final data = ByteData(4)..setUint32(0, dataBytes, Endian.little);
    await raf.setPosition(40);
    await raf.writeFrom(data.buffer.asUint8List());
    if (length != 44 + dataBytes) await raf.truncate(44 + dataBytes);
    return Duration(milliseconds: dataBytes ~/ frameBytes * 1000 ~/ sampleRate);
  } finally {
    await raf.close();
  }
}
