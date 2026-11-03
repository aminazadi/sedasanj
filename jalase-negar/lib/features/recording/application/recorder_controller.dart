import 'dart:async';
import 'dart:io';
import 'dart:math' as math;

import 'package:disk_space_plus/disk_space_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:record/record.dart';
import 'package:uuid/uuid.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import '../../../core/utils/format.dart';
import '../../../core/audio/chunk_writer.dart';
import '../../../core/audio/wav.dart';
import '../../../core/platform/recording_service.dart';
import '../../../core/providers.dart';
import '../../meetings/application/pipeline_controller.dart';
import '../../meetings/data/meeting.dart';
import '../../meetings/data/meeting_repository.dart';
import '../../upload/upload_controller.dart';

/// Meetings are recorded mono at 16 kHz, the native rate of the ASR models
/// and of the upload format, so nothing needs resampling downstream.
const int kRecordSampleRate = 16000;

/// Recording refuses to start (and stops) below this much free space; two
/// hours of mono 16 kHz audio take about 230 MB, written twice while chunks
/// wait for upload.
const int kMinFreeDiskMb = 500;

enum RecorderStatus { idle, recording, paused, saving }

class RecorderState {
  const RecorderState({
    this.status = RecorderStatus.idle,
    this.elapsed = Duration.zero,
    this.error,
    this.savedMeetingId,
    this.inputDevices = const [],
    this.selectedInputDeviceId = '',
    this.discoveringInputDevices = false,
    this.interrupted = false,
    this.interruptions = 0,
    this.chunkCount = 0,
  });

  final RecorderStatus status;

  /// Length of the audio written to disk (sample-based, not wall clock).
  final Duration elapsed;
  final String? error;
  final String? savedMeetingId;
  final List<InputDevice> inputDevices;
  final String selectedInputDeviceId;
  final bool discoveringInputDevices;

  /// The OS paused capture (phone call, another app took the microphone).
  final bool interrupted;
  final int interruptions;
  final int chunkCount;

  RecorderState copyWith({
    RecorderStatus? status,
    Duration? elapsed,
    String? error,
    String? savedMeetingId,
    List<InputDevice>? inputDevices,
    String? selectedInputDeviceId,
    bool? discoveringInputDevices,
    bool? interrupted,
    int? interruptions,
    int? chunkCount,
  }) => RecorderState(
    status: status ?? this.status,
    elapsed: elapsed ?? this.elapsed,
    error: error,
    savedMeetingId: savedMeetingId,
    inputDevices: inputDevices ?? this.inputDevices,
    selectedInputDeviceId: selectedInputDeviceId ?? this.selectedInputDeviceId,
    discoveringInputDevices:
        discoveringInputDevices ?? this.discoveringInputDevices,
    interrupted: interrupted ?? this.interrupted,
    interruptions: interruptions ?? this.interruptions,
    chunkCount: chunkCount ?? this.chunkCount,
  );
}

class RecorderController extends Notifier<RecorderState> {
  /// Smoothed input loudness 0..1 for the live waveform. Kept out of
  /// [RecorderState] so a level update never rebuilds the whole screen.
  final ValueNotifier<double> level = ValueNotifier<double>(0);

  AudioRecorder? _recorder;
  StreamSubscription<Uint8List>? _subscription;
  StreamSubscription<RecordState>? _stateSubscription;
  WavFileWriter? _writer;
  ChunkWriter? _chunks;
  MeetingRepository? _repo;
  Timer? _ticker;
  Timer? _diskTimer;
  String? _meetingId;
  bool _userPaused = false;
  bool _failing = false;
  Future<void> _chunkRows = Future.value();

  @override
  RecorderState build() {
    ref.onDispose(_disposeResources);
    return const RecorderState();
  }

  InputDevice? _selectedInputDevice() {
    if (state.selectedInputDeviceId.isEmpty) return null;
    for (final device in state.inputDevices) {
      if (device.id == state.selectedInputDeviceId) return device;
    }
    return null;
  }

  void setInputDevice(String id) {
    if (state.status != RecorderStatus.idle) return;
    state = state.copyWith(selectedInputDeviceId: id);
  }

  Future<void> refreshInputDevices() async {
    if (state.status != RecorderStatus.idle) return;
    await _discoverInputDevices(requestPermission: false);
  }

  Future<void> _discoverInputDevices({required bool requestPermission}) async {
    final recorder = AudioRecorder();
    try {
      state = state.copyWith(discoveringInputDevices: true, error: null);
      final hasPermission = await recorder.hasPermission(
        request: requestPermission,
      );
      if (!hasPermission) {
        state = state.copyWith(
          selectedInputDeviceId: '',
          inputDevices: const [],
          discoveringInputDevices: false,
          error: 'برای مشاهده میکروفون‌ها، دسترسی ضبط صدا فعال شود',
        );
        return;
      }
      final devices = await recorder.listInputDevices();
      var selectedId = state.selectedInputDeviceId;
      if (selectedId.isNotEmpty && !devices.any((d) => d.id == selectedId)) {
        selectedId = '';
      }
      state = state.copyWith(
        inputDevices: devices,
        selectedInputDeviceId: selectedId,
        discoveringInputDevices: false,
      );
    } catch (e) {
      state = state.copyWith(
        selectedInputDeviceId: '',
        inputDevices: const [],
        discoveringInputDevices: false,
        error: 'خطا در دریافت لیست میکروفون: $e',
      );
    } finally {
      await recorder.dispose();
    }
  }

  Future<int?> _freeDiskMb() async {
    try {
      final free = await DiskSpacePlus().getFreeDiskSpace;
      return free?.floor();
    } catch (_) {
      return null;
    }
  }

  Future<void> start() async {
    if (state.status != RecorderStatus.idle) return;
    final recorder = AudioRecorder();
    try {
      if (!await recorder.hasPermission()) {
        state = state.copyWith(
          error:
              'دسترسی به میکروفون داده نشد؛ در تنظیمات گوشی اجازه‌ی میکروفون را فعال کنید.',
        );
        await recorder.dispose();
        return;
      }
      final freeMb = await _freeDiskMb();
      if (freeMb != null && freeMb < kMinFreeDiskMb) {
        state = state.copyWith(
          error:
              'فضای گوشی کم است (کمتر از $kMinFreeDiskMb مگابایت)؛ فایل‌های قدیمی را پاک کنید و دوباره شروع کنید.',
        );
        await recorder.dispose();
        return;
      }
      final devices = await recorder.listInputDevices();
      var selectedId = state.selectedInputDeviceId;
      if (selectedId.isNotEmpty && !devices.any((d) => d.id == selectedId)) {
        selectedId = '';
      }
      state = state.copyWith(
        inputDevices: devices,
        selectedInputDeviceId: selectedId,
      );

      final paths = await ref.read(appPathsProvider.future);
      final repo = await ref.read(meetingRepositoryProvider.future);
      final meetingId = const Uuid().v4();
      final path = paths.recordingPath(meetingId);
      final now = DateTime.now();

      _writer = await WavFileWriter.open(
        File(path),
        sampleRate: kRecordSampleRate,
        channels: 1,
      );
      _chunks = ChunkWriter(
        dir: paths.meetingChunksDir(meetingId),
        onChunk: (chunk) {
          _chunkRows = _chunkRows.then(
            (_) => repo.insertChunk(meetingId, chunk),
          );
          state = state.copyWith(chunkCount: chunk.seq + 1);
        },
      );
      // The row exists from the first second, so a crash leaves a recoverable
      // meeting instead of orphan files.
      await repo.insert(
        Meeting(
          id: meetingId,
          title: 'جلسه ${formatJalaliDay(now)}',
          createdAt: now,
          duration: Duration.zero,
          audioPath: path,
          sampleRate: kRecordSampleRate,
          channels: 1,
          status: MeetingStatus.recording,
          recordingState: 'recording',
        ),
      );
      ref.invalidate(meetingsProvider);
      _repo = repo;
      _meetingId = meetingId;

      final warning = await RecordingService.start();
      final stream = await recorder.startStream(
        RecordConfig(
          encoder: AudioEncoder.pcm16bits,
          sampleRate: kRecordSampleRate,
          numChannels: 1,
          device: devices.isEmpty ? null : _selectedInputDevice(),
          // Quiet speech is lifted by the platform before it is written;
          // meeting audio never contains app playback, so echo cancel is off.
          autoGain: true,
          noiseSuppress: true,
          echoCancel: false,
          audioInterruption: AudioInterruptionMode.pauseResume,
        ),
      );
      _recorder = recorder;
      _userPaused = false;
      _failing = false;
      _subscription = stream.listen(
        _onPcm,
        onError: (Object e) => _fail('خطا در دریافت صدا: $e'),
      );
      _stateSubscription = recorder.onStateChanged().listen(_onRecorderState);
      _startTicker();
      await WakelockPlus.enable();
      state = RecorderState(
        status: RecorderStatus.recording,
        inputDevices: devices,
        selectedInputDeviceId: selectedId,
        error: warning,
      );
    } catch (e) {
      await _abortStart(recorder);
      state = RecorderState(error: 'ضبط شروع نشد: $e');
    }
  }

  Future<void> _abortStart(AudioRecorder recorder) async {
    await recorder.dispose();
    _recorder = null;
    await RecordingService.stop();
    await _stateSubscription?.cancel();
    _stateSubscription = null;
    try {
      await _chunks?.close();
      await _writer?.close();
    } catch (_) {}
    final id = _meetingId;
    final repo = _repo;
    if (id != null && repo != null) {
      final meeting = await repo.byId(id);
      if (meeting != null) await repo.delete(meeting);
      ref.invalidate(meetingsProvider);
    }
    _chunks = null;
    _writer = null;
    _meetingId = null;
    _repo = null;
  }

  void _onPcm(Uint8List pcm) {
    _updateLevel(pcm);
    // Both writers swallow no errors: a failed write surfaces through the
    // returned future and stops the recording with the audio kept so far.
    _writer?.add(pcm);
    _chunks?.add(pcm).catchError((Object e) => _fail('خطا در نوشتن فایل: $e'));
  }

  /// RMS of the 16-bit little-endian PCM chunk (every 4th sample), mapped to
  /// a perceptual 0..1 level with a quick decay.
  void _updateLevel(Uint8List pcm) {
    final data = ByteData.sublistView(pcm);
    var sum = 0.0;
    var n = 0;
    for (var i = 0; i + 1 < pcm.lengthInBytes; i += 8) {
      final v = data.getInt16(i, Endian.little) / 32768.0;
      sum += v * v;
      n++;
    }
    if (n == 0) return;
    final raw = (math.sqrt(sum / n) * 5).clamp(0.0, 1.0);
    level.value = math.max(raw, level.value * 0.6);
  }

  void _onRecorderState(RecordState recorderState) {
    if (state.status == RecorderStatus.idle ||
        state.status == RecorderStatus.saving) {
      return;
    }
    if (recorderState == RecordState.pause && !_userPaused) {
      state = state.copyWith(
        interrupted: true,
        interruptions: state.interruptions + 1,
      );
    } else if (recorderState == RecordState.record && state.interrupted) {
      state = state.copyWith(interrupted: false);
    }
  }

  /// A failing stream or disk stops the recording and keeps what was
  /// captured, so a long meeting is never lost to one write error.
  Future<void> _fail(String message) async {
    if (_failing) return;
    _failing = true;
    if (state.status == RecorderStatus.recording ||
        state.status == RecorderStatus.paused) {
      await stop(streamError: message);
    }
  }

  void _startTicker() {
    _ticker?.cancel();
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) {
      final chunks = _chunks;
      if (chunks != null) state = state.copyWith(elapsed: chunks.duration);
    });
    _diskTimer?.cancel();
    _diskTimer = Timer.periodic(const Duration(seconds: 30), (_) async {
      final freeMb = await _freeDiskMb();
      if (freeMb != null && freeMb < kMinFreeDiskMb ~/ 5) {
        _fail(
          'فضای گوشی تمام شد؛ ضبط متوقف و صدای تا اینجا ذخیره شد. فایل‌های قدیمی را پاک کنید.',
        );
      }
    });
  }

  Future<void> pause() async {
    if (state.status != RecorderStatus.recording) return;
    _userPaused = true;
    level.value = 0;
    await _recorder?.pause();
    state = state.copyWith(status: RecorderStatus.paused);
  }

  Future<void> resume() async {
    if (state.status != RecorderStatus.paused) return;
    await _recorder?.resume();
    _userPaused = false;
    state = state.copyWith(status: RecorderStatus.recording);
  }

  Future<void> stop({String? streamError}) async {
    if (state.status != RecorderStatus.recording &&
        state.status != RecorderStatus.paused) {
      return;
    }
    state = state.copyWith(status: RecorderStatus.saving);
    level.value = 0;
    _ticker?.cancel();
    _diskTimer?.cancel();
    await WakelockPlus.disable();

    final meetingId = _meetingId;
    final repo = _repo;
    final chunks = _chunks;
    final writer = _writer;
    _meetingId = null;
    _chunks = null;
    _writer = null;

    String? error = streamError;
    try {
      await _subscription?.cancel();
      _subscription = null;
      await _stateSubscription?.cancel();
      _stateSubscription = null;
      await _recorder?.stop();
      await _recorder?.dispose();
      _recorder = null;
      await RecordingService.stop();
      try {
        await chunks?.close();
      } catch (e) {
        error ??= 'آخرین بخش صدا ذخیره نشد: $e';
      }
      await writer?.close();
      await _chunkRows;

      if (meetingId == null || repo == null) {
        state = RecorderState(error: error ?? 'ضبط ناقص بود');
        return;
      }
      await repo.finishRecording(
        meetingId,
        chunks?.duration ?? writer?.duration ?? Duration.zero,
      );
      ref.invalidate(meetingsProvider);
      ref.read(uploadQueueProvider.notifier).kick();
      state = RecorderState(savedMeetingId: meetingId, error: error);
    } catch (e) {
      state = RecorderState(error: error ?? e.toString());
    }
  }

  void _disposeResources() {
    _ticker?.cancel();
    _diskTimer?.cancel();
    _subscription?.cancel();
    _stateSubscription?.cancel();
    _recorder?.dispose();
    _writer?.close();
    _chunks?.close();
    WakelockPlus.disable();
  }
}

final recorderControllerProvider =
    NotifierProvider<RecorderController, RecorderState>(RecorderController.new);
