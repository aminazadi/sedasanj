import 'dart:async';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/asr/live_asr_engine.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';
import 'package:jalase_negar/features/meetings/data/transcript_store.dart';
import 'package:jalase_negar/features/recording/application/live_transcript_session.dart';

class FakeEngine implements LiveAsrEngine {
  final StreamController<LiveEvent> controller = StreamController.broadcast();
  final List<Uint8List> fed = [];
  int flushes = 0;
  int stops = 0;
  bool disposed = false;
  Object? stopError;

  /// Events delivered while `stop` drains, like the real engine's tail.
  List<LiveEvent> onStop = const [];

  @override
  Stream<LiveEvent> get events => controller.stream;

  @override
  Future<void> start() async {}

  @override
  void feed(Uint8List pcm16) => fed.add(pcm16);

  @override
  void flush() => flushes++;

  @override
  Future<void> stop({Duration timeout = const Duration(seconds: 15)}) async {
    stops++;
    for (final event in onStop) {
      controller.add(event);
    }
    await Future<void>.delayed(Duration.zero);
    if (stopError != null) throw stopError!;
  }

  @override
  Future<void> dispose() async => disposed = true;

  void emit(LiveEvent event) => controller.add(event);
}

class MemoryStore implements TranscriptStore {
  final List<String> identities = [];
  final List<Segment> appended = [];
  List<Segment>? replaced;
  bool failAppend = false;

  @override
  Future<void> setAsrIdentity(String meetingId, String identity) async =>
      identities.add(identity);

  @override
  Future<void> appendSegments(String meetingId, List<Segment> segments) async {
    if (failAppend) throw StateError('disk full');
    appended.addAll(segments);
  }

  @override
  Future<void> replaceSegments(String meetingId, List<Segment> segments) async {
    replaced = segments;
  }
}

Future<void> settle() => Future<void>.delayed(const Duration(milliseconds: 30));

void main() {
  late FakeEngine engine;
  late MemoryStore store;
  late LiveTranscriptSession session;

  setUp(() {
    engine = FakeEngine();
    store = MemoryStore();
    session = LiveTranscriptSession(
      engine: engine,
      store: store,
      meetingId: 'm1',
      modelId: 'shenava-test',
      persistInterval: const Duration(milliseconds: 10),
    );
  });

  test('starts preparing and becomes live when the model is ready', () async {
    await session.start();
    expect(session.state.value.phase, LivePhase.preparing);
    engine.emit(const LiveReady());
    await settle();
    expect(session.state.value.phase, LivePhase.listening);
  });

  test('shows utterances in order and saves them while recording', () async {
    await session.start();
    engine.emit(const LiveReady());
    engine.emit(const LiveUtterance(startMs: 0, endMs: 1500, text: 'سلام'));
    engine.emit(
      const LiveUtterance(startMs: 5000, endMs: 6000, text: 'خداحافظ'),
    );
    await settle();
    expect(session.state.value.lines, ['سلام', 'خداحافظ']);
    expect(store.appended.map((s) => s.text), ['سلام', 'خداحافظ']);
    expect(store.identities, hasLength(1));
    expect(
      store.identities.single,
      'shenava-test|device-quiet-gain-v1|segmenter:silero-vad-live',
    );
  });

  test('keeps only the latest lines on screen', () async {
    final small = LiveTranscriptSession(
      engine: engine,
      store: store,
      meetingId: 'm1',
      modelId: 'm',
      maxLines: 2,
    );
    await small.start();
    for (var i = 0; i < 4; i++) {
      engine.emit(
        LiveUtterance(startMs: i * 5000, endMs: i * 5000 + 1000, text: 'خط $i'),
      );
    }
    await settle();
    expect(small.state.value.lines, ['خط 2', 'خط 3']);
    await small.dispose();
  });

  test('forwards audio and pauses only while running', () async {
    await session.start();
    session.feed(Uint8List(4));
    session.pause();
    expect(engine.fed, hasLength(1));
    expect(engine.flushes, 1);
    await session.stop();
    session.feed(Uint8List(4));
    session.pause();
    expect(engine.fed, hasLength(1));
    expect(engine.flushes, 1);
  });

  test('stop saves the tail and replaces rows with merged turns', () async {
    await session.start();
    engine.emit(const LiveReady());
    engine.emit(const LiveUtterance(startMs: 0, endMs: 1000, text: 'امروز'));
    engine.onStop = const [
      LiveUtterance(startMs: 1500, endMs: 2500, text: 'جلسه داریم'),
    ];
    await session.stop();
    // 500 ms apart, same channel: one readable turn.
    expect(store.replaced, hasLength(1));
    expect(store.replaced!.single.text, 'امروز جلسه داریم');
    expect(store.replaced!.single.startMs, 0);
    expect(store.replaced!.single.endMs, 2500);
    expect(session.state.value.phase, LivePhase.off);
    expect(engine.stops, 1);
  });

  test('stop with no speech leaves the stored transcript alone', () async {
    await session.start();
    engine.emit(const LiveReady());
    await session.stop();
    expect(store.replaced, isNull);
    expect(store.identities, isEmpty);
  });

  test('a fatal engine failure shows a hint and never throws', () async {
    await session.start();
    engine.emit(const LiveFailure('مدل بارگذاری نشد', fatal: true));
    await settle();
    expect(session.state.value.phase, LivePhase.failed);
    expect(session.state.value.note, contains('مدل بارگذاری نشد'));
    expect(session.state.value.note, contains('JN-ASR-0001'));
    await session.stop();
    expect(session.state.value.phase, LivePhase.failed);
  });

  test('a non-fatal failure only sets the note', () async {
    await session.start();
    engine.emit(const LiveReady());
    engine.emit(const LiveFailure('خطای کوچک'));
    await settle();
    expect(session.state.value.phase, LivePhase.listening);
    expect(session.state.value.note, contains('خطای کوچک'));
    expect(session.state.value.note, contains('JN-ASR-0001'));
  });

  test('skipped speech and lag are reported without stopping', () async {
    await session.start();
    engine.emit(const LiveReady());
    engine.emit(const LiveLagState(lagging: true));
    await settle();
    expect(session.state.value.phase, LivePhase.lagging);
    engine.emit(const LiveSkipped(startMs: 0, endMs: 2000));
    await settle();
    expect(session.state.value.skipped, 1);
    expect(session.state.value.note, contains('JN-ASR-0001'));
    engine.emit(const LiveLagState(lagging: false));
    await settle();
    expect(session.state.value.phase, LivePhase.listening);
  });

  test('tracks whether speech is being heard', () async {
    await session.start();
    engine.emit(const LiveReady());
    engine.emit(const LiveSpeechState(speaking: true));
    await settle();
    expect(session.state.value.speaking, isTrue);
    engine.emit(const LiveSpeechState(speaking: false));
    await settle();
    expect(session.state.value.speaking, isFalse);
  });

  test('a failing store does not break the session', () async {
    store.failAppend = true;
    await session.start();
    engine.emit(const LiveUtterance(startMs: 0, endMs: 1000, text: 'سلام'));
    await settle();
    expect(session.state.value.lines, ['سلام']);
    await session.stop();
    // The final rewrite still carries the text kept in memory.
    expect(store.replaced!.single.text, 'سلام');
  });

  test('an engine that throws on stop still finishes the draft', () async {
    engine.stopError = StateError('isolate gone');
    await session.start();
    engine.emit(const LiveUtterance(startMs: 0, endMs: 1000, text: 'سلام'));
    await session.stop();
    expect(store.replaced!.single.text, 'سلام');
  });

  test('dispose frees the engine without saving', () async {
    await session.start();
    engine.emit(const LiveUtterance(startMs: 0, endMs: 1000, text: 'سلام'));
    await session.dispose();
    expect(engine.disposed, isTrue);
    expect(store.replaced, isNull);
  });
}
