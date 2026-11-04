import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers.dart';
import '../../../core/platform/api_client.dart';
import '../../settings/application/connection_controller.dart';
import '../../upload/upload_controller.dart';
import '../data/meeting_repository.dart';
import '../data/meeting.dart';
import '../data/transcript_edit.dart';

/// Whether SedaSanj already holds this meeting's text (so an edit must be
/// sent there too). A text being uploaded right now is not editable at all.
bool isTextSentToServer(Meeting meeting) =>
    meeting.remoteMeetingId != null &&
    (meeting.status == MeetingStatus.processing ||
        meeting.status == MeetingStatus.uploaded ||
        meeting.status == MeetingStatus.complete);

enum TranscriptSaveResult {
  /// Stored on the phone; SedaSanj has no copy to update.
  saved,

  /// Stored on the phone and sent to SedaSanj.
  synced,

  /// Stored on the phone; sending to SedaSanj failed and can be retried.
  savedOnDevice,

  /// Nothing was stored.
  failed,
}

class TranscriptSave {
  const TranscriptSave(this.result, [this.problem]);

  final TranscriptSaveResult result;

  /// Why sending failed, as text for the user.
  final String? problem;

  bool get stored => result != TranscriptSaveResult.failed;
}

/// The server connection used to send an edited text; null when the app is
/// not paired. Overridden in tests.
final textSyncApiProvider = FutureProvider<MeetingUploadApi?>((ref) async {
  final store = await ref.watch(connectionStoreProvider.future);
  final connection = await store.load();
  final token = await store.token();
  if (connection == null || token == null) return null;
  return ApiClient(serverUrl: connection.serverUrl, token: token);
});

class MeetingActions {
  MeetingActions(this.ref, this.meetingId);

  final Ref ref;
  final String meetingId;

  Future<void> renameMeeting(String title) async {
    final trimmed = title.trim();
    if (trimmed.isEmpty) return;
    final repo = await ref.read(meetingRepositoryProvider.future);
    final meeting = await repo.byId(meetingId);
    if (meeting == null) return;
    await repo.update(meeting.copyWith(title: trimmed, error: meeting.error));
    ref.invalidate(meetingsProvider);
    ref.invalidate(meetingDetailProvider(meetingId));
  }

  /// Sends this meeting's transcript now (works even when the settings
  /// switch was off while it was recorded).
  Future<void> sendText() async {
    final repo = await ref.read(meetingRepositoryProvider.future);
    await repo.requestSend(meetingId);
    ref.invalidate(meetingsProvider);
    ref.invalidate(meetingDetailProvider(meetingId));
    ref.read(uploadQueueProvider.notifier).kick();
  }

  /// Saves the edited transcript text: one segment per line, keeping the
  /// timing of the lines that were kept. When the text was already sent to
  /// SedaSanj and [settle] is set, the edit is sent too, so the panel text and
  /// minutes follow; autosaves in between only store it on the phone.
  Future<TranscriptSave> saveTranscript(
    String text, {
    bool settle = true,
  }) async {
    final repo = await ref.read(meetingRepositoryProvider.future);
    final meeting = await repo.byId(meetingId);
    if (meeting == null || meeting.status == MeetingStatus.uploading) {
      return const TranscriptSave(TranscriptSaveResult.failed);
    }
    final edited = applyTranscriptEdit(await repo.segments(meetingId), text);
    await repo.replaceSegments(meetingId, edited);
    ref.invalidate(meetingPreviewProvider(meetingId));
    var result = const TranscriptSave(TranscriptSaveResult.saved);
    if (isTextSentToServer(meeting)) {
      if (settle) {
        result = await _pushText(repo, meeting, edited);
      } else {
        // Remembered, so an edit survives the app being closed before it is sent.
        await repo.setTextSyncPending(meetingId, true);
      }
    }
    ref.invalidate(meetingsProvider);
    ref.invalidate(meetingDetailProvider(meetingId));
    return result;
  }

  /// Sends the stored text again after an edit could not reach SedaSanj.
  Future<TranscriptSave> retryTextSync() async {
    final repo = await ref.read(meetingRepositoryProvider.future);
    final meeting = await repo.byId(meetingId);
    if (meeting == null || !isTextSentToServer(meeting)) {
      return const TranscriptSave(TranscriptSaveResult.failed);
    }
    final result = await _pushText(
      repo,
      meeting,
      await repo.segments(meetingId),
    );
    ref.invalidate(meetingsProvider);
    ref.invalidate(meetingDetailProvider(meetingId));
    return result;
  }

  Future<TranscriptSave> _pushText(
    MeetingRepository repo,
    Meeting meeting,
    List<Segment> segments,
  ) async {
    final api = await ref.read(textSyncApiProvider.future);
    String? problem;
    if (api == null) {
      problem = 'اپ به صداسنج وصل نیست.';
    } else {
      try {
        await api.putTranscript(
          meetingId: meeting.remoteMeetingId!,
          segments: [
            for (final s in segments)
              if (s.text.trim().isNotEmpty) s,
          ],
          asrIdentity: meeting.asrIdentity,
        );
        // The server rebuilds the minutes; the queue follows that to the end.
        await repo.setTextSyncPending(meeting.id, false);
        await repo.setStatus(meeting.id, MeetingStatus.processing);
        ref.read(uploadQueueProvider.notifier).kick();
        return const TranscriptSave(TranscriptSaveResult.synced);
      } on ApiException catch (e) {
        problem = e.message;
      }
    }
    await repo.setTextSyncPending(meeting.id, true);
    return TranscriptSave(TranscriptSaveResult.savedOnDevice, problem);
  }

  Future<void> deleteMeeting() async {
    final repo = await ref.read(meetingRepositoryProvider.future);
    final meeting = await repo.byId(meetingId);
    if (meeting == null) return;
    final paths = await ref.read(appPathsProvider.future);
    final chunksDir = paths.meetingChunksDir(meetingId);
    if (await chunksDir.exists()) await chunksDir.delete(recursive: true);
    await repo.delete(
      meeting,
      extraFiles: [
        for (var ch = 0; ch < meeting.channels; ch++)
          paths.channelWavPath(meetingId, ch),
      ],
    );
    ref.invalidate(meetingsProvider);
    ref.invalidate(meetingDetailProvider(meetingId));
  }
}

final meetingActionsProvider = Provider.family<MeetingActions, String>(
  MeetingActions.new,
);

final meetingsProvider = FutureProvider<List<Meeting>>((ref) async {
  final repo = await ref.watch(meetingRepositoryProvider.future);
  return repo.all();
});

/// One-line transcript preview of a meeting for the list; reloads when the
/// meeting's status changes (e.g. transcription finished).
final meetingPreviewProvider = FutureProvider.family<String, String>((
  ref,
  meetingId,
) async {
  ref.watch(
    meetingsProvider.select(
      (a) => a.value?.where((m) => m.id == meetingId).firstOrNull?.status,
    ),
  );
  final repo = await ref.watch(meetingRepositoryProvider.future);
  return repo.previewText(meetingId);
});

/// Meetings swiped away in the list whose deletion is still undoable.
class PendingDeletes extends Notifier<Set<String>> {
  @override
  Set<String> build() => const {};

  void hide(String id) => state = {...state, id};

  void restore(String id) => state = {...state}..remove(id);
}

final pendingDeletesProvider = NotifierProvider<PendingDeletes, Set<String>>(
  PendingDeletes.new,
);

class MeetingDetail {
  const MeetingDetail({required this.meeting, required this.segments});

  final Meeting meeting;
  final List<Segment> segments;
}

final meetingDetailProvider = FutureProvider.family<MeetingDetail?, String>((
  ref,
  meetingId,
) async {
  final repo = await ref.watch(meetingRepositoryProvider.future);
  final meeting = await repo.byId(meetingId);
  if (meeting == null) return null;
  return MeetingDetail(
    meeting: meeting,
    segments: await repo.segments(meetingId),
  );
});
