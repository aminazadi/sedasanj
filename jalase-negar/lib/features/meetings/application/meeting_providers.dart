import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers.dart';
import '../../upload/upload_controller.dart';
import '../data/meeting.dart';

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
