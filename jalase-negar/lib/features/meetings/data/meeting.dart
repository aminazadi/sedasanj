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
    this.sendText = true,
    this.textSyncPending = false,
    this.speakersState = 'done',
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

  /// Whether this meeting's transcript is sent to SedaSanj. Snapshot of the
  /// settings switch taken when the meeting is created, so changing the
  /// switch later never affects meetings already recorded.
  final bool sendText;

  /// The text was edited after it was sent to SedaSanj and the server has not
  /// taken the edit yet.
  final bool textSyncPending;

  /// 'pending' / 'analyzing' while the people of the recording are being
  /// identified (nothing is sent meanwhile), 'done' otherwise.
  final String speakersState;

  bool get analyzingSpeakers => speakersState != 'done';

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
      other.asrIdentity == asrIdentity &&
      other.sendText == sendText &&
      other.textSyncPending == textSyncPending &&
      other.speakersState == speakersState;

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
    sendText,
    textSyncPending,
    speakersState,
  );

  /// The meeting as the list should show it when no recorder is open: a row
  /// still marked [MeetingStatus.recording] was cut short, not live.
  Meeting asClosedRecording() => status == MeetingStatus.recording
      ? copyWith(status: MeetingStatus.recorded)
      : this;

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
    bool? sendText,
    bool? textSyncPending,
    String? speakersState,
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
    sendText: sendText ?? this.sendText,
    textSyncPending: textSyncPending ?? this.textSyncPending,
    speakersState: speakersState ?? this.speakersState,
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
    sendText: ((row['send_text'] as int?) ?? 1) != 0,
    textSyncPending: ((row['text_sync_pending'] as int?) ?? 0) != 0,
    speakersState: (row['speakers_state'] as String?) ?? 'done',
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
    'send_text': sendText ? 1 : 0,
    'text_sync_pending': textSyncPending ? 1 : 0,
    'speakers_state': speakersState,
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
    this.speakerPersonId,
    this.speaker2,
    this.speaker2PersonId,
    this.overlap = false,
    this.speakerConfidence,
    this.speakerManual = false,
  });

  final int channel;
  final int startMs;
  final int endMs;
  final String text;

  /// 0..1 when the recognizer provides one; null for RNNT/CTC (like the
  /// server, which only has a score for Whisper models).
  final double? confidence;

  /// Who spoke, as shown: a person's name or "Unknown N" for a voice that
  /// matches nobody enrolled. Null when speakers were not identified.
  final String? speaker;
  final String timestampSource;

  /// 'device' for on-device transcripts, 'server' for platform ones.
  final String source;

  /// The enrolled person [speaker] was matched to (`people.client_id`).
  final String? speakerPersonId;

  /// Second voice when [overlap] is set (two people talking at once).
  final String? speaker2;
  final String? speaker2PersonId;

  /// Spoken over another voice: the text comes from the mixed audio and the
  /// speaker attribution is uncertain.
  final bool overlap;

  /// 0..100; how sure the speaker match was. Null when not scored.
  final int? speakerConfidence;

  /// The user chose the speaker; automatic passes never change it.
  final bool speakerManual;

  /// Names of everyone on this line, e.g. `Ali / Sara`; null without speakers.
  String? get speakerLabel {
    final first = speaker;
    if (first == null || first.isEmpty) return null;
    final second = speaker2;
    return second == null || second.isEmpty ? first : '$first / $second';
  }

  /// `Name: text`, or just the text when the speaker is unknown.
  String get labeledText {
    final label = speakerLabel;
    return label == null ? text : '$label: $text';
  }

  Segment copyWith({
    int? startMs,
    int? endMs,
    String? text,
    String? speaker,
    String? speakerPersonId,
    String? speaker2,
    String? speaker2PersonId,
    bool? overlap,
    int? speakerConfidence,
    bool? speakerManual,
    bool clearSpeaker = false,
    bool clearSpeaker2 = false,
    bool clearSpeakerConfidence = false,
  }) => Segment(
    channel: channel,
    startMs: startMs ?? this.startMs,
    endMs: endMs ?? this.endMs,
    text: text ?? this.text,
    confidence: confidence,
    speaker: clearSpeaker ? null : (speaker ?? this.speaker),
    timestampSource: timestampSource,
    source: source,
    speakerPersonId: clearSpeaker
        ? null
        : (speakerPersonId ?? this.speakerPersonId),
    speaker2: clearSpeaker2 ? null : (speaker2 ?? this.speaker2),
    speaker2PersonId: clearSpeaker2
        ? null
        : (speaker2PersonId ?? this.speaker2PersonId),
    overlap: overlap ?? this.overlap,
    speakerConfidence: clearSpeakerConfidence
        ? null
        : (speakerConfidence ?? this.speakerConfidence),
    speakerManual: speakerManual ?? this.speakerManual,
  );

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
    speakerPersonId: row['speaker_person_id'] as String?,
    speaker2: row['speaker2'] as String?,
    speaker2PersonId: row['speaker2_person_id'] as String?,
    overlap: ((row['overlap'] as int?) ?? 0) != 0,
    speakerConfidence: row['speaker_confidence'] as int?,
    speakerManual: ((row['speaker_manual'] as int?) ?? 0) != 0,
  );

  /// Column values for the `segments` table (without id and meeting id).
  Map<String, Object?> toRow() => {
    'channel': channel,
    't_start_ms': startMs,
    't_end_ms': endMs,
    'text': text,
    'confidence': confidence,
    'speaker': speaker,
    'timestamp_source': timestampSource,
    'source': source,
    'speaker_person_id': speakerPersonId,
    'speaker2': speaker2,
    'speaker2_person_id': speaker2PersonId,
    'overlap': overlap ? 1 : 0,
    'speaker_confidence': speakerConfidence,
    'speaker_manual': speakerManual ? 1 : 0,
  };
}
