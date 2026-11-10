import 'dart:io';

import 'package:path_provider/path_provider.dart';

/// Central place for on-disk locations so features never hardcode paths.
class AppPaths {
  AppPaths._(this.root);

  final Directory root;

  static AppPaths? _instance;

  static Future<AppPaths> instance() async {
    if (_instance != null) return _instance!;
    final docs = await getApplicationDocumentsDirectory();
    final paths = AppPaths._(docs);
    await paths.recordingsDir.create(recursive: true);
    await paths.chunksDir.create(recursive: true);
    await paths.modelsDir.create(recursive: true);
    await paths.derivedDir.create(recursive: true);
    _instance = paths;
    return paths;
  }

  Directory get recordingsDir => Directory('${root.path}/recordings');

  /// Closed WAV chunks of a meeting, waiting for upload.
  Directory get chunksDir => Directory('${root.path}/chunks');

  Directory meetingChunksDir(String meetingId) =>
      Directory('${chunksDir.path}/$meetingId');

  Directory get modelsDir => Directory('${root.path}/models');

  /// Per-channel WAVs and other regenerable artifacts.
  Directory get derivedDir => Directory('${root.path}/derived');

  String recordingPath(String meetingId) =>
      '${recordingsDir.path}/$meetingId.wav';

  /// Every microphone channel of a multi-microphone recording, interleaved.
  /// The meeting's own WAV stays a mono mix so playback, upload and speaker
  /// analysis keep working unchanged.
  String multiChannelWavPath(String meetingId) =>
      '${derivedDir.path}/$meetingId-all.wav';

  String channelWavPath(String meetingId, int channel) =>
      '${derivedDir.path}/$meetingId-ch$channel.wav';

  Directory modelDir(String modelId) => Directory('${modelsDir.path}/$modelId');
}
