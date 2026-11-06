import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/asr/asr_common.dart';
import 'package:jalase_negar/core/asr/live_asr_engine.dart';
import 'package:jalase_negar/core/asr/live_pipeline.dart';
import 'package:jalase_negar/core/speaker/speaker_labeler.dart';
import 'package:jalase_negar/core/speaker/speaker_matcher.dart';

/// Span the fake VAD hands out once [at] samples have been fed. A span that
/// has not been reached yet is the "speech in progress" that `flush` closes.
class ScriptedSpan {
  ScriptedSpan({required this.at, required this.start, required this.length});

  final int at;
  final int start;
  final int length;
  bool emitted = false;
}

class FakeVad implements LiveVad {
  FakeVad([List<ScriptedSpan> script = const []]) : _script = script;

  final List<ScriptedSpan> _script;
  final List<VadSpan> _ready = [];
  int accepted = 0;
  bool disposed = false;
  bool flushed = false;

  void _emit(ScriptedSpan s) {
    s.emitted = true;
    _ready.add(
      VadSpan(
        startSample: s.start,
        samples: Float32List(s.length)..fillRange(0, s.length, 0.1),
      ),
    );
  }

  @override
  void accept(Float32List samples) {
    accepted += samples.length;
    for (final s in _script) {
      if (!s.emitted && s.at <= accepted) _emit(s);
    }
  }

  @override
  bool get speechDetected =>
      _script.any((s) => !s.emitted && s.start < accepted);

  @override
  VadSpan? pop() => _ready.isEmpty ? null : _ready.removeAt(0);

  @override
  void flush() {
    flushed = true;
    for (final s in _script) {
      if (!s.emitted && s.start < accepted) _emit(s);
    }
  }

  @override
  void dispose() => disposed = true;
}

/// Labels every utterance with the next speaker name in [names].
class FakeLabeler implements UtteranceLabeler {
  FakeLabeler(this.names);

  final List<String> names;

  @override
  List<LabeledPart> label(Float32List speech, {required int startMs}) => [
    LabeledPart(
      startMs: startMs,
      endMs: startMs + speech.length * 1000 ~/ kAsrSampleRate,
      speakers: [SpeakerIdentity(name: names.removeAt(0))],
    ),
  ];
}

class FakeDecoder implements LiveDecoder {
  FakeDecoder(this.texts, {this.clock, this.microsPerCall = 0});

  /// Fake clock the decode "takes" [microsPerCall] on.
  final List<int>? clock;
  final int microsPerCall;

  final List<String> texts;
  final List<int> inputLengths = [];

  @override
  String decode(Float32List samples) {
    inputLengths.add(samples.length);
    if (clock != null) clock![0] += microsPerCall;
    return texts.isEmpty ? '' : texts.removeAt(0);
  }
}

Uint8List pcmSeconds(double seconds, {int value = 1000}) {
  final samples = (seconds * kAsrSampleRate).round();
  final data = ByteData(samples * 2);
  for (var i = 0; i < samples; i++) {
    data.setInt16(i * 2, value, Endian.little);
  }
  return data.buffer.asUint8List();
}

LivePipeline pipelineWith(
  List<FakeVad> vads,
  FakeDecoder decoder, {
  int maxBacklogMs = 60000,
}) {
  var index = 0;
  return LivePipeline(
    vadFactory: () => vads[index++],
    decoder: decoder,
    maxBacklogMs: maxBacklogMs,
  );
}

void main() {
  group('SampleHistory', () {
    test('returns the samples in range after the ring wrapped', () {
      final history = SampleHistory(10);
      history.append(
        Float32List.fromList([for (var i = 0; i < 7; i++) i + 0.0]),
      );
      history.append(
        Float32List.fromList([for (var i = 7; i < 15; i++) i + 0.0]),
      );
      expect(history.endSample, 15);
      expect(history.startSample, 5);
      final slice = history.slice(8, 13);
      expect(slice.start, 8);
      expect(slice.samples, [8.0, 9.0, 10.0, 11.0, 12.0]);
    });

    test(
      'clips a request that reaches before the oldest or past the newest',
      () {
        final history = SampleHistory(4)
          ..append(Float32List.fromList([1, 2, 3, 4, 5, 6]));
        final slice = history.slice(0, 100);
        expect(slice.start, 2);
        expect(slice.samples, [3.0, 4.0, 5.0, 6.0]);
        expect(history.slice(50, 60).samples, isEmpty);
      },
    );

    test('keeps only the tail of a chunk larger than the ring', () {
      final history = SampleHistory(3)
        ..append(Float32List.fromList([1, 2, 3, 4, 5]));
      expect(history.slice(0, 5).samples, [3.0, 4.0, 5.0]);
      expect(history.startSample, 2);
    });
  });

  group('LivePipeline', () {
    test('times an utterance on the recording timeline', () {
      final decoder = FakeDecoder(['سلام']);
      final pipeline = pipelineWith([
        FakeVad([ScriptedSpan(at: 48000, start: 16000, length: 16000)]),
      ], decoder);
      final events = [
        ...pipeline.feed(pcmSeconds(2)),
        ...pipeline.feed(pcmSeconds(1)),
      ];
      expect(events, hasLength(1));
      final utterance = events.single as LiveUtterance;
      expect(utterance.text, 'سلام');
      expect(utterance.startMs, 1000);
      expect(utterance.endMs, 2000);
      expect(pipeline.fedSamples, 48000);
    });

    test('adds look-around context from the history', () {
      final decoder = FakeDecoder(['x']);
      final pipeline = pipelineWith([
        FakeVad([ScriptedSpan(at: 64000, start: 24000, length: 8000)]),
      ], decoder);
      pipeline.feed(pcmSeconds(4));
      expect(
        decoder.inputLengths.single,
        kAsrPreRollSamples + 8000 + kAsrPostRollSamples,
      );
    });

    test('has no post-roll when the span ends the audio (flush)', () {
      final decoder = FakeDecoder(['x']);
      final vad = FakeVad([
        ScriptedSpan(at: 1 << 30, start: 16000, length: 16000),
      ]);
      final pipeline = pipelineWith([vad, FakeVad()], decoder);
      expect(pipeline.feed(pcmSeconds(2)), isEmpty);
      expect(pipeline.speechDetected, isTrue);
      final events = pipeline.flush();
      expect(vad.flushed, isTrue);
      expect(events.single, isA<LiveUtterance>());
      // The VAD cut covers 1-2 s; only pre-roll exists around it.
      expect(decoder.inputLengths.single, kAsrPreRollSamples + 16000);
    });

    test('keeps the timeline aligned after a flush restarts the VAD', () {
      final decoder = FakeDecoder(['one', 'two']);
      final first = FakeVad();
      final second = FakeVad([
        ScriptedSpan(at: 32000, start: 8000, length: 8000),
      ]);
      final pipeline = pipelineWith([first, second], decoder);
      pipeline.feed(pcmSeconds(3));
      pipeline.flush();
      expect(first.disposed, isTrue);
      final events = pipeline.feed(pcmSeconds(2));
      final utterance = events.single as LiveUtterance;
      // The second VAD counts from 0 but was created at 3 s.
      expect(utterance.startMs, 3500);
      expect(utterance.endMs, 4000);
    });

    test('skips decoding when the engine is too far behind', () {
      final decoder = FakeDecoder(['never']);
      final pipeline = pipelineWith(
        [
          FakeVad([ScriptedSpan(at: 16000, start: 0, length: 16000)]),
        ],
        decoder,
        maxBacklogMs: 5000,
      );
      final events = pipeline.feed(pcmSeconds(1), backlogMs: 6000);
      expect(events.single, isA<LiveSkipped>());
      expect(decoder.inputLengths, isEmpty);
    });

    test('decodes again once the backlog is gone', () {
      final decoder = FakeDecoder(['late']);
      final pipeline = pipelineWith(
        [
          FakeVad([
            ScriptedSpan(at: 16000, start: 0, length: 16000),
            ScriptedSpan(at: 48000, start: 32000, length: 16000),
          ]),
        ],
        decoder,
        maxBacklogMs: 5000,
      );
      expect(
        pipeline.feed(pcmSeconds(1), backlogMs: 9000).single,
        isA<LiveSkipped>(),
      );
      final events = pipeline.feed(pcmSeconds(2), backlogMs: 100);
      expect((events.single as LiveUtterance).text, 'late');
    });

    test('decodes a skipped span later when recover is called', () {
      final decoder = FakeDecoder(['جا مانده']);
      final pipeline = pipelineWith(
        [
          FakeVad([ScriptedSpan(at: 16000, start: 0, length: 16000)]),
        ],
        decoder,
        maxBacklogMs: 5000,
      );
      expect(
        pipeline.feed(pcmSeconds(1), backlogMs: 9000).single,
        isA<LiveSkipped>(),
      );
      expect(pipeline.hasDeferred, isTrue);
      final events = pipeline.recover();
      expect((events.first as LiveUtterance).text, 'جا مانده');
      expect(events.last, isA<LiveRecovered>());
      expect(pipeline.hasDeferred, isFalse);
      expect(pipeline.recover(), isEmpty);
    });

    test('finish recovers deferred speech within the budget', () {
      final decoder = FakeDecoder(['یک', 'دو']);
      final pipeline = pipelineWith(
        [
          FakeVad([
            ScriptedSpan(at: 16000, start: 0, length: 8000),
            ScriptedSpan(at: 48000, start: 32000, length: 8000),
          ]),
        ],
        decoder,
        maxBacklogMs: 5000,
      );
      pipeline.feed(pcmSeconds(1), backlogMs: 9000);
      pipeline.feed(pcmSeconds(2), backlogMs: 9000);
      final events = pipeline.finish(recoverBudgetMs: 1000);
      expect(events.whereType<LiveUtterance>().map((e) => e.text), [
        'یک',
        'دو',
      ]);
      expect(events.whereType<LiveRecovered>(), hasLength(2));
    });

    test('does not keep deferred audio beyond its cap', () {
      final pipeline = LivePipeline(
        vadFactory: () =>
            FakeVad([ScriptedSpan(at: 32000, start: 0, length: 32000)]),
        decoder: FakeDecoder(['x']),
        maxBacklogMs: 5000,
        maxDeferredSeconds: 1,
      );
      expect(
        pipeline.feed(pcmSeconds(2), backlogMs: 9000).single,
        isA<LiveSkipped>(),
      );
      expect(pipeline.hasDeferred, isFalse);
    });

    test('normalizes Persian text and drops empty results', () {
      final decoder = FakeDecoder(['كتاب  يك', '   ']);
      final pipeline = pipelineWith([
        FakeVad([
          ScriptedSpan(at: 16000, start: 0, length: 8000),
          ScriptedSpan(at: 80000, start: 64000, length: 8000),
        ]),
      ], decoder);
      final events = [
        ...pipeline.feed(pcmSeconds(1)),
        ...pipeline.feed(pcmSeconds(4)),
      ];
      expect(events, hasLength(1));
      expect((events.single as LiveUtterance).text, 'کتاب یک');
    });

    test('suppresses an immediate repeat of the same text', () {
      final decoder = FakeDecoder(['امروز جلسه داریم', 'امروز جلسه داریم']);
      final pipeline = pipelineWith([
        FakeVad([
          ScriptedSpan(at: 16000, start: 0, length: 8000),
          ScriptedSpan(at: 32000, start: 16000, length: 8000),
        ]),
      ], decoder);
      final events = [
        ...pipeline.feed(pcmSeconds(1)),
        ...pipeline.feed(pcmSeconds(1)),
      ];
      expect(events.whereType<LiveUtterance>(), hasLength(1));
    });

    test('keeps the same word said by two different speakers', () {
      final decoder = FakeDecoder(['بله بله', 'بله بله']);
      var index = 0;
      final vad = FakeVad([
        ScriptedSpan(at: 16000, start: 0, length: 8000),
        ScriptedSpan(at: 32000, start: 16000, length: 8000),
      ]);
      final pipeline = LivePipeline(
        vadFactory: () => [vad][index++],
        decoder: decoder,
        labeler: FakeLabeler(['علی', 'سارا']),
      );
      final events = [
        ...pipeline.feed(pcmSeconds(1)),
        ...pipeline.feed(pcmSeconds(1)),
      ];
      expect(events.whereType<LiveUtterance>(), hasLength(2));
    });

    test('still drops a repeat by the same speaker', () {
      final decoder = FakeDecoder(['بله بله', 'بله بله']);
      var index = 0;
      final vad = FakeVad([
        ScriptedSpan(at: 16000, start: 0, length: 8000),
        ScriptedSpan(at: 32000, start: 16000, length: 8000),
      ]);
      final pipeline = LivePipeline(
        vadFactory: () => [vad][index++],
        decoder: decoder,
        labeler: FakeLabeler(['علی', 'علی']),
      );
      final events = [
        ...pipeline.feed(pcmSeconds(1)),
        ...pipeline.feed(pcmSeconds(1)),
      ];
      expect(events.whereType<LiveUtterance>(), hasLength(1));
    });

    test('joins an odd trailing byte with the next chunk', () {
      final decoder = FakeDecoder(['x']);
      final pipeline = pipelineWith([
        FakeVad([ScriptedSpan(at: 4, start: 0, length: 4)]),
      ], decoder);
      final bytes = pcmSeconds(0.0003); // 5 samples = 10 bytes
      expect(bytes.length, 10);
      pipeline.feed(Uint8List.sublistView(bytes, 0, 5));
      expect(pipeline.fedSamples, 2);
      pipeline.feed(Uint8List.sublistView(bytes, 5));
      expect(pipeline.fedSamples, 5);
    });

    test('measures how fast decoding runs against the audio', () {
      final decoder = FakeDecoder(['x']);
      final pipeline = pipelineWith([
        FakeVad([ScriptedSpan(at: 16000, start: 0, length: 16000)]),
      ], decoder);
      expect(pipeline.realTimeFactor, 0);
      pipeline.feed(pcmSeconds(1));
      expect(pipeline.realTimeFactor, greaterThanOrEqualTo(0));
    });

    test(
      'sheds short utterances while decoding runs slower than real time',
      () {
        final clock = [0];
        // Every decode takes 3 s of fake time for ~1.5 s of audio: RTF 2.
        final decoder = FakeDecoder(
          ['جمله‌ی اول که طولانی است', 'اوه', 'جمله‌ی سوم که طولانی است'],
          clock: clock,
          microsPerCall: 3000000,
        );
        final pipeline = LivePipeline(
          vadFactory: () => FakeVad([
            ScriptedSpan(at: 16000, start: 0, length: 16000),
            ScriptedSpan(at: 48000, start: 32000, length: 4000),
            ScriptedSpan(at: 112000, start: 80000, length: 16000),
          ]),
          decoder: decoder,
          nowMicros: () => clock[0],
        );
        final first = pipeline.feed(pcmSeconds(1));
        expect(first.single, isA<LiveUtterance>());
        expect(pipeline.lightMode, isTrue);
        // 0.25 s filler: dropped without a decode.
        expect(pipeline.feed(pcmSeconds(2)), isEmpty);
        expect(decoder.inputLengths, hasLength(1));
        // Long speech is still decoded in light mode.
        final third = pipeline.feed(pcmSeconds(4));
        expect(third.single, isA<LiveUtterance>());
        expect(decoder.inputLengths, hasLength(2));
      },
    );

    test('finish closes the VAD', () {
      final vad = FakeVad();
      final pipeline = pipelineWith([vad], FakeDecoder([]));
      pipeline.finish();
      expect(vad.flushed, isTrue);
      expect(vad.disposed, isTrue);
    });
  });
}
