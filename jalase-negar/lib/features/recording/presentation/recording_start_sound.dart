import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:just_audio/just_audio.dart';

final recordingStartSoundProvider = Provider<RecordingStartSound Function()>(
  (ref) => RecordingStartSound.new,
);

/// Owns the short cue for one attempt and preloads it during the wind effect.
class RecordingStartSound {
  RecordingStartSound() {
    _ready = _load();
  }

  final _player = AudioPlayer(handleInterruptions: false);
  late final Future<bool> _ready;
  Future<void>? _closing;
  int _cue = 0;
  bool _reportedFailure = false;

  Future<bool> _load() async {
    try {
      await _player.setAsset('assets/audio/countdown-beep.wav');
      return true;
    } catch (_) {
      if (_closing == null) _reportFailure();
      return false;
    }
  }

  bool _isCurrent(int cue) => _closing == null && cue == _cue;

  Future<void> play() async {
    final cue = ++_cue;
    try {
      if (!await _ready || !_isCurrent(cue)) return;
      await _player.pause();
      await _player.seek(Duration.zero);
      if (_isCurrent(cue)) await _player.play();
    } catch (_) {
      if (_isCurrent(cue)) _reportFailure();
    }
  }

  Future<void> close() => _closing ??= _dispose();

  Future<void> _dispose() async {
    try {
      await _player.dispose().timeout(const Duration(milliseconds: 500));
    } catch (_) {
      _reportFailure();
    }
  }

  void _reportFailure() {
    if (_reportedFailure) return;
    _reportedFailure = true;
    debugPrint('JN-REC-0002: Check media volume and retry a short recording.');
  }
}
