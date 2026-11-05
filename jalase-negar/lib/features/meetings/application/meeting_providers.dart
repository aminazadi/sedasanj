import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../../../core/models/model_catalog.dart';
import '../../../core/providers.dart';
import '../../../core/platform/api_client.dart';
import '../../people/application/people_providers.dart';
import '../data/precise_labels.dart';
import '../data/precise_processor.dart';
import '../../settings/application/connection_controller.dart';
import '../../upload/upload_controller.dart';
import '../data/meeting_repository.dart';
import '../data/meeting.dart';
import '../data/speaker_discovery.dart' as discovery;
import '../data/speaker_edit.dart';
import '../../people/data/person.dart';
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

/// Runs the whole-recording speaker analysis. Overridden in tests.
final preciseRunnerProvider = Provider<PreciseRunner>(
  (ref) => runPreciseInIsolate,
);

/// Builds voiceprints from a meeting's audio. Overridden in tests.
final voiceprintExtractorProvider = Provider<VoiceprintExtractor>(
  (ref) => extractVoiceprintsInIsolate,
);

enum NameSpeakerStatus {
  /// A person was created (or found) and the lines were given to them.
  done,

  /// The speaker model is not installed.
  needsModels,

  /// Too little clean speech from this voice to make a voiceprint.
  tooShort,

  /// The recording is still being recorded or uploaded.
  busy,

  /// Nothing was changed.
  failed,
}

enum PreciseStatus {
  /// Speakers were re-labelled.
  done,

  /// The embedding or segmentation model is not installed.
  needsModels,

  /// The recording is longer than the precise pass can hold in memory.
  tooLong,

  /// The meeting cannot be processed right now (recording, uploading).
  busy,

  /// The analysis failed; nothing was changed.
  failed,
}

class PreciseOutcome {
  const PreciseOutcome(this.status, {this.changedLines = 0});

  final PreciseStatus status;

  /// Lines whose speaker changed.
  final int changedLines;
}

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
    return _storeSegments(repo, meeting, edited, settle: settle);
  }

  /// Stores segments changed outside the text editor (speakers chosen by
  /// hand, a line split between two speakers). Like a text edit, it is sent to
  /// SedaSanj when the text was already there.
  Future<TranscriptSave> saveSegments(
    List<Segment> segments, {
    bool settle = true,
  }) async {
    final repo = await ref.read(meetingRepositoryProvider.future);
    final meeting = await repo.byId(meetingId);
    if (meeting == null || meeting.status == MeetingStatus.uploading) {
      return const TranscriptSave(TranscriptSaveResult.failed);
    }
    return _storeSegments(repo, meeting, segments, settle: settle);
  }

  Future<TranscriptSave> _storeSegments(
    MeetingRepository repo,
    Meeting meeting,
    List<Segment> edited, {
    required bool settle,
  }) async {
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

  /// Layer B: analyses the whole recording, then re-labels the speakers of
  /// every line the user did not label by hand. Text and times are untouched.
  Future<PreciseOutcome> runPreciseProcessing() async {
    final repo = await ref.read(meetingRepositoryProvider.future);
    final meeting = await repo.byId(meetingId);
    if (meeting == null ||
        meeting.status == MeetingStatus.recording ||
        meeting.status == MeetingStatus.uploading) {
      return const PreciseOutcome(PreciseStatus.busy);
    }
    final store = await ref.read(modelStoreProvider.future);
    const embedding = ModelCatalog.speakerEmbedding;
    const segmentation = ModelCatalog.speakerSegmentation;
    if (!await store.isInstalled(embedding) ||
        !await store.isInstalled(segmentation)) {
      return const PreciseOutcome(PreciseStatus.needsModels);
    }
    if (meeting.duration > kPreciseMaxDuration) {
      return const PreciseOutcome(PreciseStatus.tooLong);
    }
    final people = await ref.read(peopleRepositoryProvider.future);
    final voices = await people.enrolledVoices(
      modelId: embedding.id,
      modelVersion: ModelCatalog.speakerEmbeddingVersion,
    );
    final PreciseAnalysis analysis;
    try {
      analysis = await ref.read(preciseRunnerProvider)(
        PreciseRequest(
          wavPath: meeting.audioPath,
          segmentationModelPath: store.filePath(
            segmentation,
            segmentation.files[0],
          ),
          embeddingModelPath: store.filePath(embedding, embedding.files[0]),
          enrolled: [for (final v in voices) v.toMap()],
        ),
      );
    } on FormatException catch (e) {
      return PreciseOutcome(
        e.message == 'recording_too_long'
            ? PreciseStatus.tooLong
            : PreciseStatus.failed,
      );
    } catch (_) {
      return const PreciseOutcome(PreciseStatus.failed);
    }
    // Read the lines only now: the user may have edited while it ran.
    final current = await repo.segments(meetingId);
    final relabelled = applyPreciseLabels(current, analysis);
    var changed = 0;
    for (var i = 0; i < current.length; i++) {
      if (current[i].labeledText != relabelled[i].labeledText ||
          current[i].overlap != relabelled[i].overlap) {
        changed++;
      }
    }
    await saveSegments(relabelled);
    return PreciseOutcome(PreciseStatus.done, changedLines: changed);
  }

  /// Turns an unnamed voice of this meeting into a person: its clean speech
  /// becomes the voiceprints, and every line of that voice gets the name.
  /// [consentGiven] must be true: the person agreed to their voice being kept.
  Future<NameSpeakerStatus> nameDetectedSpeaker({
    required String label,
    required String name,
    required PersonVisibility visibility,
    required bool consentGiven,
  }) async {
    final cleanName = name.trim();
    if (!consentGiven || cleanName.isEmpty) return NameSpeakerStatus.failed;
    final repo = await ref.read(meetingRepositoryProvider.future);
    final meeting = await repo.byId(meetingId);
    if (meeting == null ||
        meeting.status == MeetingStatus.recording ||
        meeting.status == MeetingStatus.uploading) {
      return NameSpeakerStatus.busy;
    }
    final store = await ref.read(modelStoreProvider.future);
    const embedding = ModelCatalog.speakerEmbedding;
    if (!await store.isInstalled(embedding)) {
      return NameSpeakerStatus.needsModels;
    }
    final segments = await repo.segments(meetingId);
    final groups = discovery.voiceprintGroups(segments, label);
    if (groups.isEmpty) return NameSpeakerStatus.tooShort;
    final List<ExtractedVoiceprint> samples;
    try {
      samples = await ref.read(voiceprintExtractorProvider)(
        VoiceprintRequest(
          wavPath: meeting.audioPath,
          embeddingModelPath: store.filePath(embedding, embedding.files[0]),
          groups: groups,
        ),
      );
    } catch (_) {
      return NameSpeakerStatus.failed;
    }
    if (samples.isEmpty) return NameSpeakerStatus.tooShort;
    final people = await ref.read(peopleRepositoryProvider.future);
    final person = await people.create(
      name: cleanName,
      visibility: visibility,
      consentAt: DateTime.now(),
      consentVersion: kSpeakerConsentVersion,
    );
    const uuid = Uuid();
    await people.addVoiceprints(person.clientId, [
      for (final sample in samples)
        Voiceprint(
          clientId: uuid.v4(),
          personId: person.clientId,
          modelId: embedding.id,
          modelVersion: ModelCatalog.speakerEmbeddingVersion,
          embedding: sample.embedding,
          createdAt: DateTime.now(),
          durationMs: sample.durationMs,
        ),
    ]);
    ref.read(peopleActionsProvider).samplesAdded();
    // Read the lines only now: the user may have edited while this ran.
    final current = await repo.segments(meetingId);
    await saveSegments(
      discovery.nameDetectedSpeaker(
        current,
        label,
        SpeakerChoice(name: person.name, personId: person.clientId),
      ),
    );
    return NameSpeakerStatus.done;
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
