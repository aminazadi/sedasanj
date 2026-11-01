import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/audio/chunk_writer.dart';
import 'package:jalase_negar/core/audio/wav.dart';

Uint8List pcm(int ms, {required bool loud}) {
  final samples = 16000 * ms ~/ 1000;
  final data = ByteData(samples * 2);
  for (var i = 0; i < samples; i++) {
    data.setInt16(i * 2, loud ? (i.isEven ? 8000 : -8000) : 0, Endian.little);
  }
  return data.buffer.asUint8List();
}

void main() {
  late Directory dir;
  setUp(() => dir = Directory.systemTemp.createTempSync('chunks'));
  tearDown(() => dir.deleteSync(recursive: true));

  test('cuts at the first silence after the minimum length', () async {
    final chunks = <ChunkInfo>[];
    final writer = ChunkWriter(
      dir: dir,
      onChunk: chunks.add,
      minCutMs: 2000,
      maxMs: 6000,
      silenceMs: 300,
    );
    for (var i = 0; i < 25; i++) {
      await writer.add(pcm(100, loud: true));
    }
    expect(chunks, isEmpty);
    for (var i = 0; i < 3; i++) {
      await writer.add(pcm(100, loud: false));
    }
    expect(chunks.length, 1);
    expect(chunks.first.startMs, 0);
    expect(chunks.first.endMs, 2800);
    await writer.add(pcm(500, loud: true));
    await writer.close();
    expect(chunks.length, 2);
    expect(chunks[1].startMs, 2800);
    expect(chunks[1].endMs, 3300);
    final info = await readWavInfo(chunks.first.path);
    expect(info.channels, 1);
    expect(info.sampleRate, 16000);
    expect(info.duration.inMilliseconds, 2800);
  });

  test('forces a cut when the audio never goes quiet', () async {
    final chunks = <ChunkInfo>[];
    final writer = ChunkWriter(
      dir: dir,
      onChunk: chunks.add,
      minCutMs: 1000,
      maxMs: 2000,
    );
    for (var i = 0; i < 45; i++) {
      await writer.add(pcm(100, loud: true));
    }
    await writer.close();
    expect(chunks.map((c) => c.endMs - c.startMs), [2000, 2000, 500]);
    expect(chunks.map((c) => c.seq), [0, 1, 2]);
    expect(writer.duration.inMilliseconds, 4500);
  });

  test('repairWavHeader recovers an unclosed WAV', () async {
    final file = File('${dir.path}/orphan.wav');
    final header = ByteData(44);
    for (final entry in {
      0: 'RIFF',
      8: 'WAVE',
      12: 'fmt ',
      36: 'data',
    }.entries) {
      for (var i = 0; i < 4; i++) {
        header.setUint8(entry.key + i, entry.value.codeUnitAt(i));
      }
    }
    header.setUint32(16, 16, Endian.little);
    header.setUint16(20, 1, Endian.little);
    header.setUint16(22, 1, Endian.little);
    header.setUint32(24, 16000, Endian.little);
    header.setUint32(28, 32000, Endian.little);
    header.setUint16(32, 2, Endian.little);
    header.setUint16(34, 16, Endian.little);
    await file.writeAsBytes([
      ...header.buffer.asUint8List(),
      ...pcm(1000, loud: true),
      7, // a torn half-sample at the end
    ]);
    final duration = await repairWavHeader(file.path);
    expect(duration!.inMilliseconds, 1000);
    final info = await readWavInfo(file.path);
    expect(info.dataBytes, 32000);
  });
}
