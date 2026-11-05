import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers.dart';
import '../../meetings/application/meeting_providers.dart';
import '../../meetings/data/meeting_repository.dart';
import '../../recording/application/recorder_controller.dart';
import '../../settings/application/connection_controller.dart';
import '../../upload/upload_controller.dart';
import '../data/update_native.dart';

final updateNativeProvider = Provider<UpdateNative>(
  (ref) => const UpdateNative(),
);

/// Keeps the native self-updater informed about the "calm moment" inputs the
/// Dart side owns (recording, unsent uploads, transcript edits waiting to
/// sync). The worker alone decides about battery, storage and foreground.
///
/// Publishing is cheap (a few preference writes) and runs only when one of the
/// inputs actually changed.
class UpdateCalmPublisher extends Notifier<void> {
  Timer? _debounce;
  ({bool recording, int chunks, int text})? _last;

  @override
  void build() {
    ref.onDispose(() => _debounce?.cancel());
    ref.listen(
      recorderControllerProvider.select((s) => s.status),
      (_, _) => _schedule(),
    );
    ref.listen(
      uploadQueueProvider.select((s) => s.tick),
      (_, _) => _schedule(),
    );
    ref.listen(meetingsProvider, (_, _) => _schedule());
    _schedule();
  }

  void _schedule() {
    _debounce?.cancel();
    _debounce = Timer(const Duration(seconds: 2), () => unawaited(publish()));
  }

  /// Publishes now when the inputs changed since the last publication.
  Future<void> publish() async {
    final recording = ref.read(recorderControllerProvider.notifier).isCapturing;
    var chunks = 0;
    var text = 0;
    try {
      final repo = await ref.read(meetingRepositoryProvider.future);
      final connected =
          ref.read(connectionControllerProvider).value?.connection != null;
      final backlog = await _backlog(repo);
      // Without a connection the queue cannot send anything; do not let an
      // unsent backlog block updates forever.
      chunks = connected ? backlog.pendingChunks : 0;
      text = connected ? backlog.textSyncPending : 0;
    } catch (_) {
      // Unknown means not calm: report a backlog so nothing installs blindly.
      chunks = 1;
    }
    final now = (recording: recording, chunks: chunks, text: text);
    if (_last == now) return;
    _last = now;
    await ref
        .read(updateNativeProvider)
        .publishCalmState(
          recording: recording,
          pendingChunks: chunks,
          textSyncPending: text,
        );
  }

  Future<({int pendingChunks, int textSyncPending})> _backlog(
    MeetingRepository repo,
  ) => repo.updateBacklog();
}

final updateCalmPublisherProvider = NotifierProvider<UpdateCalmPublisher, void>(
  UpdateCalmPublisher.new,
);
