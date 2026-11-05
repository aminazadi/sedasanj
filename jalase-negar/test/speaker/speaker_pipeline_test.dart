import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/asr/asr_common.dart';
import 'package:jalase_negar/core/asr/consolidate.dart';
import 'package:jalase_negar/core/asr/live_asr_engine.dart';
import 'package:jalase_negar/core/asr/live_pipeline.dart';
import 'package:jalase_negar/core/speaker/speaker_labeler.dart';
import 'package:jalase_negar/core/speaker/speaker_matcher.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';
import 'package:jalase_negar/features/meetings/data/transcript_edit.dart';
import 'package:jalase_negar/features/people/data/speaker_payload.dart';

class OneSpanVad implements LiveVad {
  OneSpanVad(this.length);
  final int length;
  int accepted = 0;
  bool emitted = false;

  @override
  void accept(Float32List samples) => accepted += samples.length;

  @override
  bool get speechDetected => !emitted;

  @override
  VadSpan? pop() {
    if (emitted || accepted < length) return null;
    emitted = true;
    return VadSpan(
      startSample: 0,
      samples: Float32List(length)..fillRange(0, length, 0.1),
    );
  }

  @override
  void flush() {}

  @override
  void dispose() {}
}

class CountingDecoder implements LiveDecoder {
  final List<int> lengths = [];

  @override
  String decode(Float32List samples) {
    lengths.add(samples.length);
    return 'متن ${lengths.length}';
  }
}

class ScriptedLabeler implements UtteranceLabeler {
  ScriptedLabeler(this.parts);
  final List<LabeledPart> parts;
  int calls = 0;

  @override
  List<LabeledPart> label(Float32List speech, {required int startMs}) {
    calls++;
    return parts;
  }
}

Uint8List pcm(double seconds) {
  final n = (seconds * kAsrSampleRate).round();
  final d = ByteData(n * 2);
  for (var i = 0; i < n; i++) {
    d.setInt16(i * 2, 1000, Endian.little);
  }
  return d.buffer.asUint8List();
}

const ali = SpeakerIdentity(name: 'علی', personId: 'ali', confidence: 90);
const sara = SpeakerIdentity(name: 'سارا', personId: 'sara', confidence: 85);

List<LiveUtterance> run(UtteranceLabeler? labeler, CountingDecoder decoder) {
  final pipeline = LivePipeline(
    vadFactory: () => OneSpanVad(8 * kAsrSampleRate),
    decoder: decoder,
    labeler: labeler,
  );
  return [...pipeline.feed(pcm(8))].whereType<LiveUtterance>().toList();
}

void main() {
  group('LivePipeline with speaker identification', () {
    test('without a labeler nothing changes: one unnamed line', () {
      final decoder = CountingDecoder();
      final out = run(null, decoder);
      expect(out, hasLength(1));
      expect(out.single.speaker, isNull);
      expect(out.single.overlap, isFalse);
    });

    test('one speaker: one decode of the whole utterance, with the name', () {
      final decoder = CountingDecoder();
      final out = run(
        ScriptedLabeler([
          const LabeledPart(
            startMs: 0,
            endMs: 8000,
            speakers: [ali],
            confidence: 90,
          ),
        ]),
        decoder,
      );
      expect(decoder.lengths, hasLength(1));
      expect(out.single.speaker!.name, 'علی');
      expect(out.single.speakerConfidence, 90);
    });

    test('a speaker change gives one line per speaker, in time order', () {
      final decoder = CountingDecoder();
      final out = run(
        ScriptedLabeler([
          const LabeledPart(
            startMs: 0,
            endMs: 4000,
            speakers: [ali],
            confidence: 90,
          ),
          const LabeledPart(
            startMs: 4000,
            endMs: 8000,
            speakers: [sara],
            confidence: 85,
          ),
        ]),
        decoder,
      );
      expect(out.map((u) => u.speaker!.name), ['علی', 'سارا']);
      expect(out.map((u) => (u.startMs, u.endMs)), [(0, 4000), (4000, 8000)]);
      expect(
        decoder.lengths,
        hasLength(2),
        reason: 'each stretch decoded alone',
      );
      expect(decoder.lengths.first, lessThan(8 * kAsrSampleRate));
    });

    test('overlapping speech is one flagged line with both names', () {
      final decoder = CountingDecoder();
      final out = run(
        ScriptedLabeler([
          const LabeledPart(
            startMs: 0,
            endMs: 3000,
            speakers: [ali],
            confidence: 90,
          ),
          const LabeledPart(
            startMs: 3000,
            endMs: 5000,
            speakers: [ali, sara],
            overlap: true,
            confidence: 40,
          ),
          const LabeledPart(
            startMs: 5000,
            endMs: 8000,
            speakers: [sara],
            confidence: 85,
          ),
        ]),
        decoder,
      );
      final mixed = out[1];
      expect(mixed.overlap, isTrue);
      expect(mixed.speaker!.name, 'علی');
      expect(mixed.speaker2!.name, 'سارا');
      expect(mixed.speakerConfidence, 40);
    });

    test('a labeler that throws never loses the text', () {
      final out = run(_Throwing(), CountingDecoder());
      expect(out, hasLength(1));
      expect(out.single.speaker, isNull);
    });
  });

  group('consolidation keeps speakers apart', () {
    AsrTurn turn(
      int from,
      int to,
      String text,
      String? speaker, {
      bool overlap = false,
    }) => AsrTurn(
      channel: 0,
      startMs: from,
      endMs: to,
      text: text,
      speaker: speaker,
      speakerPersonId: speaker,
      overlap: overlap,
    );

    test('same speaker close in time still merges', () {
      final turns = consolidateSegments([
        turn(0, 1000, 'سلام', 'ali'),
        turn(1500, 2500, 'خوبی', 'ali'),
      ]);
      expect(turns, hasLength(1));
      expect(turns.single.speaker, 'ali');
    });

    test('a different speaker never merges, however close', () {
      final turns = consolidateSegments([
        turn(0, 1000, 'سلام', 'ali'),
        turn(1100, 2500, 'سلام علی', 'sara'),
      ]);
      expect(turns.map((t) => t.speaker), ['ali', 'sara']);
    });

    test('an overlapping line stays on its own', () {
      final turns = consolidateSegments([
        turn(0, 1000, 'الف', 'ali'),
        turn(1000, 2000, 'ب', 'ali', overlap: true),
        turn(2000, 3000, 'ج', 'ali'),
      ]);
      expect(turns, hasLength(3));
      expect(turns[1].overlap, isTrue);
    });

    test('unlabelled turns merge exactly as before', () {
      final turns = consolidateSegments([
        turn(0, 1000, 'الف', null),
        turn(1200, 2000, 'ب', null),
      ]);
      expect(turns, hasLength(1));
    });
  });

  group('Segment speaker display', () {
    test('labeledText is `نام: متن`, with both names for overlap', () {
      const one = Segment(
        channel: 0,
        startMs: 0,
        endMs: 1,
        text: 'سلام',
        speaker: 'علی',
      );
      expect(one.labeledText, 'علی: سلام');
      const two = Segment(
        channel: 0,
        startMs: 0,
        endMs: 1,
        text: 'سلام',
        speaker: 'علی',
        speaker2: 'سارا',
        overlap: true,
      );
      expect(two.labeledText, 'علی / سارا: سلام');
      const none = Segment(channel: 0, startMs: 0, endMs: 1, text: 'سلام');
      expect(none.labeledText, 'سلام');
    });

    test('editing a line\'s text keeps its speaker', () {
      const original = [
        Segment(
          channel: 0,
          startMs: 0,
          endMs: 1000,
          text: 'سلام دنیا',
          speaker: 'علی',
          speakerPersonId: 'ali',
          speakerConfidence: 80,
        ),
        Segment(
          channel: 0,
          startMs: 1000,
          endMs: 2000,
          text: 'خداحافظ',
          speaker: 'سارا',
          speakerPersonId: 'sara',
          speakerManual: true,
        ),
      ];
      final edited = applyTranscriptEdit(original, 'سلام دوستان\nخداحافظ');
      expect(edited[0].speaker, 'علی');
      expect(edited[0].speakerPersonId, 'ali');
      expect(edited[0].speakerConfidence, 80);
      expect(edited[1].speakerManual, isTrue);
    });
  });

  group('transcript payload', () {
    const aliId = '11111111-1111-4111-8111-111111111111';
    const saraId = '22222222-2222-4222-8222-222222222222';

    test('numbers speakers in order of appearance and links profiles', () {
      final payload = buildTranscriptPayload(const [
        Segment(
          channel: 0,
          startMs: 0,
          endMs: 1000,
          text: 'الف',
          speaker: 'علی',
          speakerPersonId: aliId,
          speakerConfidence: 88,
        ),
        Segment(
          channel: 0,
          startMs: 1000,
          endMs: 2000,
          text: 'ب',
          speaker: 'ناشناس 1',
        ),
        Segment(
          channel: 0,
          startMs: 2000,
          endMs: 3000,
          text: 'ج',
          speaker: 'علی',
          speakerPersonId: aliId,
        ),
      ]);
      expect(payload.speakers, [
        {'idx': 0, 'label': 'علی', 'profile_client_id': aliId},
        {'idx': 1, 'label': 'ناشناس 1'},
      ]);
      expect(payload.segments.map((s) => s['speaker']), [0, 1, 0]);
      expect(payload.segments.first['speaker_confidence'], 88);
      expect(payload.segments[1].containsKey('speaker_confidence'), isFalse);
    });

    test(
      'an overlapping line is sent once per speaker with the same times',
      () {
        final payload = buildTranscriptPayload(const [
          Segment(
            channel: 0,
            startMs: 3000,
            endMs: 5000,
            text: 'هم‌زمان',
            speaker: 'علی',
            speakerPersonId: aliId,
            speaker2: 'سارا',
            speaker2PersonId: saraId,
            overlap: true,
            speakerConfidence: 40,
          ),
        ]);
        expect(payload.segments, hasLength(2));
        for (final s in payload.segments) {
          expect(s['t_start_ms'], 3000);
          expect(s['t_end_ms'], 5000);
          expect(s['overlap'], isTrue);
          expect(s['speaker_confidence'], 40);
        }
        expect(payload.segments.map((s) => s['speaker']), [0, 1]);
        expect(payload.speakers.map((s) => s['label']), ['علی', 'سارا']);
      },
    );

    test('a transcript without speakers has no speaker fields at all', () {
      final payload = buildTranscriptPayload(const [
        Segment(channel: 0, startMs: 0, endMs: 1000, text: 'الف'),
      ]);
      expect(payload.speakers, isEmpty);
      expect(payload.segments.single.keys.toSet(), {
        't_start_ms',
        't_end_ms',
        'text',
      });
    });

    test('voices beyond the platform limit are sent without a speaker', () {
      final payload = buildTranscriptPayload([
        for (var i = 0; i < 70; i++)
          Segment(
            channel: 0,
            startMs: i * 10,
            endMs: i * 10 + 5,
            text: 't$i',
            speaker: 'ناشناس $i',
          ),
      ]);
      expect(payload.speakers, hasLength(kMaxSpeakerIdx + 1));
      expect(payload.segments.last.containsKey('speaker'), isFalse);
    });

    test('a profile id that is not a UUID is not linked', () {
      final payload = buildTranscriptPayload(const [
        Segment(
          channel: 0,
          startMs: 0,
          endMs: 1,
          text: 'x',
          speaker: 'علی',
          speakerPersonId: 'not-a-uuid',
        ),
      ]);
      expect(payload.speakers.single.containsKey('profile_client_id'), isFalse);
    });
  });
}

class _Throwing implements UtteranceLabeler {
  @override
  List<LabeledPart> label(Float32List speech, {required int startMs}) =>
      throw StateError('boom');
}
