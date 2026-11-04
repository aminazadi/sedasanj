import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/audio/chunk_writer.dart';
import 'package:jalase_negar/core/audio/wav.dart';
import 'package:jalase_negar/core/providers.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';
import 'package:jalase_negar/features/meetings/data/meeting_repository.dart';
import 'package:jalase_negar/features/recording/application/live_engine_provider.dart';
import 'package:jalase_negar/features/recording/application/recorder_controller.dart';
import 'package:jalase_negar/features/upload/upload_controller.dart';

void main() {
  final binding = TestWidgetsFlutterBinding.ensureInitialized();
  final messenger = binding.defaultBinaryMessenger;
  late Directory root;
  late String pcmChannel;

  Future<void> sendAudio() async {
    final pcm = Uint8List(kRecordSampleRate ~/ 50 * 2);
    await messenger.handlePlatformMessage(
      pcmChannel,
      const StandardMethodCodec().encodeSuccessEnvelope(pcm),
      (_) {},
    );
  }

  setUpAll(() async {
    root = await Directory.systemTemp.createTemp('recorder-finalization');
  });
  tearDownAll(() => root.delete(recursive: true));

  setUp(() {
    _UploadQueue.kicks = 0;
    void mock(String name, Future<Object?> Function(MethodCall) handler) {
      final channel = MethodChannel(name);
      messenger.setMockMethodCallHandler(channel, handler);
      addTearDown(() => messenger.setMockMethodCallHandler(channel, null));
    }

    mock('plugins.flutter.io/path_provider', (_) async => root.path);
    mock('com.llfbandit.record/messages', (call) async {
      switch (call.method) {
        case 'create':
          final id = call.arguments['recorderId'];
          pcmChannel = 'com.llfbandit.record/eventsRecord/$id';
          mock(pcmChannel, (_) async => null);
          mock('com.llfbandit.record/events/$id', (_) async => null);
        case 'hasPermission':
          return true;
        case 'listInputDevices':
          return <Object>[];
        case 'stop':
          await sendAudio();
      }
      return null;
    });

    var serviceRunning = false;
    mock('flutter_foreground_task/methods', (call) async {
      switch (call.method) {
        case 'checkNotificationPermission':
          return 0;
        case 'isRunningService':
          return serviceRunning;
        case 'startService':
          serviceRunning = true;
        case 'stopService':
          serviceRunning = false;
      }
      return null;
    });

    const wakeLock =
        'dev.flutter.pigeon.wakelock_plus_platform_interface.WakelockPlusApi.toggle';
    messenger.setMockMessageHandler(
      wakeLock,
      (_) async => const StandardMessageCodec().encodeMessage([null]),
    );
    addTearDown(() => messenger.setMockMessageHandler(wakeLock, null));
  });

  test('saves the WAV and publishes the ID when a chunk row fails', () async {
    final repo = _Meetings()..failChunk = true;
    final container = _container(repo);
    addTearDown(container.dispose);
    final recorder = container.read(recorderControllerProvider.notifier);

    await recorder.start();
    expect(
      container.read(recorderControllerProvider).status,
      RecorderStatus.recording,
    );
    await sendAudio();
    await recorder.stop();

    final saved = container.read(recorderControllerProvider);
    expect(saved.savedMeetingId, repo.inserted.id);
    expect(saved.error, contains('JN-REC-0004'));
    expect(saved.error, isNot(contains('private database error')));
    expect(repo.finished, const Duration(milliseconds: 40));
    expect((await readWavInfo(repo.inserted.audioPath)).duration, repo.finished);

    repo.failChunk = false;
    await recorder.start();
    await sendAudio();
    await recorder.stop();
    expect(container.read(recorderControllerProvider).error, isNull);
    expect(repo.registeredChunks, 1);
  });

  test('is capturing from the first row until the recording is closed', () async {
    final repo = _Meetings();
    final container = _container(repo);
    addTearDown(container.dispose);
    final recorder = container.read(recorderControllerProvider.notifier);

    expect(recorder.isCapturing, isFalse);
    await recorder.start();
    expect(recorder.isCapturing, isTrue);
    await sendAudio();
    await recorder.stop();
    expect(recorder.isCapturing, isFalse);
  });

  test('a failed final save leaves nothing capturing and wakes the queue', () async {
    final repo = _Meetings()..failSave = true;
    final container = _container(repo);
    addTearDown(container.dispose);
    final recorder = container.read(recorderControllerProvider.notifier);

    await recorder.start();
    await sendAudio();
    await recorder.stop();

    expect(recorder.isCapturing, isFalse);
    expect(_UploadQueue.kicks, greaterThan(0));
  });

  test(
    'keeps the WAV and reports a short error if the local row fails',
    () async {
      final repo = _Meetings()..failSave = true;
      final container = _container(repo);
      addTearDown(container.dispose);
      final recorder = container.read(recorderControllerProvider.notifier);

      await recorder.start();
      await sendAudio();
      await recorder.stop();

      final state = container.read(recorderControllerProvider);
      expect(state.savedMeetingId, isNull);
      expect(state.status, RecorderStatus.idle);
      expect(state.error, contains('JN-REC-0003'));
      expect(state.error, isNot(contains('private database error')));
      expect(
        (await readWavInfo(repo.inserted.audioPath)).duration.inMilliseconds,
        40,
      );
    },
  );
}

ProviderContainer _container(_Meetings repo) => ProviderContainer(
  overrides: [
    meetingRepositoryProvider.overrideWith((_) async => repo),
    sendTranscriptEnabledProvider.overrideWith(_SendPreference.new),
    liveEngineBuilderProvider.overrideWithValue(
      () async => const LiveEngineSetup.unavailable(),
    ),
    uploadQueueProvider.overrideWith(_UploadQueue.new),
  ],
);

class _Meetings implements MeetingRepository {
  late Meeting inserted;
  bool failChunk = false;
  bool failSave = false;
  int registeredChunks = 0;
  Duration? finished;

  @override
  Future<void> insert(Meeting meeting) async => inserted = meeting;

  @override
  Future<void> insertChunk(String meetingId, ChunkInfo chunk) async {
    if (failChunk) throw StateError('private database error');
    registeredChunks++;
  }

  @override
  Future<void> finishRecording(String id, Duration duration) async {
    if (failSave) throw StateError('private database error');
    finished = duration;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _SendPreference extends SendTranscriptEnabled {
  @override
  Future<bool> build() async => true;
}

class _UploadQueue extends UploadController {
  @override
  UploadState build() => const UploadState();

  static int kicks = 0;

  @override
  Future<void> kick() async => kicks++;
}
