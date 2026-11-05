import 'dart:math';

import '../../../core/platform/api_client.dart';
import '../../../core/platform/speaker_api.dart';
import '../../upload/upload_queue.dart' show uploadBackoff;
import '../data/people_repository.dart';

/// What one sync pass learned; the controller turns it into UI state and the
/// next wake-up.
class SyncOutcome {
  const SyncOutcome({
    this.pushed = 0,
    this.pulled = 0,
    this.needsReconnect = false,
    this.nextWake,
    this.lastError,
  });

  final int pushed;
  final int pulled;
  final bool needsReconnect;
  final Duration? nextWake;
  final String? lastError;

  bool get ok => lastError == null && !needsReconnect;
}

/// Offline-first sync of people and voiceprints with SedaSanj.
///
/// Push first (so a local edit is never overwritten by an older server copy),
/// then pull everything after the stored cursor. Every step is driven by the
/// database (outbox rows, cursor), so a killed app or a lost connection simply
/// resumes on the next pass. Failures back off exponentially with jitter, like
/// the upload queue.
class SyncEngine {
  SyncEngine({
    required this.repository,
    required this.api,
    this.pageSize = 200,
    this.maxConflictRetries = 3,
    Random? random,
    DateTime Function()? now,
  }) : _random = random ?? Random(),
       _now = now ?? DateTime.now;

  final PeopleRepository repository;
  final SpeakerSyncApi api;
  final int pageSize;
  final int maxConflictRetries;
  final Random _random;
  final DateTime Function() _now;

  Future<SyncOutcome> syncOnce() async {
    var pushed = 0;
    var pulled = 0;
    Duration? wake;
    String? lastError;

    void wakeIn(Duration d) {
      if (wake == null || d < wake!) wake = d;
    }

    try {
      final nowMs = _now().millisecondsSinceEpoch;
      for (final entry in await repository.outbox()) {
        final due = entry.nextAttemptAt ?? 0;
        if (due > nowMs) {
          wakeIn(Duration(milliseconds: due - nowMs));
          continue;
        }
        try {
          if (await _push(entry)) pushed++;
        } on ApiException catch (e) {
          if (e.requiresReconnect) rethrow;
          lastError = e.message;
          if (e.retryable) {
            final delay = uploadBackoff(entry.attempts + 1, _random);
            await repository.markPushFailed(
              entry,
              nextAttemptAt: _now().add(delay).millisecondsSinceEpoch,
              code: e.code ?? 'http_${e.statusCode ?? 'network'}',
            );
            wakeIn(delay);
          } else {
            // The server refused this person for good (limit, invalid
            // sample): keep the entry visible but stop hammering it. A new
            // local edit resets it.
            await repository.markPushFailed(
              entry,
              nextAttemptAt: _now()
                  .add(const Duration(hours: 6))
                  .millisecondsSinceEpoch,
              code: e.code ?? 'http_${e.statusCode}',
            );
            wakeIn(const Duration(hours: 6));
          }
        }
      }
      pulled = await _pull();
      await repository.setLastSyncAt(_now());
    } on ApiException catch (e) {
      if (e.requiresReconnect) {
        return SyncOutcome(
          pushed: pushed,
          pulled: pulled,
          needsReconnect: true,
          lastError: e.message,
        );
      }
      lastError = e.message;
      wakeIn(
        e.retryable ? uploadBackoff(1, _random) : const Duration(minutes: 30),
      );
    }
    return SyncOutcome(
      pushed: pushed,
      pulled: pulled,
      nextWake: wake,
      lastError: lastError,
    );
  }

  /// Sends one outbox entry. Returns whether the server took it.
  Future<bool> _push(OutboxEntry entry) async {
    if (entry.isDelete) {
      try {
        await api.deleteProfile(entry.entityId);
      } on ApiException catch (e) {
        // Already gone on the server counts as deleted.
        if (e.code != 'speaker_profile_not_found') rethrow;
      }
      await repository.completeDelete(entry);
      return true;
    }
    var current = entry;
    for (var attempt = 0; attempt <= maxConflictRetries; attempt++) {
      final request = await repository.buildPut(current);
      if (request == null) {
        // Deleted locally after being queued.
        await repository.completeDelete(current);
        return false;
      }
      try {
        final profile = await api.putProfile(current.entityId, request);
        await repository.completePush(current, profile);
        return true;
      } on ApiException catch (e) {
        if (e.code == 'speaker_profile_not_found') {
          // Deleted on another phone: delete beats edit.
          await repository.dropPerson(current.entityId);
          return false;
        }
        if (e.code != 'speaker_profile_conflict') rethrow;
        final raw = e.details['current'];
        if (raw is! Map || attempt == maxConflictRetries) rethrow;
        await repository.rebaseOnServer(
          current,
          RemoteProfile.fromJson(Map<String, dynamic>.from(raw)),
        );
        final fresh = await repository.outbox();
        final again = fresh.where((x) => x.entityId == current.entityId);
        if (again.isEmpty) return false;
        current = again.first;
      }
    }
    return false;
  }

  Future<int> _pull() async {
    var cursor = await repository.cursor();
    var applied = 0;
    while (true) {
      final page = await api.changes(cursor: cursor, limit: pageSize);
      for (final item in page.items) {
        await repository.applyRemote(item);
        applied++;
      }
      // Advance only after the page is stored, so a crash replays it.
      if (page.nextCursor > cursor) {
        cursor = page.nextCursor;
        await repository.setCursor(cursor);
      }
      if (!page.hasMore || page.nextCursor <= cursor && page.items.isEmpty) {
        break;
      }
    }
    return applied;
  }
}
