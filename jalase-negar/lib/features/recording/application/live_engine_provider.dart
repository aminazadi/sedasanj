import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/asr/live_asr_engine.dart';
import '../../../core/asr/vad_segment_engine.dart';
import '../../../core/models/model_catalog.dart';
import '../../../core/db/app_database.dart';
import '../../../core/models/model_spec.dart';
import '../../../core/models/model_store.dart';
import '../../../core/platform/cpu_budget.dart';
import '../../../core/providers.dart';
import '../../models/application/models_controller.dart';
import '../../people/application/people_providers.dart';

/// Retired settings key. Live transcription is always on; an old value of 0
/// left by the removed switch is ignored (and cleared when a recording starts).
const String kLiveTranscriptSettingKey = 'live_transcript_enabled';

/// Settings key of the switch that sends each meeting's transcript to
/// SedaSanj. Absent means on; audio is never sent either way.
const String kSendTranscriptSettingKey = 'send_transcript_enabled';

/// Settings key: name the speakers in the live transcript (absent means on
/// whenever people are enrolled and the speaker model is installed).
const String kSpeakerIdSettingKey = 'speaker_id_enabled';

/// Settings key: write laughter, crying, coughs and similar sounds into the
/// transcript between square brackets (absent means on whenever the sound
/// model is installed).
const String kSoundEventsSettingKey = 'sound_events_enabled';

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

/// [attendeeIds] are the people chosen as present; their voices get a small
/// head start in speaker matching (others stay possible matches).
typedef LiveEngineBuilder =
    Future<LiveEngineSetup> Function({Set<String> attendeeIds});

/// Builds the engine for a new recording. Overridden in tests with a fake.
final liveEngineBuilderProvider = Provider<LiveEngineBuilder>((ref) {
  return ({Set<String> attendeeIds = const {}}) async {
    final db = await ref.read(appDatabaseProvider.future);
    // Live text is always on. A stale 0 from the removed switch must not
    // silently disable it, so it is cleared.
    try {
      if (await db.getSetting(kLiveTranscriptSettingKey) == '0') {
        await db.setSetting(kLiveTranscriptSettingKey, '1');
      }
    } catch (_) {}
    final store = await ref.read(modelStoreProvider.future);
    final asrId = await db.getSetting(kAsrModelSettingKey);
    if (asrId != ModelCatalog.shenavaKoochikRnnt.id) {
      return const LiveEngineSetup.unavailable(
        'برای متن زنده، ابتدا از بخش «مدل‌ها» گزینهٔ دانلود، نصب و فعال‌سازی را بزنید.',
      );
    }
    const asrSpec = ModelCatalog.shenavaKoochikRnnt;
    final vadSpec = ModelCatalog.sileroVad;
    if (!await store.isInstalled(asrSpec) ||
        !await store.isInstalled(vadSpec)) {
      return const LiveEngineSetup.unavailable(
        'برای متن زنده، مدل شنوا و مدل تشخیص گفتار (VAD) باید کامل نصب باشند؛ به بخش «مدل‌ها» بروید.',
      );
    }
    final transducer = asrSpec.asrArchitecture == AsrArchitecture.transducer;
    final speakers = await _speakerSetup(ref, db, store, attendeeIds);
    final sounds = await _soundEventSetup(db, store);
    final budget = await ref.read(cpuBudgetProvider.future);
    final engine = VadSegmentEngine(
      VadSegmentConfig(
        numThreads: budget.recognitionThreads,
        minSilenceSeconds: kLiveMinSilenceSeconds,
        speakerThreads: budget.liveSpeakerThreads,
        soundEventThreads: budget.soundEventThreads,
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
        speakerEmbeddingPath: speakers.embeddingPath,
        speakerSegmentationPath: speakers.segmentationPath,
        enrolled: speakers.enrolled,
        soundEventModelPath: sounds.modelPath,
        soundEventLabelsPath: sounds.labelsPath,
      ),
    );
    return LiveEngineSetup.ready(engine: engine, modelId: asrSpec.id);
  };
});

class _SoundEventSetup {
  const _SoundEventSetup({this.modelPath = '', this.labelsPath = ''});

  final String modelPath;
  final String labelsPath;
}

/// Files of the sound-event model, or nothing when the switch is off or the
/// model is not installed. Never throws.
Future<_SoundEventSetup> _soundEventSetup(
  AppDatabase db,
  ModelStore store,
) async {
  try {
    if (await db.getSetting(kSoundEventsSettingKey) == '0') {
      return const _SoundEventSetup();
    }
    const spec = ModelCatalog.soundEvents;
    if (!await store.isInstalled(spec)) return const _SoundEventSetup();
    return _SoundEventSetup(
      modelPath: store.filePath(spec, spec.files[0]),
      labelsPath: store.filePath(spec, spec.files[1]),
    );
  } catch (_) {
    return const _SoundEventSetup();
  }
}

class _SpeakerSetup {
  const _SpeakerSetup({
    this.embeddingPath = '',
    this.segmentationPath = '',
    this.enrolled = const [],
  });

  final String embeddingPath;
  final String segmentationPath;
  final List<Map<String, Object?>> enrolled;
}

/// Models and enrolled people for naming speakers, or nothing when the switch
/// is off, no model is installed or nobody is enrolled for it. Never throws:
/// a recording must start without names rather than not at all.
Future<_SpeakerSetup> _speakerSetup(
  Ref ref,
  AppDatabase db,
  ModelStore store,
  Set<String> attendeeIds,
) async {
  try {
    if (await db.getSetting(kSpeakerIdSettingKey) == '0') {
      return const _SpeakerSetup();
    }
    const embedding = ModelCatalog.speakerEmbedding;
    if (!await store.isInstalled(embedding)) return const _SpeakerSetup();
    final people = await ref.read(peopleRepositoryProvider.future);
    final voices = await people.enrolledVoices(
      modelId: embedding.id,
      modelVersion: ModelCatalog.speakerEmbeddingVersion,
    );
    if (voices.isEmpty) return const _SpeakerSetup();
    const segmentation = ModelCatalog.speakerSegmentation;
    return _SpeakerSetup(
      embeddingPath: store.filePath(embedding, embedding.files[0]),
      segmentationPath: await store.isInstalled(segmentation)
          ? store.filePath(segmentation, segmentation.files[0])
          : '',
      enrolled: [
        for (final v in voices)
          v.asPreferred(attendeeIds.contains(v.personId)).toMap(),
      ],
    );
  } catch (_) {
    return const _SpeakerSetup();
  }
}

/// The user's choice to name speakers in live transcripts.
class SpeakerIdEnabled extends AsyncNotifier<bool> {
  @override
  Future<bool> build() async {
    final db = await ref.watch(appDatabaseProvider.future);
    return await db.getSetting(kSpeakerIdSettingKey) != '0';
  }

  Future<void> set(bool enabled) async {
    final db = await ref.read(appDatabaseProvider.future);
    await db.setSetting(kSpeakerIdSettingKey, enabled ? '1' : '0');
    state = AsyncData(enabled);
  }
}

final speakerIdEnabledProvider = AsyncNotifierProvider<SpeakerIdEnabled, bool>(
  SpeakerIdEnabled.new,
);

/// The user's choice to write sounds like laughter and crying into the text.
class SoundEventsEnabled extends AsyncNotifier<bool> {
  @override
  Future<bool> build() async {
    final db = await ref.watch(appDatabaseProvider.future);
    return await db.getSetting(kSoundEventsSettingKey) != '0';
  }

  Future<void> set(bool enabled) async {
    final db = await ref.read(appDatabaseProvider.future);
    await db.setSetting(kSoundEventsSettingKey, enabled ? '1' : '0');
    state = AsyncData(enabled);
  }
}

final soundEventsEnabledProvider =
    AsyncNotifierProvider<SoundEventsEnabled, bool>(SoundEventsEnabled.new);

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
