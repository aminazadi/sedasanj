import 'dart:typed_data';

const kIncompleteLiveTranscriptCode = 'JN-ASR-0001';

/// Events a live engine reports while a recording is in progress.
sealed class LiveEvent {
  const LiveEvent();
}

/// The model finished loading; audio fed earlier is being processed now.
class LiveReady extends LiveEvent {
  const LiveReady();
}

/// One finished utterance. Times are on the recording's sample timeline, so
/// they line up with the saved WAV (paused time is not counted).
class LiveUtterance extends LiveEvent {
  const LiveUtterance({
    required this.startMs,
    required this.endMs,
    required this.text,
  });

  final int startMs;
  final int endMs;
  final String text;
}

/// Speech that was detected but not decoded because the engine had fallen too
/// far behind the microphone.
class LiveSkipped extends LiveEvent {
  const LiveSkipped({required this.startMs, required this.endMs});

  final int startMs;
  final int endMs;
}

/// Voice activity changed (drives the "listening" indicator).
class LiveSpeechState extends LiveEvent {
  const LiveSpeechState({required this.speaking});

  final bool speaking;
}

/// The engine is (or is no longer) too far behind real time.
class LiveLagState extends LiveEvent {
  const LiveLagState({required this.lagging});

  final bool lagging;
}

/// A problem inside the engine. [fatal] means no more output will come; the
/// recording itself is never affected.
class LiveFailure extends LiveEvent {
  const LiveFailure(this.message, {this.fatal = false});

  final String message;
  final bool fatal;
}

/// Everything fed before `stop` has been decoded and reported.
class LiveDone extends LiveEvent {
  const LiveDone();
}

/// A recognizer that turns the microphone stream into text while recording.
///
/// Implementations must never throw into the recording path: [feed], [flush]
/// and [stop] swallow errors and report them as [LiveFailure] events.
abstract interface class LiveAsrEngine {
  Stream<LiveEvent> get events;

  /// Loads the model in the background. Audio passed to [feed] before the
  /// model is ready is kept and processed afterwards.
  Future<void> start();

  /// PCM16 little-endian, 16 kHz, mono.
  void feed(Uint8List pcm16);

  /// Finishes the utterance in progress (pause, interruption).
  void flush();

  /// Finishes everything already fed, waiting at most [timeout], then frees
  /// the model.
  Future<void> stop({Duration timeout = const Duration(seconds: 15)});

  /// Frees resources immediately without waiting for pending audio.
  Future<void> dispose();
}
