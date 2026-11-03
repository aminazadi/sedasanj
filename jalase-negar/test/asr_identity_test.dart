import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/asr/asr_identity.dart';
import 'package:jalase_negar/core/asr/transcriber.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';

void main() {
  group('buildAsrIdentity', () {
    test('names the model, the real audio preparation and the segmenter', () {
      expect(
        buildAsrIdentity(
          modelId: 'shenava-koochik-v1-5-rnnt',
          segmenter: AsrSegmenter.silero,
        ),
        'shenava-koochik-v1-5-rnnt|device-quiet-gain-v1|segmenter:silero-vad',
      );
    });

    test('records the optional denoiser', () {
      expect(
        buildAsrIdentity(
          modelId: 'm',
          segmenter: AsrSegmenter.silero,
          denoiser: true,
        ),
        'm|device-quiet-gain-v1+gtcrn|segmenter:silero-vad',
      );
    });

    test('identifies transcripts captured live', () {
      final live = buildAsrIdentity(
        modelId: 'm',
        segmenter: AsrSegmenter.silero,
        live: true,
      );
      expect(live, 'm|device-quiet-gain-v1|segmenter:silero-vad-live');
    });

    test('server-parity mode uses the server preparation identity', () {
      expect(
        buildAsrIdentity(modelId: 'm', segmenter: AsrSegmenter.serverEnergy),
        'm|preprocess:none|segmenter:server-energy-vad',
      );
    });
  });

  group('Segment', () {
    test(
      'rows written before the contract fields default to the device VAD',
      () {
        final segment = Segment.fromRow({
          'channel': 0,
          't_start_ms': 100,
          't_end_ms': 900,
          'text': 'سلام',
        });
        expect(segment.timestampSource, TimestampSource.sileroVad);
        expect(segment.source, 'device');
        expect(segment.confidence, isNull);
        expect(segment.speaker, isNull);
      },
    );

    test('reads the contract fields', () {
      final segment = Segment.fromRow({
        'channel': 1,
        't_start_ms': 0,
        't_end_ms': 10,
        'text': 'x',
        'confidence': 1,
        'speaker': '2',
        'timestamp_source': 'vad_window',
        'source': 'server',
      });
      expect(segment.confidence, 1.0);
      expect(segment.speaker, '2');
      expect(segment.timestampSource, 'vad_window');
      expect(segment.source, 'server');
    });
  });

  test('Meeting round-trips the ASR identity', () {
    final row = Meeting(
      id: 'a',
      title: 't',
      createdAt: DateTime.fromMillisecondsSinceEpoch(1000),
      duration: const Duration(seconds: 5),
      audioPath: '/x.wav',
      sampleRate: 16000,
      channels: 1,
      status: MeetingStatus.transcribed,
      asrIdentity: 'm|p|s',
    ).toRow();
    expect(row['asr_identity'], 'm|p|s');
    expect(Meeting.fromRow(row).asrIdentity, 'm|p|s');
  });
}
