import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/asr/transcriber.dart';
import '../../../core/models/model_catalog.dart';
import '../../../core/models/model_spec.dart';
import '../../../core/models/model_store.dart';
import '../../../core/providers.dart';
import '../../../core/utils/transcript_text.dart';
import '../../models/application/models_controller.dart';
import '../data/meeting.dart';
import '../data/meeting_repository.dart';

/// Local transcription state of one meeting.
class PipelineState {
  const PipelineState({
    this.transcribing = false,
    this.transcribeProgress = 0,
    this.liveTranscript = '',
    this.liveWordCount = 0,
    this.error,
  });

  final bool transcribing;
  final double transcribeProgress;

  /// Transcript emitted by ASR during the current run, before DB persistence.
  final String liveTranscript;
  final int liveWordCount;
  final String? error;

  PipelineState copyWith({
    bool? transcribing,
    double? transcribeProgress,
    String? liveTranscript,
    int? liveWordCount,
    String? error,
  }) => PipelineState(
    transcribing: transcribing ?? this.transcribing,
    transcribeProgress: transcribeProgress ?? this.transcribeProgress,
    liveTranscript: liveTranscript ?? this.liveTranscript,
    liveWordCount: liveWordCount ?? this.liveWordCount,
    error: error,
  );
}

class PipelineController extends Notifier<PipelineState> {
  PipelineController(this.meetingId);

  final String meetingId;

  @override
  PipelineState build() => const PipelineState();

  /// Missing prerequisite (Persian message) or null when ready.
  Future<String?> transcribePrerequisite() async {
    final store = await ref.read(modelStoreProvider.future);
    final db = await ref.read(appDatabaseProvider.future);
    final asrId = await db.getSetting(kAsrModelSettingKey);
    if (asrId == null || asrId.isEmpty) {
      return 'ابتدا یکی از مدل‌های شنوا را از بخش «مدل‌ها» دانلود و انتخاب کنید';
    }
    if (!await store.isInstalled(ModelCatalog.byId(asrId))) {
      return 'مدل شنوا کامل نصب نشده است؛ به بخش «مدل‌ها» بروید';
    }
    if (!await store.isInstalled(ModelCatalog.sileroVad)) {
      return 'مدل تشخیص گفتار (VAD) نصب نشده است؛ به بخش «مدل‌ها» بروید';
    }
    // Noise reduction is optional; the pipeline remains usable without it.
    return null;
  }

  Future<void> transcribeMeeting() async {
    if (state.transcribing) return;
    final repo = await ref.read(meetingRepositoryProvider.future);
    final meeting = await repo.byId(meetingId);
    if (meeting == null) return;

    final missing = await transcribePrerequisite();
    if (missing != null) {
      state = state.copyWith(error: missing);
      return;
    }
    final store = await ref.read(modelStoreProvider.future);
    final db = await ref.read(appDatabaseProvider.future);
    final asrSpec = ModelCatalog.byId(
      (await db.getSetting(kAsrModelSettingKey))!,
    );
    final vadSpec = ModelCatalog.sileroVad;
    final denoiserSpec = ModelCatalog.gtcrnDenoiser;
    final isTransducer = asrSpec.asrArchitecture == AsrArchitecture.transducer;

    state = const PipelineState(transcribing: true);
    await repo.update(meeting.copyWith(status: MeetingStatus.transcribing));
    ref.invalidate(meetingsProvider);

    await _runLocalTranscription(
      repo: repo,
      meeting: meeting,
      store: store,
      asrSpec: asrSpec,
      vadSpec: vadSpec,
      denoiserSpec: denoiserSpec,
      isTransducer: isTransducer,
    );
    ref.invalidate(meetingsProvider);
    ref.invalidate(meetingDetailProvider(meetingId));
  }

  Future<void> _runLocalTranscription({
    required MeetingRepository repo,
    required Meeting meeting,
    required ModelStore store,
    required ModelSpec asrSpec,
    required ModelSpec vadSpec,
    required ModelSpec denoiserSpec,
    required bool isTransducer,
  }) async {
    final segments = <Segment>[];
    try {
      await for (final event in transcribe(
        TranscribeRequest(
          wavPath: meeting.audioPath,
          asrModelPath: isTransducer
              ? ''
              : store.filePath(asrSpec, asrSpec.files[0]),
          tokensPath: store.filePath(
            asrSpec,
            asrSpec.files[isTransducer ? 3 : 1],
          ),
          vadModelPath: store.filePath(vadSpec, vadSpec.files[0]),
          denoiserModelPath: await store.isInstalled(denoiserSpec)
              ? store.filePath(denoiserSpec, denoiserSpec.files[0])
              : null,
          architecture: asrSpec.asrArchitecture,
          encoderPath: isTransducer
              ? store.filePath(asrSpec, asrSpec.files[0])
              : null,
          decoderPath: isTransducer
              ? store.filePath(asrSpec, asrSpec.files[1])
              : null,
          joinerPath: isTransducer
              ? store.filePath(asrSpec, asrSpec.files[2])
              : null,
        ),
      )) {
        switch (event) {
          case TranscriptSegment segment:
            segments.add(
              Segment(
                channel: segment.channel,
                startMs: segment.startMs,
                endMs: segment.endMs,
                text: segment.text,
              ),
            );
            final liveTranscript = segments
                .map((item) => item.text.trim())
                .where((text) => text.isNotEmpty)
                .join('\n');
            state = state.copyWith(
              liveTranscript: liveTranscript,
              liveWordCount: RegExp(r'\S+').allMatches(liveTranscript).length,
            );
          case TranscribeProgress progress:
            state = state.copyWith(transcribeProgress: progress.fraction);
        }
      }
      await repo.replaceSegments(meetingId, segments);
      if (segments.isEmpty) {
        const noSpeechError =
            'شنوا گفتاری تشخیص نداد. اگر از شنیده شدن صدا مطمئن هستید، دوباره تلاش کنید یا از میکروفون دیگری استفاده کنید.';
        await repo.update(
          meeting.copyWith(status: MeetingStatus.failed, error: noSpeechError),
        );
        state = state.copyWith(
          transcribing: false,
          transcribeProgress: 1,
          error: noSpeechError,
        );
      } else {
        final finalTranscript = buildTranscriptText(
          segments
              .map(
                (segment) => (
                  channel: segment.channel,
                  startMs: segment.startMs,
                  text: segment.text,
                ),
              )
              .toList(),
          channelCount: meeting.channels,
        );
        await repo.update(meeting.copyWith(status: MeetingStatus.transcribed));
        state = state.copyWith(
          transcribing: false,
          transcribeProgress: 1,
          liveTranscript: finalTranscript,
          liveWordCount: RegExp(r'\S+').allMatches(finalTranscript).length,
        );
      }
    } catch (e) {
      await repo.update(
        meeting.copyWith(status: MeetingStatus.failed, error: e.toString()),
      );
      state = state.copyWith(transcribing: false, error: e.toString());
    }
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

final pipelineControllerProvider =
    NotifierProvider.family<PipelineController, PipelineState, String>(
      PipelineController.new,
    );

final meetingsProvider = FutureProvider<List<Meeting>>((ref) async {
  final repo = await ref.watch(meetingRepositoryProvider.future);
  return repo.all();
});

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
