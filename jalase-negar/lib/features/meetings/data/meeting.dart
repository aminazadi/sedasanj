enum MeetingStatus {
  recording,
  recorded,
  transcribing,
  transcribed,
  uploading,
  uploaded,
  processing,
  complete,
  failed;

  /// Lenient parse: statuses written by older app versions map to the
  /// closest current one instead of throwing.
  static MeetingStatus parse(String value) {
    for (final status in MeetingStatus.values) {
      if (status.name == value) return status;
    }
    return switch (value) {
      'correcting' || 'corrected' || 'summarizing' => MeetingStatus.transcribed,
      'done' => MeetingStatus.complete,
      _ => MeetingStatus.recorded,
    };
  }
}

class Meeting {
  const Meeting({
    required this.id,
    required this.title,
    required this.createdAt,
    required this.duration,
    required this.audioPath,
    required this.sampleRate,
    required this.channels,
    required this.status,
    this.error,
    this.recordingState = 'finished',
    this.remoteMeetingId,
    this.asrIdentity,
  });

  final String id;
  final String title;
  final DateTime createdAt;
  final Duration duration;
  final String audioPath;
  final int sampleRate;
  final int channels;
  final MeetingStatus status;
  final String? error;

  /// 'recording' while capture is live (or was cut short by a crash),
  /// 'finished' once the recording was closed cleanly or recovered.
  final String recordingState;
  final String? remoteMeetingId;

  /// How the on-device transcript was produced (model, audio preparation and
  /// segmentation), in the ASR parity contract's identity format. Null until
  /// the meeting is transcribed.
  final String? asrIdentity;

  /// Value equality lets the list skip rebuilding tiles whose meeting did not
  /// change when the list is reloaded.
  @override
  bool operator ==(Object other) =>
      other is Meeting &&
      other.id == id &&
      other.title == title &&
      other.createdAt == createdAt &&
      other.duration == duration &&
      other.audioPath == audioPath &&
      other.sampleRate == sampleRate &&
      other.channels == channels &&
      other.status == status &&
      other.error == error &&
      other.recordingState == recordingState &&
      other.remoteMeetingId == remoteMeetingId &&
      other.asrIdentity == asrIdentity;

  @override
  int get hashCode => Object.hash(
    id,
    title,
    createdAt,
    duration,
    audioPath,
    sampleRate,
    channels,
    status,
    error,
    recordingState,
    remoteMeetingId,
    asrIdentity,
  );

  Meeting copyWith({
    MeetingStatus? status,
    String? title,
    String? error,
    Duration? duration,
    String? audioPath,
    int? sampleRate,
    int? channels,
    String? recordingState,
    String? remoteMeetingId,
    String? asrIdentity,
  }) => Meeting(
    id: id,
    title: title ?? this.title,
    createdAt: createdAt,
    duration: duration ?? this.duration,
    audioPath: audioPath ?? this.audioPath,
    sampleRate: sampleRate ?? this.sampleRate,
    channels: channels ?? this.channels,
    status: status ?? this.status,
    error: error,
    recordingState: recordingState ?? this.recordingState,
    remoteMeetingId: remoteMeetingId ?? this.remoteMeetingId,
    asrIdentity: asrIdentity ?? this.asrIdentity,
  );

  factory Meeting.fromRow(Map<String, Object?> row) => Meeting(
    id: row['id'] as String,
    title: row['title'] as String,
    createdAt: DateTime.fromMillisecondsSinceEpoch(row['created_at'] as int),
    duration: Duration(milliseconds: row['duration_ms'] as int),
    audioPath: row['audio_path'] as String,
    sampleRate: row['sample_rate'] as int,
    channels: row['channels'] as int,
    status: MeetingStatus.parse(row['status'] as String),
    error: row['error'] as String?,
    recordingState: (row['recording_state'] as String?) ?? 'finished',
    remoteMeetingId: row['remote_meeting_id'] as String?,
    asrIdentity: row['asr_identity'] as String?,
  );

  Map<String, Object?> toRow() => {
    'id': id,
    'title': title,
    'created_at': createdAt.millisecondsSinceEpoch,
    'duration_ms': duration.inMilliseconds,
    'audio_path': audioPath,
    'sample_rate': sampleRate,
    'channels': channels,
    'status': status.name,
    'error': error,
    'recording_state': recordingState,
    'remote_meeting_id': remoteMeetingId,
    'asr_identity': asrIdentity,
  };
}

/// Where a segment's timestamps come from (ASR parity contract).
abstract final class TimestampSource {
  static const String sileroVad = 'silero_vad';
  static const String vadWindow = 'vad_window';
  static const String native = 'native';
  static const String diarization = 'diarization';
}

class Segment {
  const Segment({
    required this.channel,
    required this.startMs,
    required this.endMs,
    required this.text,
    this.confidence,
    this.speaker,
    this.timestampSource = TimestampSource.sileroVad,
    this.source = 'device',
  });

  final int channel;
  final int startMs;
  final int endMs;
  final String text;

  /// 0..1 when the recognizer provides one; null for RNNT/CTC (like the
  /// server, which only has a score for Whisper models).
  final double? confidence;
  final String? speaker;
  final String timestampSource;

  /// 'device' for on-device transcripts, 'server' for platform ones.
  final String source;

  factory Segment.fromRow(Map<String, Object?> row) => Segment(
    channel: row['channel'] as int,
    startMs: row['t_start_ms'] as int,
    endMs: row['t_end_ms'] as int,
    text: row['text'] as String,
    confidence: (row['confidence'] as num?)?.toDouble(),
    speaker: row['speaker'] as String?,
    timestampSource:
        (row['timestamp_source'] as String?) ?? TimestampSource.sileroVad,
    source: (row['source'] as String?) ?? 'device',
  );
}
