import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/audio/wav.dart';

Uint8List interleavedPcm16(List<List<int>> channels) {
  final frames = channels[0].length;
  final data = ByteData(frames * channels.length * 2);
  for (var f = 0; f < frames; f++) {
    for (var c = 0; c < channels.length; c++) {
      data.setInt16(
        (f * channels.length + c) * 2,
        channels[c][f],
        Endian.little,
      );
    }
  }
  return data.buffer.asUint8List();
}

void main() {
  late Directory tmp;

  setUp(() async {
    tmp = await Directory.systemTemp.createTemp('wav_test');
  });

  tearDown(() async {
    await tmp.delete(recursive: true);
  });

  group('WavFileWriter / readWavInfo', () {
    test('writes a valid PCM16 stereo header and data length', () async {
      final file = File('${tmp.path}/out.wav');
      final writer = await WavFileWriter.open(
        file,
        sampleRate: 16000,
        channels: 2,
      );
      final pcm = interleavedPcm16([
        List.generate(1600, (i) => i % 100),
        List.generate(1600, (i) => -(i % 100)),
      ]);
      await writer.add(pcm);
      await writer.close();

      final info = await readWavInfo(file.path);
      expect(info.sampleRate, 16000);
      expect(info.channels, 2);
      expect(info.dataBytes, pcm.length);
      expect(info.frameCount, 1600);
      expect(info.duration, const Duration(milliseconds: 100));
    });

    test('unawaited add calls keep byte order intact', () async {
      final file = File('${tmp.path}/order.wav');
      final writer = await WavFileWriter.open(
        file,
        sampleRate: 16000,
        channels: 1,
      );
      // Chunks large enough to trigger multiple internal flushes.
      final chunks = List.generate(8, (c) {
        final chunk = Uint8List(300 * 1024);
        for (var i = 0; i < chunk.length; i++) {
          chunk[i] = (c * 31 + i) % 251;
        }
        return chunk;
      });
      for (final chunk in chunks) {
        // ignore: unawaited_futures
        writer.add(chunk);
      }
      await writer.close();

      final bytes = await file.readAsBytes();
      final expected = BytesBuilder();
      for (final chunk in chunks) {
        expected.add(chunk);
      }
      expect(bytes.sublist(44), expected.takeBytes());
    });
  });

  group('extractChannelToWav', () {
    test('extracts each channel to a mono wav', () async {
      final source = File('${tmp.path}/stereo.wav');
      final writer = await WavFileWriter.open(
        source,
        sampleRate: 16000,
        channels: 2,
      );
      final left = List.generate(500, (i) => i - 250);
      final right = List.generate(500, (i) => 250 - i);
      await writer.add(interleavedPcm16([left, right]));
      await writer.close();

      for (final (channel, expected) in [(0, left), (1, right)]) {
        final target = File('${tmp.path}/ch$channel.wav');
        await extractChannelToWav(
          sourcePath: source.path,
          targetPath: target.path,
          channel: channel,
        );
        final info = await readWavInfo(target.path);
        expect(info.channels, 1);
        expect(info.frameCount, 500);
        final bytes = await target.readAsBytes();
        final bd = ByteData.sublistView(bytes, info.dataOffset);
        for (var f = 0; f < 500; f++) {
          expect(bd.getInt16(f * 2, Endian.little), expected[f]);
        }
      }
    });

    test('rejects out-of-range channel', () async {
      final source = File('${tmp.path}/mono.wav');
      final writer = await WavFileWriter.open(
        source,
        sampleRate: 16000,
        channels: 1,
      );
      await writer.add(interleavedPcm16([List.filled(10, 0)]));
      await writer.close();
      expect(
        () => extractChannelToWav(
          sourcePath: source.path,
          targetPath: '${tmp.path}/bad.wav',
          channel: 1,
        ),
        throwsRangeError,
      );
    });
  });

  group('LinearResampler', () {
    test('passthrough when rates match', () {
      final r = LinearResampler(srcRate: 16000, dstRate: 16000);
      final input = Float32List.fromList([0.1, 0.2, 0.3]);
      expect(r.process(input), same(input));
    });

    test('produces expected output length across chunks', () {
      final r = LinearResampler(srcRate: 44100, dstRate: 16000);
      var totalOut = 0;
      const chunkSize = 4410;
      const chunks = 10;
      for (var i = 0; i < chunks; i++) {
        totalOut += r.process(Float32List(chunkSize)).length;
      }
      final expected = (chunkSize * chunks * 16000 / 44100).round();
      expect((totalOut - expected).abs() <= 2, isTrue);
    });

    test('preserves a constant signal', () {
      final r = LinearResampler(srcRate: 48000, dstRate: 16000);
      final out = r.process(Float32List.fromList(List.filled(480, 0.5)));
      for (final sample in out) {
        expect((sample - 0.5).abs() < 1e-6, isTrue);
      }
    });

    test('tracks a sine wave within tolerance', () {
      final r = LinearResampler(srcRate: 32000, dstRate: 16000);
      final input = Float32List.fromList([
        for (var i = 0; i < 3200; i++) math.sin(2 * math.pi * 100 * i / 32000),
      ]);
      final out = r.process(input);
      for (var i = 0; i < out.length; i++) {
        final expected = math.sin(2 * math.pi * 100 * i / 16000);
        expect((out[i] - expected).abs() < 0.01, isTrue);
      }
    });
  });

  group('readChannelSamples', () {
    test('streams normalized floats for the requested channel', () async {
      final source = File('${tmp.path}/read.wav');
      final writer = await WavFileWriter.open(
        source,
        sampleRate: 16000,
        channels: 2,
      );
      final left = List.generate(1000, (i) => (i % 200) * 100 - 10000);
      final right = List.filled(1000, 16384);
      await writer.add(interleavedPcm16([left, right]));
      await writer.close();

      final info = await readWavInfo(source.path);
      final samples = <double>[];
      var sourceFrames = 0;
      await for (final chunk in readChannelSamples(
        source.path,
        info: info,
        channel: 1,
        targetSampleRate: 16000,
        chunkFrames: 128,
      )) {
        samples.addAll(chunk.samples);
        sourceFrames += chunk.sourceFrames;
      }
      expect(sourceFrames, 1000);
      expect(samples.length, 1000);
      for (final sample in samples) {
        expect((sample - 0.5).abs() < 1e-4, isTrue);
      }
    });
  });

  group('pcm16ToChannelFloats', () {
    test('splits interleaved channels', () {
      final pcm = interleavedPcm16([
        [32767, 0, -32768],
        [-16384, 16384, 0],
      ]);
      final out = pcm16ToChannelFloats(pcm, 2);
      expect(out.length, 2);
      expect(out[0][0], closeTo(1.0, 1e-4));
      expect(out[0][2], closeTo(-1.0, 1e-4));
      expect(out[1][0], closeTo(-0.5, 1e-4));
      expect(out[1][1], closeTo(0.5, 1e-4));
    });
  });
}
