import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/asr/live_asr_engine.dart';
import '../../../core/asr/vad_segment_engine.dart';
import '../../../core/models/model_catalog.dart';
import '../../../core/models/model_spec.dart';
import '../../../core/providers.dart';
import '../../models/application/models_controller.dart';

/// Settings key: live transcription during recording (absent means on).
const String kLiveTranscriptSettingKey = 'live_transcript_enabled';

/// Settings key of the switch that sends each meeting's transcript to
/// SedaSanj. Absent means on; audio is never sent either way.
const String kSendTranscriptSettingKey = 'send_transcript_enabled';

/// What a recording needs to start live transcription, or why it cannot.
class LiveEngineSetup {
  const LiveEngineSetup.ready({required this.engine, required this.modelId})
    : unavailableReason = null;

  const LiveEngineSetup.unavailable([this.unavailableReason])
    : engine = null,
      modelId = '';

  final LiveAsrEngine? engine;
  final String modelId;

  /// Persian hint shown on the recording screen; null when the user simply
  /// turned live transcription off.
  final String? unavailableReason;
}

typedef LiveEngineBuilder = Future<LiveEngineSetup> Function();

/// Builds the engine for a new recording. Overridden in tests with a fake.
final liveEngineBuilderProvider = Provider<LiveEngineBuilder>((ref) {
  return () async {
    final db = await ref.read(appDatabaseProvider.future);
    if (await db.getSetting(kLiveTranscriptSettingKey) == '0') {
      return const LiveEngineSetup.unavailable();
    }
    final store = await ref.read(modelStoreProvider.future);
    final asrId = await db.getSetting(kAsrModelSettingKey);
    if (asrId == null || asrId.isEmpty) {
      return const LiveEngineSetup.unavailable(
        'برای متن زنده، ابتدا یک مدل شنوا را از بخش «مدل‌ها» دانلود و انتخاب کنید.',
      );
    }
    final asrSpec = ModelCatalog.byId(asrId);
    final vadSpec = ModelCatalog.sileroVad;
    if (!await store.isInstalled(asrSpec) ||
        !await store.isInstalled(vadSpec)) {
      return const LiveEngineSetup.unavailable(
        'برای متن زنده، مدل شنوا و مدل تشخیص گفتار (VAD) باید کامل نصب باشند؛ به بخش «مدل‌ها» بروید.',
      );
    }
    final transducer = asrSpec.asrArchitecture == AsrArchitecture.transducer;
    final engine = VadSegmentEngine(
      VadSegmentConfig(
        vadModelPath: store.filePath(vadSpec, vadSpec.files[0]),
        tokensPath: store.filePath(asrSpec, asrSpec.files[transducer ? 3 : 1]),
        architecture: asrSpec.asrArchitecture,
        asrModelPath: transducer
            ? ''
            : store.filePath(asrSpec, asrSpec.files[0]),
        encoderPath: transducer
            ? store.filePath(asrSpec, asrSpec.files[0])
            : null,
        decoderPath: transducer
            ? store.filePath(asrSpec, asrSpec.files[1])
            : null,
        joinerPath: transducer
            ? store.filePath(asrSpec, asrSpec.files[2])
            : null,
      ),
    );
    return LiveEngineSetup.ready(engine: engine, modelId: asrSpec.id);
  };
});

/// The user's on/off choice for live transcription.
class LiveTranscriptEnabled extends AsyncNotifier<bool> {
  @override
  Future<bool> build() async {
    final db = await ref.watch(appDatabaseProvider.future);
    return await db.getSetting(kLiveTranscriptSettingKey) != '0';
  }

  Future<void> set(bool enabled) async {
    final db = await ref.read(appDatabaseProvider.future);
    await db.setSetting(kLiveTranscriptSettingKey, enabled ? '1' : '0');
    state = AsyncData(enabled);
  }
}

final liveTranscriptEnabledProvider =
    AsyncNotifierProvider<LiveTranscriptEnabled, bool>(
      LiveTranscriptEnabled.new,
    );

/// The user's on/off choice for sending meeting transcripts to SedaSanj.
class SendTranscriptEnabled extends AsyncNotifier<bool> {
  @override
  Future<bool> build() async {
    final db = await ref.watch(appDatabaseProvider.future);
    return await db.getSetting(kSendTranscriptSettingKey) != '0';
  }

  Future<void> set(bool enabled) async {
    final db = await ref.read(appDatabaseProvider.future);
    await db.setSetting(kSendTranscriptSettingKey, enabled ? '1' : '0');
    state = AsyncData(enabled);
  }
}

final sendTranscriptEnabledProvider =
    AsyncNotifierProvider<SendTranscriptEnabled, bool>(
      SendTranscriptEnabled.new,
    );
