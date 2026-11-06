import 'dart:async';
import 'dart:convert';
import 'dart:isolate';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:record/record.dart';
import 'package:sherpa_onnx/sherpa_onnx.dart' as sherpa;
import 'package:uuid/uuid.dart';

import '../../../core/asr/asr_common.dart';
import '../../../core/speaker/sherpa_speaker.dart';
import 'enrollment_quality.dart';
import 'people_repository.dart';
import 'person.dart';

/// One text the person reads to record their voice.
class SpeakerPrompt {
  const SpeakerPrompt({
    required this.id,
    required this.text,
    required this.required,
    required this.near,
  });

  final String id;
  final String text;
  final bool required;

  /// Read close to the microphone; otherwise from about 50 cm, so the voiceprint
  /// also covers the distance of a meeting room.
  final bool near;
}

class SpeakerPrompts {
  const SpeakerPrompts({required this.version, required this.prompts});

  final String version;
  final List<SpeakerPrompt> prompts;

  int get requiredCount => prompts.where((p) => p.required).length;

  factory SpeakerPrompts.parse(String source) {
    final json = jsonDecode(source) as Map<String, dynamic>;
    return SpeakerPrompts(
      version: json['version'] as String,
      prompts: [
        for (final p in (json['prompts'] as List).cast<Map<String, dynamic>>())
          SpeakerPrompt(
            id: p['id'] as String,
            text: p['text'] as String,
            required: p['required'] == true,
            near: p['distance'] != 'far',
          ),
      ],
    );
  }
}

/// Records the microphone for the enrolment.
abstract interface class EnrollmentRecorder {
  /// False when the microphone permission was refused.
  Future<bool> start();

  /// Input level 0..1 while recording.
  Stream<double> get levels;

  /// Ends the recording and returns 16 kHz mono floats.
  Future<Float32List> stop();

  Future<void> dispose();
}

class MicEnrollmentRecorder implements EnrollmentRecorder {
  final AudioRecorder _recorder = AudioRecorder();
  final _levels = StreamController<double>.broadcast();
  final BytesBuilder _pcm = BytesBuilder(copy: false);
  StreamSubscription<Uint8List>? _subscription;

  @override
  Stream<double> get levels => _levels.stream;

  @override
  Future<bool> start() async {
    if (!await _recorder.hasPermission()) return false;
    _pcm.clear();
    final stream = await _recorder.startStream(
      const RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: kAsrSampleRate,
        numChannels: 1,
        // Raw voice: the platform's gain and noise suppression would change
        // the voiceprint compared with the meeting recordings it is matched to.
        autoGain: false,
        noiseSuppress: false,
        echoCancel: false,
      ),
    );
    _subscription = stream.listen((chunk) {
      _pcm.add(chunk);
      if (_levels.hasListener) _levels.add(_rms(chunk));
    });
    return true;
  }

  double _rms(Uint8List bytes) {
    final view = ByteData.sublistView(bytes);
    final n = bytes.length ~/ 2;
    if (n == 0) return 0;
    var sum = 0.0;
    for (var i = 0; i < n; i++) {
      final v = view.getInt16(i * 2, Endian.little) / 32768.0;
      sum += v * v;
    }
    return (sum / n).clamp(0.0, 1.0).toDouble();
  }

  @override
  Future<Float32List> stop() async {
    await _recorder.stop();
    await _subscription?.cancel();
    _subscription = null;
    final bytes = _pcm.takeBytes();
    final view = ByteData.sublistView(bytes);
    final out = Float32List(bytes.length ~/ 2);
    for (var i = 0; i < out.length; i++) {
      out[i] = view.getInt16(i * 2, Endian.little) / 32768.0;
    }
    return out;
  }

  @override
  Future<void> dispose() async {
    await _subscription?.cancel();
    await _recorder.dispose();
    await _levels.close();
  }
}

/// Turns recorded audio into a voice embedding with the installed model.
abstract interface class VoiceEmbeddingService {
  String get modelId;
  String get modelVersion;

  /// Null when the audio could not be embedded.
  Future<Float32List?> embed(Float32List samples);
}

class SherpaEmbeddingService implements VoiceEmbeddingService {
  SherpaEmbeddingService({
    required this.modelPath,
    required this.modelId,
    required this.modelVersion,
    this.threads = 2,
  });

  final String modelPath;

  /// Cores one embedding may use (the owner's CPU limit in Settings).
  final int threads;

  @override
  final String modelId;

  @override
  final String modelVersion;

  @override
  Future<Float32List?> embed(Float32List samples) {
    final path = modelPath;
    final threads = this.threads;
    return Isolate.run(() {
      sherpa.initBindings();
      final embedder = SherpaVoiceEmbedder.tryCreate(path, numThreads: threads);
      if (embedder == null) return null;
      try {
        return embedder.embed(samples);
      } finally {
        embedder.free();
      }
    });
  }
}

enum EnrollmentPhase { idle, recording, processing, finished }

class EnrollmentState {
  const EnrollmentState({
    this.index = 0,
    this.phase = EnrollmentPhase.idle,
    this.level = 0,
    this.message,
    this.accepted = const {},
    this.permissionDenied = false,
  });

  /// The prompt being read.
  final int index;
  final EnrollmentPhase phase;
  final double level;

  /// Why the last recording was refused, or how to continue.
  final String? message;

  /// Prompt ids whose voiceprint is stored.
  final Set<String> accepted;
  final bool permissionDenied;

  EnrollmentState copyWith({
    int? index,
    EnrollmentPhase? phase,
    double? level,
    String? message,
    bool clearMessage = false,
    Set<String>? accepted,
    bool? permissionDenied,
  }) => EnrollmentState(
    index: index ?? this.index,
    phase: phase ?? this.phase,
    level: level ?? this.level,
    message: clearMessage ? null : (message ?? this.message),
    accepted: accepted ?? this.accepted,
    permissionDenied: permissionDenied ?? this.permissionDenied,
  );
}

/// Walks one person through reading the prompts. Every accepted recording is
/// stored at once (and queued for sync), so leaving half way keeps the progress.
class EnrollmentSession {
  EnrollmentSession({
    required this.personId,
    required this.prompts,
    required this.recorder,
    required this.embedder,
    required this.repository,
    Uuid uuid = const Uuid(),
    EnrollmentAssessment Function(Float32List)? assess,
  }) : _uuid = uuid,
       _assess = assess ?? assessEnrollmentSample;

  final String personId;
  final SpeakerPrompts prompts;
  final EnrollmentRecorder recorder;
  final VoiceEmbeddingService embedder;
  final PeopleRepository repository;
  final Uuid _uuid;
  final EnrollmentAssessment Function(Float32List) _assess;

  final ValueNotifier<EnrollmentState> state = ValueNotifier(
    const EnrollmentState(),
  );
  StreamSubscription<double>? _levels;

  SpeakerPrompt get current => prompts.prompts[state.value.index];

  /// The required prompts are done: the voice can be recognised.
  bool get canFinish => prompts.prompts
      .where((p) => p.required)
      .every((p) => state.value.accepted.contains(p.id));

  Future<void> start() async {
    if (state.value.phase != EnrollmentPhase.idle) return;
    final granted = await recorder.start();
    if (!granted) {
      state.value = state.value.copyWith(
        permissionDenied: true,
        message:
            'دسترسی به میکروفون داده نشد؛ در تنظیمات گوشی اجازه‌ی میکروفون را فعال کنید.',
      );
      return;
    }
    _levels = recorder.levels.listen(
      (v) => state.value = state.value.copyWith(level: v),
    );
    state.value = state.value.copyWith(
      phase: EnrollmentPhase.recording,
      clearMessage: true,
      permissionDenied: false,
    );
  }

  /// Stops, checks the quality and stores the voiceprint when it is good.
  /// Returns whether the recording was accepted.
  Future<bool> stop() async {
    if (state.value.phase != EnrollmentPhase.recording) return false;
    await _levels?.cancel();
    _levels = null;
    state.value = state.value.copyWith(
      phase: EnrollmentPhase.processing,
      level: 0,
    );
    final samples = await recorder.stop();
    final assessment = _assess(samples);
    if (!assessment.ok) {
      state.value = state.value.copyWith(
        phase: EnrollmentPhase.idle,
        message: assessment.messageFa,
      );
      return false;
    }
    final embedding = await embedder.embed(samples);
    if (embedding == null || embedding.isEmpty) {
      state.value = state.value.copyWith(
        phase: EnrollmentPhase.idle,
        message:
            'ردصدا ساخته نشد؛ دوباره بخوانید و اگر تکرار شد مدل «تشخیص گوینده» را در بخش «مدل‌ها» دوباره نصب کنید.',
      );
      return false;
    }
    await repository.addVoiceprints(personId, [
      Voiceprint(
        clientId: _uuid.v4(),
        personId: personId,
        modelId: embedder.modelId,
        modelVersion: embedder.modelVersion,
        embedding: embedding,
        createdAt: DateTime.now(),
        quality: assessment.quality,
        durationMs: assessment.speechMs,
      ),
    ]);
    final accepted = {...state.value.accepted, current.id};
    final last = state.value.index >= prompts.prompts.length - 1;
    state.value = state.value.copyWith(
      accepted: accepted,
      index: last ? state.value.index : state.value.index + 1,
      phase: last ? EnrollmentPhase.finished : EnrollmentPhase.idle,
      clearMessage: true,
    );
    return true;
  }

  /// Skips an optional text, or goes back to read one again.
  void goTo(int index) {
    if (state.value.phase == EnrollmentPhase.recording ||
        state.value.phase == EnrollmentPhase.processing) {
      return;
    }
    state.value = state.value.copyWith(
      index: index.clamp(0, prompts.prompts.length - 1),
      phase: EnrollmentPhase.idle,
      clearMessage: true,
    );
  }

  Future<void> dispose() async {
    await _levels?.cancel();
    await recorder.dispose();
    state.dispose();
  }
}
