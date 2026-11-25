import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/providers.dart';
import 'package:jalase_negar/features/meetings/application/meeting_providers.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';
import 'package:jalase_negar/features/meetings/data/meeting_repository.dart';
import 'package:jalase_negar/features/recording/application/recorder_controller.dart';
import 'package:jalase_negar/features/upload/upload_controller.dart';

import '../people/people_test_support.dart';

class _IdleRecorder extends RecorderController {
  @override
  RecorderState build() => const RecorderState();
}

class _IdleUploads extends UploadController {
  @override
  UploadState build() => const UploadState();

  @override
  Future<void> kick() async {}
}

class _FakeActions extends MeetingActions {
  _FakeActions(super.ref, super.meetingId, this.onRun);

  final Future<void> Function(String id) onRun;

  @override
  Future<PreciseOutcome> runPreciseProcessing() async {
    await onRun(meetingId);
    return const PreciseOutcome(PreciseStatus.done);
  }
}

Meeting _meeting(String id) => Meeting(
  id: id,
  title: id,
  createdAt: DateTime(2026, 11, 1),
  duration: const Duration(minutes: 1),
  audioPath: '/nowhere/$id.wav',
  sampleRate: 16000,
  channels: 1,
  status: MeetingStatus.recorded,
  recordingState: 'finished',
  speakersState: 'pending',
);

void main() {
  test(
    'a meeting finishing during analysis is analysed in the same run',
    () async {
      final (db, dir) = await openTestDb();
      addTearDown(() async {
        await db.db.close();
        dir.deleteSync(recursive: true);
      });
      final repo = MeetingRepository(db);
      await repo.insert(_meeting('m1'));

      final gate = Completer<void>();
      final processed = <String>[];
      final container = ProviderContainer(
        overrides: [
          appDatabaseProvider.overrideWith((ref) async => db),
          meetingRepositoryProvider.overrideWith((ref) async => repo),
          recorderControllerProvider.overrideWith(_IdleRecorder.new),
          uploadQueueProvider.overrideWith(_IdleUploads.new),
          meetingActionsProvider.overrideWith(
            (ref, id) => _FakeActions(ref, id, (name) async {
              processed.add(name);
            if (name == 'm1') {
              await gate.future;
            }
            await repo.setSpeakersState(name, 'done');
            }),
          ),
        ],
      );
      addTearDown(container.dispose);

      final notifier = container.read(speakerAnalysisProvider.notifier);
      // Let the controller's start-up pass begin m1.
      await Future<void>.delayed(const Duration(milliseconds: 20));
      await repo.insert(_meeting('m2'));
      // A second kick while m1 is running must not be dropped.
      unawaited(notifier.kick());
      gate.complete();
      await Future<void>.delayed(const Duration(milliseconds: 100));

      expect(processed, ['m1', 'm2']);
    },
  );
}
