import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../../core/asr/asr_identity.dart';
import '../../../core/asr/consolidate.dart';
import '../../../core/asr/live_asr_engine.dart';
import '../../../core/asr/transcriber.dart' show AsrSegmenter;
import '../../meetings/data/meeting.dart';
import '../../meetings/data/transcript_store.dart';

enum LivePhase {
  /// Live transcription is not running (disabled, or the models are missing).
  off,

  /// The model is loading; audio is already being kept for it.
  preparing,

  listening,

  /// Decoding is further behind the microphone than it should be.
  lagging,

  /// The engine stopped; the recording itself continues.
  failed,
}

class LiveTranscriptState {
  const LiveTranscriptState({
    this.phase = LivePhase.off,
    this.lines = const [],
    this.speaking = false,
    this.note,
    this.skipped = 0,
  });

  final LivePhase phase;

  /// Finished utterances in time order (the latest [LiveTranscriptSession.maxLines]).
  final List<String> lines;

  /// A voice is being heard right now, its text not finished yet.
  final bool speaking;

  /// Persian explanation of the current phase, when one is useful.
  final String? note;

  /// Speech spans left out because decoding fell behind.
  final int skipped;

  LiveTranscriptState copyWith({
    LivePhase? phase,
    List<String>? lines,
    bool? speaking,
    String? note,
    bool clearNote = false,
    int? skipped,
  }) => LiveTranscriptState(
    phase: phase ?? this.phase,
    lines: lines ?? this.lines,
    speaking: speaking ?? this.speaking,
    note: clearNote ? null : (note ?? this.note),
    skipped: skipped ?? this.skipped,
  );
}

/// Owns one recording's live transcription: feeds the engine, mirrors its
/// output into [state] for the screen, writes utterances to the database while
/// the meeting is recorded, and saves the transcript when recording stops.
///
/// Nothing here may disturb the recording: engine and database errors only
/// change [state].
class LiveTranscriptSession {
  LiveTranscriptSession({
    required this.engine,
    required this.store,
    required this.meetingId,
    required this.modelId,
    this.maxLines = 300,
    this.persistInterval = const Duration(seconds: 2),
  });

  final LiveAsrEngine engine;
  final TranscriptStore store;
  final String meetingId;
  final String modelId;
  final int maxLines;
  final Duration persistInterval;

  final ValueNotifier<LiveTranscriptState> state = ValueNotifier(
    const LiveTranscriptState(phase: LivePhase.preparing),
  );

  final List<AsrTurn> _all = [];
  final List<Segment> _unsaved = [];
  StreamSubscription<LiveEvent>? _events;
  Timer? _persistTimer;
  Future<void> _writes = Future.value();
  bool _identityWritten = false;
  bool _stopped = false;

  Future<void> start() async {
    _events = engine.events.listen(_onEvent);
    _persistTimer = Timer.periodic(persistInterval, (_) => _persist());
    await engine.start();
  }

  void feed(Uint8List pcm16) {
    if (_stopped) return;
    engine.feed(pcm16);
  }

  /// Pause or interruption: finish the sentence in progress.
  void pause() {
    if (_stopped) return;
    engine.flush();
  }

  /// Finishes the transcript: waits for the engine to drain, saves what is
  /// left, and replaces the per-utterance rows with merged turns. Never throws.
  Future<void> stop() async {
    if (_stopped) return;
    _stopped = true;
    try {
      await engine.stop();
    } catch (_) {
      // The engine reports its own failures; keep the text that arrived.
    }
    _persistTimer?.cancel();
    await _events?.cancel();
    try {
      _persist();
      await _writes;
      if (_all.isNotEmpty) {
        final turns = consolidateSegments(_all);
        await store.replaceSegments(meetingId, [
          for (final turn in turns)
            Segment(
              channel: turn.channel,
              startMs: turn.startMs,
              endMs: turn.endMs,
              text: turn.text,
              confidence: turn.confidence,
              timestampSource:
                  turn.timestampSource ?? TimestampSource.sileroVad,
              speaker: turn.speaker,
              speakerPersonId: turn.speakerPersonId,
              speaker2: turn.speaker2,
              speaker2PersonId: turn.speaker2PersonId,
              overlap: turn.overlap,
              speakerConfidence: turn.speakerConfidence,
            ),
        ]);
      }
    } catch (_) {
      // Keep the rows already appended.
    }
    final current = state.value;
    state.value = current.copyWith(
      phase: current.phase == LivePhase.failed
          ? LivePhase.failed
          : LivePhase.off,
      speaking: false,
    );
  }

  Future<void> dispose() async {
    _stopped = true;
    _persistTimer?.cancel();
    await _events?.cancel();
    await engine.dispose();
  }

  void _onEvent(LiveEvent event) {
    final current = state.value;
    switch (event) {
      case LiveReady():
        state.value = current.copyWith(
          phase: LivePhase.listening,
          clearNote: true,
        );
      case LiveUtterance():
        _all.add(
          AsrTurn(
            channel: 0,
            startMs: event.startMs,
            endMs: event.endMs,
            text: event.text,
            timestampSource: TimestampSource.sileroVad,
            speaker: event.speaker?.name,
            speakerPersonId: event.speaker?.personId,
            speaker2: event.speaker2?.name,
            speaker2PersonId: event.speaker2?.personId,
            overlap: event.overlap,
            speakerConfidence: event.speakerConfidence,
          ),
        );
        final segment = Segment(
          channel: 0,
          startMs: event.startMs,
          endMs: event.endMs,
          text: event.text,
          speaker: event.speaker?.name,
          speakerPersonId: event.speaker?.personId,
          speaker2: event.speaker2?.name,
          speaker2PersonId: event.speaker2?.personId,
          overlap: event.overlap,
          speakerConfidence: event.speakerConfidence,
        );
        _unsaved.add(segment);
        // The panel shows `Name: text`; a line spoken over another voice is
        // marked so it is read with care.
        final shown = event.overlap
            ? '${segment.labeledText} (هم‌زمان)'
            : segment.labeledText;
        final lines = [...current.lines, shown];
        if (lines.length > maxLines) {
          lines.removeRange(0, lines.length - maxLines);
        }
        state.value = current.copyWith(lines: lines);
      case LiveSkipped():
        state.value = current.copyWith(
          skipped: current.skipped + 1,
          note:
              'گوشی از گفتار عقب افتاد و بخشی از متن زنده جا ماند. برای شنیدن آن، فایل جلسه را پخش کنید. ($kIncompleteLiveTranscriptCode)',
        );
      case LiveSpeechState():
        state.value = current.copyWith(speaking: event.speaking);
      case LiveLagState():
        if (current.phase == LivePhase.failed) return;
        state.value = current.copyWith(
          phase: event.lagging ? LivePhase.lagging : LivePhase.listening,
          note: event.lagging
              ? 'متن زنده کمی عقب است؛ ضبط بدون مشکل ادامه دارد.'
              : null,
          clearNote: !event.lagging,
        );
      case LiveFailure():
        final note =
            '${event.message} برای شنیدن بخش‌های ثبت‌نشده، فایل جلسه را پخش کنید. ($kIncompleteLiveTranscriptCode)';
        if (event.fatal) {
          state.value = current.copyWith(
            phase: LivePhase.failed,
            speaking: false,
            note: 'ضبط ادامه دارد. $note',
          );
        } else {
          state.value = current.copyWith(note: note);
        }
      case LiveDone():
        break;
    }
  }

  /// Queues the utterances finished since the last write. Writes are chained
  /// so rows land in order and a slow disk never overlaps two transactions.
  void _persist() {
    if (_unsaved.isEmpty) return;
    final batch = List<Segment>.of(_unsaved);
    _unsaved.clear();
    _writes = _writes.then((_) async {
      try {
        if (!_identityWritten) {
          _identityWritten = true;
          await store.setAsrIdentity(
            meetingId,
            buildAsrIdentity(
              modelId: modelId,
              segmenter: AsrSegmenter.silero,
              live: true,
            ),
          );
        }
        await store.appendSegments(meetingId, batch);
      } catch (_) {
        // Held in memory too: the stop-time rewrite retries the whole draft.
      }
    });
  }
}
