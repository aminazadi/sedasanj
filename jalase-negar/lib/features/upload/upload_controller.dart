import 'dart:async';
import 'dart:math';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/platform/api_client.dart';
import '../../core/providers.dart';
import '../meetings/application/meeting_providers.dart';
import '../settings/application/connection_controller.dart';
import 'upload_queue.dart';

class UploadState {
  const UploadState({
    this.running = false,
    this.connected = false,
    this.needsReconnect = false,
    this.creditExhausted = false,
    this.lastError,
    this.tick = 0,
  });

  final bool running;
  final bool connected;
  final bool needsReconnect;
  final bool creditExhausted;
  final String? lastError;

  /// Bumped after every pass so progress providers refresh.
  final int tick;
}

/// Runs [UploadQueue] whenever something may have changed: a chunk closed,
/// the recording ended, the app started, connectivity returned, or a retry
/// delay elapsed. Passes never overlap; a kick during a pass runs one more.
class UploadController extends Notifier<UploadState> {
  Timer? _wake;
  StreamSubscription<List<ConnectivityResult>>? _connectivity;
  bool _running = false;
  bool _again = false;

  @override
  UploadState build() {
    ref.onDispose(() {
      _wake?.cancel();
      _connectivity?.cancel();
    });
    _connectivity = Connectivity().onConnectivityChanged.listen((results) {
      if (results.any((r) => r != ConnectivityResult.none)) kick();
    });
    // Resume whatever was left over from a previous run.
    Future.microtask(kick);
    return const UploadState();
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
    final connectionStore = await ref.read(connectionStoreProvider.future);
    final connection = await connectionStore.load();
    final token = await connectionStore.token();
    if (connection == null || token == null) {
      state = UploadState(tick: state.tick + 1);
      return;
    }
    final repo = await ref.read(meetingRepositoryProvider.future);
    final queue = UploadQueue(
      store: repo,
      api: ApiClient(serverUrl: connection.serverUrl, token: token),
    );
    state = UploadState(running: true, connected: true, tick: state.tick);
    UploadOutcome outcome;
    try {
      outcome = await queue.processOnce();
    } catch (e) {
      outcome = UploadOutcome(
        nextWake: const Duration(seconds: 30),
        lastError:
            'ارسال به صداسنج با خطا روبه‌رو شد؛ بعداً دوباره تلاش می‌شود.',
      );
    }
    state = UploadState(
      connected: true,
      needsReconnect: outcome.needsReconnect,
      creditExhausted: outcome.creditExhausted,
      lastError: outcome.lastError,
      tick: state.tick + 1,
    );
    ref.invalidate(meetingsProvider);
    final wake = outcome.nextWake;
    if (wake != null && !outcome.needsReconnect) {
      _wake = Timer(wake + Duration(milliseconds: Random().nextInt(500)), kick);
    }
  }
}

final uploadQueueProvider = NotifierProvider<UploadController, UploadState>(
  UploadController.new,
);

/// (sent, total) chunk counts of a meeting, refreshed after each queue pass.
final uploadProgressProvider = FutureProvider.family<(int, int), String>((
  ref,
  meetingId,
) async {
  ref.watch(uploadQueueProvider.select((s) => s.tick));
  final repo = await ref.watch(meetingRepositoryProvider.future);
  return repo.chunkCounts(meetingId);
});
