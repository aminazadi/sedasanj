import 'dart:io';
import 'package:flutter/services.dart';

/// One audio input device with its real channel count.
class CaptureSource {
  const CaptureSource({
    required this.uid,
    required this.name,
    required this.channels,
    required this.sampleRate,
    this.memberUids = const [],
    this.builtIn = false,
    this.builtInChannels = const {},
  });

  factory CaptureSource.fromMap(Map<Object?, Object?> m) => CaptureSource(
    uid: m['uid']! as String,
    name: (m['name'] as String?) ?? (m['uid']! as String),
    channels: (m['channels'] as num).toInt(),
    sampleRate: (m['sampleRate'] as num?)?.toDouble() ?? 0,
    builtIn:
        (m['builtIn'] as bool?) ??
        RegExp(
          r'MacBook|iMac|Mac mini|Mac Studio|Built-?in',
          caseSensitive: false,
        ).hasMatch((m['name'] as String?) ?? ''),
  );

  final String uid;
  final String name;
  final int channels;
  final double sampleRate;

  /// The computer's own microphone: its several channels are one array, not
  /// several microphones, so it is recorded the ordinary mono way.
  final bool builtIn;

  /// For a combined source: the channels (0-based) that belong to the
  /// device's own microphone.
  final Set<int> builtInChannels;

  /// For a combined source: the devices to open together, in channel order.
  /// Empty for a single device ([uid] alone).
  final List<String> memberUids;

  List<String> get uids => memberUids.isEmpty ? [uid] : memberUids;
}

/// What the platform actually started: the real channel count of the stream
/// (interleaved little-endian PCM16 at [sampleRate]).
class CaptureInfo {
  const CaptureInfo({required this.channels, required this.sampleRate});
  final int channels;
  final int sampleRate;
}

/// Native capture of every channel of one input device: CoreAudio on macOS,
/// the external USB input on Android (AudioRecord; together with the phone's
/// own microphone when the phone allows a second stream) and iOS
/// (AVAudioEngine). Other platforms report [isSupported] false and
/// keep using the mono `record` path.
class MultichannelCapture {
  MultichannelCapture({
    MethodChannel? method,
    EventChannel? events,
    bool? supported,
  }) : _method = method ?? const MethodChannel('jalase/multichannel_capture'),
       _events =
           events ?? const EventChannel('jalase/multichannel_capture/pcm'),
       isSupported =
           supported ??
           (Platform.isMacOS || Platform.isAndroid || Platform.isIOS);

  final MethodChannel _method;
  final EventChannel _events;
  final bool isSupported;

  /// Inputs with at least one channel. Empty when unsupported.
  Future<List<CaptureSource>> listSources() async {
    if (!isSupported) return const [];
    final raw = await _method.invokeListMethod<Map<Object?, Object?>>(
      'listInputs',
    );
    return [for (final m in raw ?? const []) CaptureSource.fromMap(m)];
  }

  /// Starts capture; [pcm] must be listened to before the first audio is
  /// needed. Throws [PlatformException] with code `mic_denied`,
  /// `device_missing`, `no_input`, `format`, `ioproc` or `start`.
  Future<CaptureInfo> start(List<String> deviceUids) async {
    final m = await _method.invokeMapMethod<String, Object?>('start', {
      'deviceUids': deviceUids,
    });
    return CaptureInfo(
      channels: (m!['channels']! as num).toInt(),
      sampleRate: (m['sampleRate']! as num).toInt(),
    );
  }

  Future<void> stop() => _method.invokeMethod<void>('stop');

  /// Interleaved PCM16 chunks of the running capture.
  Stream<Uint8List> get pcm =>
      _events.receiveBroadcastStream().cast<Uint8List>();
}
