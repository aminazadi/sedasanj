import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../../core/asr/asr_identity.dart';
import '../../../core/asr/consolidate.dart';
import '../../../core/asr/inline_sound_events.dart';
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
    this.persistDelay = const Duration(seconds: 6),
  });

  final LiveAsrEngine engine;
  final TranscriptStore store;
  final String meetingId;
  final String modelId;
  final int maxLines;
  final Duration persistInterval;

  /// A finished line waits this long before it is written to the database,
  /// because a sound found in it (laughter, a cough) is reported a few seconds
  /// after the speech and is written into that line. The stop-time rewrite
  /// always has everything.
  final Duration persistDelay;

  final ValueNotifier<LiveTranscriptState> state = ValueNotifier(
    const LiveTranscriptState(phase: LivePhase.preparing),
  );

  final List<LiveUtterance> _utterances = [];
  final List<SoundMark> _marks = [];

  /// Indexes into [_utterances] not yet written, with the time they arrived.
  final List<(int, DateTime)> _unsaved = [];
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
      _persist(force: true);
      await _writes;
      final turns = consolidateSegments(_finalTurns());
      if (turns.isNotEmpty) {
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
        _utterances.add(event);
        _unsaved.add((_utterances.length - 1, DateTime.now()));
        state.value = current.copyWith(lines: _renderLines());
      case LiveSoundEvent():
        // A sound is written inside the line of whoever was speaking, at the
        // word where it happened; only a sound far from any speech gets a line
        // of its own (see placeSoundMarks).
        _marks.add(
          SoundMark(
            startMs: event.startMs,
            endMs: event.endMs,
            marker: event.text,
          ),
        );
        state.value = current.copyWith(lines: _renderLines());
      case LiveSoundEventsUnavailable():
        state.value = current.copyWith(
          note:
              'متن گفتار ادامه دارد، ولی خنده، گریه و صداهای مشابه در متن نوشته نمی‌شوند. مدل «تشخیص صداهای انسانی» را در بخش «مدل‌ها» دوباره دانلود کنید. ($kSoundEventsUnavailableCode)',
        );
      case LiveSkipped():
        state.value = current.copyWith(
          skipped: current.skipped + 1,
          note:
              'گوشی از گفتار عقب افتاد و بخشی از متن زنده جا ماند. برای شنیدن آن، فایل جلسه را پخش کنید. ($kIncompleteLiveTranscriptCode)',
        );
      case LiveRecovered():
        final remaining = current.skipped > 0 ? current.skipped - 1 : 0;
        state.value = current.copyWith(
          skipped: remaining,
          clearNote:
              remaining == 0 &&
              (current.note?.contains(kIncompleteLiveTranscriptCode) ?? false),
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

  List<SpeechSpan> get _spans => [
    for (final u in _utterances)
      SpeechSpan(
        startMs: u.startMs,
        endMs: u.endMs,
        text: u.text,
        words: u.words,
      ),
  ];

  Segment _segmentOf(LiveUtterance u, String text) => Segment(
    channel: 0,
    startMs: u.startMs,
    endMs: u.endMs,
    text: text,
    speaker: u.speaker?.name,
    speakerPersonId: u.speaker?.personId,
    speaker2: u.speaker2?.name,
    speaker2PersonId: u.speaker2?.personId,
    overlap: u.overlap,
    speakerConfidence: u.speakerConfidence,
  );

  /// The lines shown on screen, in time order: every utterance with its
  /// sounds written inside it, and the few sounds that stand alone.
  List<String> _renderLines() {
    final placement = placeSoundMarks(_spans, _marks);
    final rows = <(int, String)>[];
    for (var i = 0; i < _utterances.length; i++) {
      final u = _utterances[i];
      final segment = _segmentOf(u, placement.texts[i]);
      // The panel shows `Name: text`; a line spoken over another voice is
      // marked so it is read with care.
      rows.add((
        u.startMs,
        u.overlap ? '${segment.labeledText} (هم‌زمان)' : segment.labeledText,
      ));
    }
    for (final loose in placement.loose) {
      rows.add((loose.startMs, loose.text));
    }
    rows.sort((a, b) => a.$1.compareTo(b.$1));
    final lines = [for (final row in rows) row.$2];
    if (lines.length > maxLines) {
      lines.removeRange(0, lines.length - maxLines);
    }
    return lines;
  }

  /// Every turn of the finished recording, sounds included, for the merge
  /// into readable lines.
  List<AsrTurn> _finalTurns() {
    final placement = placeSoundMarks(_spans, _marks);
    return [
      for (var i = 0; i < _utterances.length; i++)
        AsrTurn(
          channel: 0,
          startMs: _utterances[i].startMs,
          endMs: _utterances[i].endMs,
          text: placement.texts[i],
          timestampSource: TimestampSource.sileroVad,
          speaker: _utterances[i].speaker?.name,
          speakerPersonId: _utterances[i].speaker?.personId,
          speaker2: _utterances[i].speaker2?.name,
          speaker2PersonId: _utterances[i].speaker2?.personId,
          overlap: _utterances[i].overlap,
          speakerConfidence: _utterances[i].speakerConfidence,
        ),
      for (final loose in placement.loose)
        AsrTurn(
          channel: 0,
          startMs: loose.startMs,
          endMs: loose.endMs,
          text: loose.text,
          timestampSource: TimestampSource.sileroVad,
        ),
    ];
  }

  /// Queues the utterances that have waited [persistDelay] (all of them when
  /// [force]). Writes are chained so rows land in order and a slow disk never
  /// overlaps two transactions.
  void _persist({bool force = false}) {
    if (_unsaved.isEmpty) return;
    final now = DateTime.now();
    final due = [
      for (final item in _unsaved)
        if (force || now.difference(item.$2) >= persistDelay) item,
    ];
    if (due.isEmpty) return;
    _unsaved.removeWhere(due.contains);
    final placement = placeSoundMarks(_spans, _marks);
    final batch = [
      for (final item in due)
        _segmentOf(_utterances[item.$1], placement.texts[item.$1]),
    ];
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
