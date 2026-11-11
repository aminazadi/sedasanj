import 'dart:async';
import 'dart:io';

import 'package:disk_space_plus/disk_space_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart' show PlatformException;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:record/record.dart';
import 'package:uuid/uuid.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import '../../../core/utils/format.dart';
import '../../../core/audio/channel_ownership.dart';
import '../../../core/audio/chunk_writer.dart';
import '../../../core/audio/multichannel_capture.dart';
import '../../../core/audio/pcm_channels.dart';
import '../../../core/audio/wav.dart';
import '../../../core/platform/recording_service.dart';
import '../../../core/providers.dart';
import '../../../core/speaker/speaker_matcher.dart';
import '../../meetings/application/meeting_providers.dart';
import '../../meetings/data/attendee.dart';
import '../../meetings/data/meeting.dart';
import '../../meetings/data/meeting_repository.dart';
import '../../upload/upload_controller.dart';
import 'live_audio_waveform.dart';
import 'live_engine_provider.dart';
import 'live_transcript_session.dart';

/// Meetings are recorded mono at 16 kHz, the native rate of the ASR models
/// and of the upload format, so nothing needs resampling downstream.
const int kRecordSampleRate = 16000;

/// Recording refuses to start (and stops) below this much free space; two
/// hours of mono 16 kHz audio take about 230 MB, written twice while chunks
/// wait for upload.
const int kMinFreeDiskMb = 500;

/// Prefix of [RecorderState.selectedInputDeviceId] for a native multi-channel
/// device (the rest is its CoreAudio UID).
const kMultichannelPrefix = 'mc:';

/// Uid of the combined "all connected microphones" input.
const kAllMicrophonesUid = '__all__';

const _saveErrorCode = 'JN-REC-0003';
const _finalizationWarningCode = 'JN-REC-0004';
const _attendeesWarningCode = 'JN-REC-0005';
const _usbInputCode = 'JN-REC-0007';
const _usbInputStartError =
    'ورودی USB باز نشد. گیرنده را از گوشی جدا و دوباره وصل کنید، سپس ضبط را دوباره شروع کنید. ($_usbInputCode)';
const _usbInputLostError =
    'ورودی USB قطع شد یا صدا به میکروفون دیگری رفت؛ ضبط تا اینجا ذخیره شد. گیرنده را دوباره وصل کنید و ضبط تازه‌ای شروع کنید. ($_usbInputCode)';
const _usbInputErrorCodes = {
  'wrong_route',
  'device_lost',
  'device_missing',
  'no_input',
  'format',
  'start',
};
const _saveError =
    'ذخیرهٔ ضبط کامل نشد. برنامه را دوباره باز کنید و فهرست جلسات را بررسی کنید. ($_saveErrorCode)';
const _finalizationWarning =
    'جلسه ذخیره شد. پخش صدا و وضعیت ارسال را در جزئیات بررسی کنید. ($_finalizationWarningCode)';

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
    this.captureSources = const [],
    this.channels = 1,
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

  /// Multi-channel devices (2+ input channels) found on this computer.
  final List<CaptureSource> captureSources;

  /// Microphone channels of the running recording (1 = ordinary mono).
  final int channels;

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
    List<CaptureSource>? captureSources,
    int? channels,
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
    captureSources: captureSources ?? this.captureSources,
    channels: channels ?? this.channels,
  );
}

class RecorderController extends Notifier<RecorderState> {
  /// Repaint the waveform directly without rebuilding the recording screen.
  final waveform = LiveAudioWaveform(sampleRate: kRecordSampleRate);

  /// One waveform per microphone channel of the running recording; the first
  /// one is [waveform]. Extra ones are created once and reused.
  final ValueNotifier<List<LiveAudioWaveform>> channelWaveforms =
      ValueNotifier<List<LiveAudioWaveform>>(const []);
  final List<LiveAudioWaveform> _waveformPool = [];

  /// Channels (0-based) the user muted. A muted channel is silenced before
  /// anything uses it: the per-channel file, the mix, the live text and the
  /// upload all get silence for it. Cleared when a new recording starts.
  final ValueNotifier<Set<int>> mutedChannels = ValueNotifier(const {});

  void toggleChannelMute(int channel) {
    final next = {...mutedChannels.value};
    if (!next.remove(channel)) next.add(channel);
    mutedChannels.value = next;
  }

  /// Who holds each microphone (0-based channel → person). While a channel
  /// has an owner its lines are named after that person and voice recognition
  /// is not used for them. The owner can change during the recording: the new
  /// one counts from that moment on and earlier lines keep the old one.
  final ValueNotifier<Map<int, SpeakerIdentity>> channelOwners = ValueNotifier(
    const {},
  );
  ChannelAssignments _assignments = ChannelAssignments();
  ChannelActivityLog? _activityLog;

  /// Samples fed to the live transcript so far: its clock, which the owner
  /// changes are stamped with (paused time is not counted, like the text).
  int _liveSamples = 0;

  void assignChannel(int channel, SpeakerIdentity? who) {
    _assignments.assign(
      channel,
      who,
      atMs: _liveSamples * 1000 ~/ kRecordSampleRate,
    );
    final next = {...channelOwners.value};
    if (who == null) {
      next.remove(channel);
    } else {
      next[channel] = who;
    }
    channelOwners.value = next;
  }

  /// A one-line Persian note about the microphone channels (a copied or silent
  /// channel), or null when all is well. Cleared when a recording starts.
  final ValueNotifier<String?> channelNotice = ValueNotifier(null);
  ChannelProbe? _probe;

  /// Channels left out of the mix because they are silent or a copy of another.
  Set<int> _excluded = const {};

  /// Channels of the phone's own microphone in the running recording.
  Set<int> _ownMicChannels = const {};

  void _applyHealth(List<ChannelHealth> health) {
    final skip = <int>{};
    final copies = <int>[];
    final dead = <int>[];
    for (var c = 0; c < health.length; c++) {
      if (health[c] == ChannelHealth.duplicate) {
        skip.add(c);
        copies.add(c);
      } else if (health[c] == ChannelHealth.dead) {
        skip.add(c);
        dead.add(c);
      }
    }
    _excluded = skip;
    debugPrint('JN-REC: channel health $health');
    if (copies.isNotEmpty) {
      channelNotice.value =
          'این گیرنده صدای همهٔ میکروفون‌ها را در یک کانال می‌فرستد؛ تفکیک گوینده با تشخیص خودکار صدا انجام می‌شود.';
    } else if (dead.isNotEmpty && dead.every(_ownMicChannels.contains)) {
      channelNotice.value =
          'این گوشی میکروفون خودش را هم‌زمان با گیرندهٔ USB در اختیار نمی‌گذارد؛ فقط صدای گیرنده ضبط می‌شود.';
    } else if (dead.isNotEmpty) {
      final names = dead.map((c) => toPersianDigits('${c + 1}')).join('، ');
      channelNotice.value =
          'کانال $names صدایی نمی‌فرستد؛ فرستندهٔ آن را روشن کنید یا اتصال را بررسی کنید.';
    } else {
      channelNotice.value = null;
    }
  }

  final MultichannelCapture _native = MultichannelCapture();
  PcmDeinterleaver? _deinterleaver;
  ChannelMixdown? _mixdown;
  WavFileWriter? _rawWriter;
  bool _nativeActive = false;

  List<LiveAudioWaveform> _waveformsFor(int channels) {
    if (_waveformPool.isEmpty) _waveformPool.add(waveform);
    while (_waveformPool.length < channels) {
      _waveformPool.add(LiveAudioWaveform(sampleRate: kRecordSampleRate));
    }
    return List.unmodifiable(_waveformPool.take(channels));
  }

  void _clearWaveforms() {
    for (final w in _waveformPool) {
      w.clear();
    }
    waveform.clear();
  }

  /// Live transcript of the running recording; like [waveform], separate from
  /// [RecorderState] so a new line does not rebuild the whole screen.
  final ValueNotifier<LiveTranscriptState> live =
      ValueNotifier<LiveTranscriptState>(const LiveTranscriptState());
  LiveTranscriptSession? _live;
  VoidCallback? _liveListener;

  /// Whether the live panel has anything to show; changes rarely, so the
  /// screen can re-layout on it without following every new line.
  final ValueNotifier<bool> liveVisible = ValueNotifier<bool>(false);

  void _setLive(LiveTranscriptState value) {
    live.value = value;
    liveVisible.value = value.phase != LivePhase.off || value.lines.isNotEmpty;
  }

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
  bool _chunkRegistrationFailed = false;

  /// True from the moment a meeting row is created until its recording is
  /// closed. The upload queue must not touch a meeting in this window.
  bool get isCapturing =>
      state.status != RecorderStatus.idle || _meetingId != null;

  @override
  RecorderState build() {
    ref.onDispose(_disposeResources);
    ref.onDispose(() {
      for (final w in _waveformPool) {
        if (w != waveform) w.dispose();
      }
      channelWaveforms.dispose();
      waveform.dispose();
    });
    channelWaveforms.value = [waveform];
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
      // CoreAudio's own temporary "CADefaultDeviceAggregate-…" device is not a
      // microphone; offering it only confuses.
      final devices = [
        for (final d in await recorder.listInputDevices())
          if (!d.label.startsWith('CADefaultDeviceAggregate') &&
              !d.id.startsWith('CADefaultDeviceAggregate'))
            d,
      ];
      final sources = await _multichannelSources();
      final selectedId = _validSelection(devices, sources);
      state = state.copyWith(
        inputDevices: devices,
        captureSources: sources,
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

  Future<List<CaptureSource>> _multichannelSources() async {
    try {
      final all = await _native.listSources();
      // Channels of the device's own microphone inside the combined input.
      final own = <int>{};
      var at = 0;
      for (final s in all) {
        if (s.builtIn) {
          own.addAll([for (var c = 0; c < s.channels; c++) at + c]);
        }
        at += s.channels;
      }
      return [
        // Two or more separate microphones are offered as one combined input:
        // macOS opens several devices at once; Android opens the USB receiver
        // together with the phone's own microphone.
        if (all.length >= 2 && (Platform.isMacOS || Platform.isAndroid))
          CaptureSource(
            uid: kAllMicrophonesUid,
            name: 'همهٔ میکروفون‌های متصل (${all.length})',
            channels: all.fold(0, (sum, s) => sum + s.channels),
            sampleRate: all.first.sampleRate,
            memberUids: [for (final s in all) s.uid],
            builtInChannels: own,
          ),
        for (final s in all)
          if (s.channels >= 2 && !s.builtIn) s,
      ];
    } catch (_) {
      return const [];
    }
  }

  /// Every connected microphone is always used: the combined input when
  /// there are several devices (macOS), else the one multi-channel device.
  /// Empty means the ordinary single default microphone.
  String _validSelection(
    List<InputDevice> devices,
    List<CaptureSource> sources,
  ) => sources.isEmpty ? '' : '$kMultichannelPrefix${sources.first.uid}';

  Future<int?> _freeDiskMb() async {
    try {
      final free = await DiskSpacePlus().getFreeDiskSpace;
      return free?.floor();
    } catch (_) {
      return null;
    }
  }

  /// Starts recording. [attendees] are the people chosen as present; they are
  /// saved with the meeting before audio starts so a crash keeps them.
  Future<void> start({List<Attendee> attendees = const []}) async {
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
      final sources = await _multichannelSources();
      final selectedId = _validSelection(devices, sources);
      state = state.copyWith(
        inputDevices: devices,
        captureSources: sources,
        selectedInputDeviceId: selectedId,
      );
      CaptureSource? multi;
      if (selectedId.startsWith(kMultichannelPrefix)) {
        final uid = selectedId.substring(kMultichannelPrefix.length);
        for (final s in sources) {
          if (s.uid == uid) multi = s;
        }
      }
      final channelCount = multi?.channels ?? 1;
      debugPrint(
        'JN-REC: input=${multi == null ? 'default mono' : '${multi.name} x${multi.channels}'}',
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
      if (channelCount > 1) {
        // Every microphone untouched, next to the mono mix the app works on.
        final rawPath = paths.multiChannelWavPath(meetingId);
        await File(rawPath).parent.create(recursive: true);
        _rawWriter = await WavFileWriter.open(
          File(rawPath),
          sampleRate: kRecordSampleRate,
          channels: channelCount,
        );
        _deinterleaver = PcmDeinterleaver(channelCount);
        _probe = ChannelProbe(channelCount, sampleRate: kRecordSampleRate);
        _excluded = const {};
        _ownMicChannels = multi?.builtInChannels ?? const {};
        channelNotice.value = null;
        _activityLog = ChannelActivityLog(sampleRate: kRecordSampleRate);
        _mixdown = ChannelMixdown(log: _activityLog);
      }
      _chunkRows = Future.value();
      _chunkRegistrationFailed = false;
      _chunks = ChunkWriter(
        dir: paths.meetingChunksDir(meetingId),
        onChunk: (chunk) {
          _chunkRows = _chunkRows.then((_) async {
            try {
              await repo.insertChunk(meetingId, chunk);
            } catch (error) {
              _chunkRegistrationFailed = true;
              _reportFailure(
                _finalizationWarningCode,
                'Register upload chunk',
                error,
              );
            }
          });
          state = state.copyWith(chunkCount: chunk.seq + 1);
        },
      );
      final sendText = await ref.read(sendTranscriptEnabledProvider.future);
      // Marked before the row exists so the upload queue never sees an open
      // recording that looks abandoned.
      _meetingId = meetingId;
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
          sendText: sendText,
          speakersState: 'pending',
        ),
      );
      ref.invalidate(meetingsProvider);
      _repo = repo;
      if (attendees.isNotEmpty) {
        try {
          await repo.setAttendees(meetingId, attendees);
        } catch (error) {
          // The recording matters more than the list; it can be edited later.
          _reportFailure(
            _attendeesWarningCode,
            'Save meeting attendees',
            error,
          );
        }
      }

      if (multi == null) _activityLog = null;
      _assignments = ChannelAssignments();
      channelOwners.value = const {};
      _liveSamples = 0;
      await _startLive(
        repo,
        meetingId,
        attendeeIds: {for (final a in attendees) a.personId},
      );
      final warning = await RecordingService.start();
      _clearWaveforms();
      channelWaveforms.value = _waveformsFor(channelCount);
      mutedChannels.value = const {};
      if (channelCount == 1) channelNotice.value = null;
      _userPaused = false;
      _failing = false;
      if (multi != null) {
        // The plugin recorder is not used for a multi-channel device.
        await recorder.dispose();
        // Listen first so the native side has a sink before audio flows.
        _subscription = _native.pcm.listen(
          _onPcm,
          onError: (Object error) =>
              _captureFailed('Receive microphone audio', error),
        );
        final info = await _native.start(multi.uids);
        _nativeActive = true;
        if (info.channels != channelCount) {
          throw StateError(
            'JN-REC-0006: device reports ${info.channels} channels, expected $channelCount',
          );
        }
      } else {
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
        _subscription = stream.listen(
          _onPcm,
          onError: (Object error) =>
              _captureFailed('Receive microphone audio', error),
        );
        _stateSubscription = recorder.onStateChanged().listen(_onRecorderState);
      }
      _startTicker();
      await WakelockPlus.enable();
      state = RecorderState(
        status: RecorderStatus.recording,
        inputDevices: devices,
        captureSources: sources,
        selectedInputDeviceId: selectedId,
        channels: channelCount,
        error: warning,
      );
    } catch (e) {
      await _abortStart(recorder);
      if (e is PlatformException && _usbInputErrorCodes.contains(e.code)) {
        _reportFailure(_usbInputCode, 'Open USB input (${e.code})', e);
        state = const RecorderState(error: _usbInputStartError);
      } else {
        state = RecorderState(error: 'ضبط شروع نشد: $e');
      }
    }
  }

  Future<void> _abortStart(AudioRecorder recorder) async {
    try {
      await recorder.dispose();
    } catch (_) {}
    await _stopNative();
    _recorder = null;
    await RecordingService.stop();
    await _disposeLive();
    await _stateSubscription?.cancel();
    _stateSubscription = null;
    try {
      await _chunks?.close();
      await _writer?.close();
      await _rawWriter?.close();
    } catch (_) {}
    _rawWriter = null;
    _deinterleaver = null;
    _mixdown = null;
    _probe = null;
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

  Future<void> _stopNative() async {
    if (!_nativeActive) return;
    _nativeActive = false;
    try {
      await _native.stop();
    } catch (_) {}
  }

  void _onPcm(Uint8List input) {
    var pcm = input;
    final split = _deinterleaver;
    if (split != null) {
      // A native device keeps delivering while the user has paused.
      if (_userPaused) return;
      final channels = split.split(input);
      final probe = _probe;
      if (probe != null && probe.add(channels)) _applyHealth(probe.health);
      final muted = mutedChannels.value;
      if (muted.isNotEmpty) {
        for (final c in muted) {
          if (c < channels.length) channels[c] = Uint8List(channels[c].length);
        }
      }
      if (!state.interrupted && state.status != RecorderStatus.saving) {
        final waveforms = channelWaveforms.value;
        for (var i = 0; i < channels.length && i < waveforms.length; i++) {
          waveforms[i].addPcm(channels[i]);
        }
      }
      _rawWriter
          ?.add(muted.isEmpty ? input : interleavePcm(channels))
          .catchError(
            (Object error) => _captureFailed('Write channel audio', error),
          );
      var skipped = muted;
      if (_excluded.isNotEmpty) {
        final both = {...muted, ..._excluded};
        // Never leave nothing to mix: if every channel would be skipped, only
        // the user's own mutes count.
        if (both.length < channels.length) skipped = both;
      }
      pcm = _mixdown!.mix(channels, muted: skipped);
      if (pcm.isEmpty) return;
    } else {
      // One microphone: muting it records silence everywhere.
      if (mutedChannels.value.contains(0)) pcm = Uint8List(input.length);
      if (!_userPaused &&
          !state.interrupted &&
          state.status != RecorderStatus.saving) {
        waveform.addPcm(pcm);
      }
    }
    _writer
        ?.add(pcm)
        .catchError(
          (Object error) => _captureFailed('Write recording audio', error),
        );
    _live?.feed(pcm);
    _liveSamples += pcm.length ~/ 2;
    if (_liveSamples % 160000 < pcm.length ~/ 2) {
      debugPrint(
        'JN-LIVE: fed ${_liveSamples ~/ 16000} s, live=${_live != null}',
      );
    }
    _chunks
        ?.add(pcm)
        .catchError(
          (Object error) => _captureFailed('Write upload chunk', error),
        );
  }

  void _onRecorderState(RecordState recorderState) {
    if (state.status == RecorderStatus.idle ||
        state.status == RecorderStatus.saving) {
      return;
    }
    if (recorderState == RecordState.pause && !_userPaused) {
      _clearWaveforms();
      _live?.pause();
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
  Future<void> _captureFailed(String operation, Object error) async {
    if (_failing || state.status == RecorderStatus.saving) return;
    if (error is PlatformException &&
        _usbInputErrorCodes.contains(error.code)) {
      _reportFailure(_usbInputCode, '$operation (${error.code})', error);
      await _fail(_usbInputLostError);
      return;
    }
    _reportFailure(_finalizationWarningCode, operation, error);
    await _fail(_finalizationWarning);
  }

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
    _clearWaveforms();
    await _recorder?.pause();
    _live?.pause();
    state = state.copyWith(status: RecorderStatus.paused);
  }

  Future<void> resume() async {
    if (state.status != RecorderStatus.paused) return;
    await _recorder?.resume();
    _userPaused = false;
    state = state.copyWith(status: RecorderStatus.recording);
  }

  /// Stops the recording and throws it away: the meeting row, the recording
  /// and the per-channel file are deleted. Nothing is kept.
  bool _discarding = false;

  Future<void> stopAndDiscard() async {
    final id = _meetingId;
    final repo = _repo;
    _discarding = true;
    try {
      await stop();
    } finally {
      _discarding = false;
    }
    if (id == null || repo == null) return;
    try {
      final meeting = await repo.byId(id);
      if (meeting == null) return;
      final paths = await ref.read(appPathsProvider.future);
      await repo.delete(meeting, extraFiles: [paths.multiChannelWavPath(id)]);
    } catch (e) {
      debugPrint('JN-REC: discard failed ($e)');
    }
  }

  Future<void> stop({String? streamError}) async {
    if (state.status != RecorderStatus.recording &&
        state.status != RecorderStatus.paused) {
      return;
    }
    state = state.copyWith(status: RecorderStatus.saving);
    _clearWaveforms();
    _ticker?.cancel();
    _diskTimer?.cancel();

    final meetingId = _meetingId;
    final repo = _repo;
    final chunks = _chunks;
    final writer = _writer;
    final recorder = _recorder;
    final rawWriter = _rawWriter;

    String? error = streamError;
    Future<void> finishOptional(
      String operation,
      Future<void> Function() action,
    ) async {
      try {
        await action();
      } catch (failure) {
        _reportFailure(_finalizationWarningCode, operation, failure);
        error ??= _finalizationWarning;
      }
    }

    await finishOptional('Stop microphone', () async {
      await recorder?.stop();
      await _stopNative();
    });
    await finishOptional(
      'Release microphone',
      () async => await recorder?.dispose(),
    );
    await finishOptional(
      'Close microphone stream',
      () async => await _subscription?.cancel(),
    );
    await finishOptional(
      'Close recorder state stream',
      () async => await _stateSubscription?.cancel(),
    );
    _subscription = null;
    _stateSubscription = null;
    _recorder = null;
    _meetingId = null;
    _repo = null;
    _chunks = null;
    _writer = null;
    _rawWriter = null;
    _deinterleaver = null;
    _mixdown = null;
    _probe = null;

    // Flush the draft after capture ends, in parallel with closing the WAVs.
    final liveDone = finishOptional('Finalize live transcript', _finishLive);
    await finishOptional('Stop recording service', RecordingService.stop);
    await finishOptional('Release wake lock', WakelockPlus.disable);
    await finishOptional(
      'Close upload chunks',
      () async => await chunks?.close(),
    );
    await _chunkRows;
    if (_chunkRegistrationFailed) error ??= _finalizationWarning;

    try {
      if (meetingId == null || repo == null || writer == null) {
        throw StateError('Missing active recording data');
      }
      await Future.wait([
        writer.close(),
        liveDone,
        if (rawWriter != null) rawWriter.close(),
      ]);
      await repo.finishRecording(meetingId, writer.duration);
    } catch (failure) {
      await liveDone;
      _reportFailure(_saveErrorCode, 'Save local recording', failure);
      if (ref.mounted) state = const RecorderState(error: _saveError);
      // The row would stay "recording" and never be sent; the upload queue
      // repairs it from the WAV on its next pass now that nothing is capturing.
      unawaited(_resumeUpload());
      return;
    }

    if (!ref.mounted) return;
    ref.invalidate(meetingsProvider);
    ref.invalidate(meetingDetailProvider(meetingId));
    ref.invalidate(meetingPreviewProvider(meetingId));
    // A discarded recording must not open the meeting it is about to delete.
    state = RecorderState(
      savedMeetingId: _discarding ? null : meetingId,
      error: error,
    );
    unawaited(_resumeUpload());
  }

  Future<void> _resumeUpload() async {
    try {
      // Identify the people first; the analysis wakes the upload when done.
      unawaited(ref.read(speakerAnalysisProvider.notifier).kick());
      await ref.read(uploadQueueProvider.notifier).kick();
    } catch (error) {
      _reportFailure(_finalizationWarningCode, 'Resume upload queue', error);
    }
  }

  void _reportFailure(String code, String operation, Object error) {
    debugPrint(
      '$code: $operation failed (${error.runtimeType}). Check the meeting list and retry.',
    );
  }

  void _disposeResources() {
    _ticker?.cancel();
    _diskTimer?.cancel();
    _subscription?.cancel();
    _stateSubscription?.cancel();
    _recorder?.dispose();
    _stopNative();
    _rawWriter?.close();
    _writer?.close();
    _chunks?.close();
    _live?.dispose();
    WakelockPlus.disable();
  }

  /// Starts live transcription for the meeting being recorded. A missing
  /// model or any failure only leaves the live panel empty with a hint; the
  /// recording starts either way.
  Future<void> _startLive(
    MeetingRepository repo,
    String meetingId, {
    Set<String> attendeeIds = const {},
  }) async {
    _setLive(const LiveTranscriptState());
    try {
      final setup = await ref.read(liveEngineBuilderProvider)(
        attendeeIds: attendeeIds,
      );
      final engine = setup.engine;
      if (engine == null) {
        _setLive(LiveTranscriptState(note: setup.unavailableReason));
        return;
      }
      final session = LiveTranscriptSession(
        engine: engine,
        store: repo,
        meetingId: meetingId,
        modelId: setup.modelId,
        ownership: ChannelOwnership(
          assignments: _assignments,
          log: _activityLog,
        ),
      );
      void mirror() => _setLive(session.state.value);
      session.state.addListener(mirror);
      _live = session;
      _liveListener = mirror;
      mirror();
      // Loading the model takes seconds; audio is buffered meanwhile.
      unawaited(session.start());
    } catch (e) {
      _setLive(
        const LiveTranscriptState(
          phase: LivePhase.failed,
          note: 'متن زنده شروع نشد؛ ضبط بدون آن ادامه دارد.',
        ),
      );
    }
  }

  Future<void> _finishLive() async {
    final session = _live;
    if (session == null) return;
    _live = null;
    try {
      await session.stop();
    } catch (_) {
      // The draft is best effort; the recording is already safe.
    }
    _unhookLive(session);
  }

  Future<void> _disposeLive() async {
    final session = _live;
    if (session == null) return;
    _live = null;
    try {
      await session.dispose();
    } catch (_) {}
    _unhookLive(session);
    _setLive(const LiveTranscriptState());
  }

  void _unhookLive(LiveTranscriptSession session) {
    final listener = _liveListener;
    if (listener != null) {
      listener();
      session.state.removeListener(listener);
      _liveListener = null;
    }
  }
}

final recorderControllerProvider =
    NotifierProvider<RecorderController, RecorderState>(RecorderController.new);
