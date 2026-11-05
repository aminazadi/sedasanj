import 'dart:async';
import 'dart:math';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/models/model_catalog.dart';
import '../../../core/platform/api_client.dart';
import '../../../core/platform/speaker_api.dart';
import '../../../core/providers.dart';
import '../../models/application/models_controller.dart';
import '../../settings/application/connection_controller.dart';
import '../data/embedding_cipher.dart';
import '../data/enrollment_session.dart';
import '../data/people_repository.dart';
import '../data/person.dart';
import '../sync/sync_engine.dart';

/// Replaced in tests with a fixed-key cipher.
final embeddingCipherProvider = FutureProvider<EmbeddingCipher>(
  (ref) => loadDeviceEmbeddingCipher(),
);

final peopleRepositoryProvider = FutureProvider<PeopleRepository>((ref) async {
  final db = await ref.watch(appDatabaseProvider.future);
  final cipher = await ref.watch(embeddingCipherProvider.future);
  return PeopleRepository(db, cipher);
});

/// The people list, reloaded after local changes and sync passes.
final peopleProvider = FutureProvider<List<Person>>((ref) async {
  ref.watch(speakerSyncProvider.select((s) => s.tick));
  final repo = await ref.watch(peopleRepositoryProvider.future);
  return repo.people();
});

class SpeakerSyncState {
  const SpeakerSyncState({
    this.running = false,
    this.connected = false,
    this.needsReconnect = false,
    this.lastError,
    this.lastSyncAt,
    this.pending = 0,
    this.tick = 0,
  });

  final bool running;
  final bool connected;
  final bool needsReconnect;
  final String? lastError;
  final DateTime? lastSyncAt;

  /// People with a change that has not reached SedaSanj yet.
  final int pending;

  /// Bumped after every pass and local change so lists refresh.
  final int tick;

  SpeakerSyncState copyWith({int? tick, int? pending}) => SpeakerSyncState(
    running: running,
    connected: connected,
    needsReconnect: needsReconnect,
    lastError: lastError,
    lastSyncAt: lastSyncAt,
    pending: pending ?? this.pending,
    tick: tick ?? this.tick,
  );
}

/// How often a quiet app still checks for people changed on another phone.
const Duration kSpeakerSyncInterval = Duration(minutes: 15);

/// Runs [SyncEngine] whenever something may have changed: the app started,
/// connectivity returned, the phone was just paired (a new phone gets everyone
/// back at once), a person was changed locally, or a retry delay elapsed.
/// Passes never overlap; a kick during a pass runs one more.
class SpeakerSyncController extends Notifier<SpeakerSyncState> {
  Timer? _wake;
  Timer? _periodic;
  StreamSubscription<List<ConnectivityResult>>? _connectivity;
  bool _running = false;
  bool _again = false;

  /// Test hook: builds the API for a connection.
  static SpeakerSyncApi Function(String serverUrl, String token)? apiFactory;

  @override
  SpeakerSyncState build() {
    ref.onDispose(() {
      _wake?.cancel();
      _periodic?.cancel();
      _connectivity?.cancel();
    });
    _connectivity = Connectivity().onConnectivityChanged.listen((results) {
      if (results.any((r) => r != ConnectivityResult.none)) kick();
    });
    _periodic = Timer.periodic(kSpeakerSyncInterval, (_) => kick());
    // Pairing completed (or the account changed): sync from the stored cursor.
    ref.listen(
      connectionControllerProvider.select((a) => a.value?.connection),
      (previous, next) {
        if (next != null && next != previous) kick();
      },
    );
    Future.microtask(kick);
    return const SpeakerSyncState();
  }

  /// Marks a local change and starts a pass (immediately when online).
  void localChanged() {
    state = state.copyWith(tick: state.tick + 1);
    kick();
  }

  Future<void> kick() async {
    if (_running) {
      _again = true;
      return;
    }
    _running = true;
    try {
      do {
        _again = false;
        await _pass();
      } while (_again);
    } finally {
      _running = false;
    }
  }

  Future<void> _pass() async {
    _wake?.cancel();
    final repo = await ref.read(peopleRepositoryProvider.future);
    final store = await ref.read(connectionStoreProvider.future);
    final connection = await store.load();
    final token = await store.token();
    final pending = await repo.pendingCount();
    if (connection == null || token == null) {
      state = SpeakerSyncState(pending: pending, tick: state.tick + 1);
      return;
    }
    await repo.bindToAccount(
      '${connection.serverUrl}|${connection.tenantName}|${connection.userName}',
    );
    state = SpeakerSyncState(
      running: true,
      connected: true,
      pending: pending,
      lastSyncAt: state.lastSyncAt,
      tick: state.tick,
    );
    final factory = apiFactory;
    final api =
        factory?.call(connection.serverUrl, token) ??
        ApiClient(serverUrl: connection.serverUrl, token: token);
    SyncOutcome outcome;
    try {
      outcome = await SyncEngine(repository: repo, api: api).syncOnce();
    } catch (_) {
      outcome = const SyncOutcome(
        nextWake: Duration(seconds: 30),
        lastError:
            'همگام‌سازی افراد با خطا روبه‌رو شد؛ بعداً دوباره تلاش می‌شود.',
      );
    }
    state = SpeakerSyncState(
      connected: true,
      needsReconnect: outcome.needsReconnect,
      lastError: outcome.lastError,
      lastSyncAt: await repo.lastSyncAt(),
      pending: await repo.pendingCount(),
      tick: state.tick + 1,
    );
    final wake = outcome.nextWake;
    if (wake != null && !outcome.needsReconnect) {
      _wake = Timer(wake + Duration(milliseconds: Random().nextInt(500)), kick);
    }
  }
}

final speakerSyncProvider =
    NotifierProvider<SpeakerSyncController, SpeakerSyncState>(
      SpeakerSyncController.new,
    );

/// The texts to read when enrolling a voice.
final speakerPromptsProvider = FutureProvider<SpeakerPrompts>((ref) async {
  return SpeakerPrompts.parse(
    await rootBundle.loadString('assets/speaker_prompts_fa.json'),
  );
});

typedef EnrollmentRecorderFactory = EnrollmentRecorder Function();

/// Overridden in tests with a scripted recorder.
final enrollmentRecorderFactoryProvider = Provider<EnrollmentRecorderFactory>(
  (ref) => MicEnrollmentRecorder.new,
);

/// The embedding service, or null while the speaker model is not installed.
final voiceEmbeddingServiceProvider = FutureProvider<VoiceEmbeddingService?>((
  ref,
) async {
  final store = await ref.watch(modelStoreProvider.future);
  const spec = ModelCatalog.speakerEmbedding;
  if (!await store.isInstalled(spec)) return null;
  return SherpaEmbeddingService(
    modelPath: store.filePath(spec, spec.files[0]),
    modelId: spec.id,
    modelVersion: ModelCatalog.speakerEmbeddingVersion,
  );
});

/// Whether the speaker embedding model is on the phone (re-checked when the
/// models screen changes anything).
final speakerModelInstalledProvider = FutureProvider<bool>((ref) async {
  ref.watch(modelsControllerProvider);
  final store = await ref.watch(modelStoreProvider.future);
  return store.isInstalled(ModelCatalog.speakerEmbedding);
});

/// Changes to people from the screens: each also queues sync and refreshes
/// the lists.
class PeopleActions {
  PeopleActions(this.ref);

  final Ref ref;

  Future<PeopleRepository> get _repo =>
      ref.read(peopleRepositoryProvider.future);

  void _changed() {
    ref.invalidate(peopleProvider);
    ref.read(speakerSyncProvider.notifier).localChanged();
  }

  /// Creates a person after the consent screen was accepted.
  Future<Person> create({
    required String name,
    required PersonVisibility visibility,
  }) async {
    final person = await (await _repo).create(
      name: name,
      visibility: visibility,
      consentAt: DateTime.now(),
      consentVersion: kSpeakerConsentVersion,
    );
    _changed();
    return person;
  }

  Future<void> update(
    String id, {
    String? name,
    PersonVisibility? visibility,
  }) async {
    await (await _repo).update(id, name: name, visibility: visibility);
    _changed();
  }

  Future<void> removeVoiceprint(String personId, String voiceprintId) async {
    await (await _repo).removeVoiceprint(personId, voiceprintId);
    _changed();
  }

  Future<void> delete(String id) async {
    await (await _repo).delete(id);
    _changed();
  }

  /// Called after enrolment stored samples.
  void samplesAdded() => _changed();
}

final peopleActionsProvider = Provider<PeopleActions>(PeopleActions.new);
