import 'package:sqflite/sqflite.dart';

/// Single sqflite database for meeting metadata and transcript segments.
/// Audio and model binaries live on the filesystem; the DB only holds text
/// and references so it stays tiny and fast.
class AppDatabase {
  AppDatabase._(this.db);

  final Database db;

  static AppDatabase? _instance;

  static Future<AppDatabase> instance() async {
    if (_instance != null) return _instance!;
    final path = '${await getDatabasesPath()}/jalase_negar.db';
    _instance = await open(path);
    return _instance!;
  }

  /// Opens (and migrates) the database at [path]. [factory] lets tests use an
  /// in-process sqlite instead of the platform plugin.
  static Future<AppDatabase> open(
    String path, {
    DatabaseFactory? factory,
  }) async {
    final options = OpenDatabaseOptions(
      version: schemaVersion,
      onConfigure: (db) => db.execute('PRAGMA foreign_keys = ON'),
      onCreate: (db, version) async {
        await _createV4(db);
        await _migrateToV5(db);
        await _migrateToV6(db);
        await _migrateToV7(db);
        await _migrateToV8(db);
        await _migrateToV9(db);
        await _migrateToV10(db);
        await _migrateToV11(db);
      },
      onUpgrade: (db, oldVersion, newVersion) async {
        if (oldVersion < 4) await _migrateToV4(db);
        if (oldVersion < 5) await _migrateToV5(db);
        if (oldVersion < 6) await _migrateToV6(db);
        if (oldVersion < 7) await _migrateToV7(db);
        if (oldVersion < 8) await _migrateToV8(db);
        if (oldVersion < 9) await _migrateToV9(db);
        if (oldVersion < 10) await _migrateToV10(db);
        if (oldVersion < 11) await _migrateToV11(db);
      },
      onOpen: _ensureUploadChunksTable,
    );
    final db = factory == null
        ? await openDatabase(
            path,
            version: options.version,
            onConfigure: options.onConfigure,
            onCreate: options.onCreate,
            onUpgrade: options.onUpgrade,
            onOpen: options.onOpen,
          )
        : await factory.openDatabase(path, options: options);
    return AppDatabase._(db);
  }

  static const int schemaVersion = 11;

  /// Creates the schema as the last app version before people existed (v8).
  /// Only for migration tests.
  static Future<void> createV8ForTest(Database db) async {
    await _createV4(db);
    await _migrateToV5(db);
    await _migrateToV6(db);
    await _migrateToV7(db);
    await _migrateToV8(db);
  }

  static Future<void> _createV4(Database db) async {
    await db.execute('''
      CREATE TABLE meetings (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        duration_ms INTEGER NOT NULL,
        audio_path TEXT NOT NULL,
        sample_rate INTEGER NOT NULL,
        channels INTEGER NOT NULL,
        status TEXT NOT NULL,
        error TEXT
      )
    ''');
    await db.execute('''
      CREATE TABLE segments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
        channel INTEGER NOT NULL,
        t_start_ms INTEGER NOT NULL,
        t_end_ms INTEGER NOT NULL,
        text TEXT NOT NULL
      )
    ''');
    await db.execute(
      'CREATE INDEX IF NOT EXISTS idx_segments_meeting ON segments(meeting_id, t_start_ms)',
    );
    await db.execute('''
      CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
      )
    ''');
  }

  /// v4 drops everything that belonged to on-device analysis: minutes,
  /// LLM transcript corrections, online transcripts and their settings
  /// (including any stored online-AI API key and license data).
  static Future<void> _migrateToV4(Database db) async {
    await db.execute('DROP TABLE IF EXISTS minutes');
    await db.execute('DROP TABLE IF EXISTS minutes_old');
    await db.execute('DROP TABLE IF EXISTS transcript_corrections');
    await db.execute('DROP TABLE IF EXISTS online_transcripts');
    await db.execute(
      "DELETE FROM settings WHERE key IN ('online_ai_config', 'header_config', "
      "'output_config', 'selected_llm_model', 'license_data', "
      "'license_last_check', 'license_first_activation')",
    );
  }

  /// v5 adds the streaming-recording bookkeeping: recording_state lets the
  /// app recover meetings interrupted by a crash, and upload_chunks is the
  /// durable queue of closed WAV chunks waiting for upload.
  static Future<void> _migrateToV5(Database db) async {
    await db.execute(
      "ALTER TABLE meetings ADD COLUMN recording_state TEXT NOT NULL DEFAULT 'finished'",
    );
    await db.execute('ALTER TABLE meetings ADD COLUMN remote_meeting_id TEXT');
    await _ensureUploadChunksTable(db);
  }

  // Some existing databases have the meeting columns but are missing the
  // queue table. Check even when the schema version did not change.
  static Future<void> _ensureUploadChunksTable(Database db) async {
    await db.execute('''
      CREATE TABLE IF NOT EXISTS upload_chunks (
        meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
        seq INTEGER NOT NULL,
        local_path TEXT NOT NULL,
        bytes INTEGER NOT NULL,
        t_start_ms INTEGER NOT NULL,
        t_end_ms INTEGER NOT NULL,
        device_text TEXT,
        sha256 TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at INTEGER,
        last_error_code TEXT,
        PRIMARY KEY (meeting_id, seq)
      )
    ''');
  }

  /// v6 adds the ASR parity contract fields. Segments written before this
  /// version came from the Silero VAD on the device, which the column defaults
  /// describe; asr_identity stays null for them.
  static Future<void> _migrateToV6(Database db) async {
    await db.execute('ALTER TABLE segments ADD COLUMN confidence REAL');
    await db.execute('ALTER TABLE segments ADD COLUMN speaker TEXT');
    await db.execute(
      "ALTER TABLE segments ADD COLUMN timestamp_source TEXT NOT NULL DEFAULT 'silero_vad'",
    );
    await db.execute(
      "ALTER TABLE segments ADD COLUMN source TEXT NOT NULL DEFAULT 'device'",
    );
    await db.execute('ALTER TABLE meetings ADD COLUMN asr_identity TEXT');
  }

  /// v7 adds send_text, the per-meeting snapshot of the "send transcript"
  /// switch. Meetings an older version left mid-upload start over: audio-only
  /// sessions on the server cannot take a transcript.
  static Future<void> _migrateToV7(Database db) async {
    await _ensureUploadChunksTable(db);
    await db.execute(
      'ALTER TABLE meetings ADD COLUMN send_text INTEGER NOT NULL DEFAULT 1',
    );
    await db.execute(
      "UPDATE meetings SET remote_meeting_id = NULL, status = 'recorded' "
      "WHERE status IN ('uploading', 'processing')",
    );
    await db.execute(
      "UPDATE upload_chunks SET status = 'pending', attempts = 0, "
      "next_attempt_at = NULL WHERE meeting_id IN "
      "(SELECT id FROM meetings WHERE status = 'recorded' "
      "AND remote_meeting_id IS NULL)",
    );
  }

  /// v8 adds text_sync_pending: an edit to the text of a meeting already sent
  /// to SedaSanj that the server has not accepted yet.
  static Future<void> _migrateToV8(Database db) async {
    await db.execute(
      'ALTER TABLE meetings ADD COLUMN text_sync_pending INTEGER NOT NULL DEFAULT 0',
    );
  }

  /// v9 adds people and voiceprints (enrolled speakers), the sync outbox that
  /// carries their changes to SedaSanj, and the speaker columns of segments:
  /// who spoke (a person id or a label for an unknown voice), an optional
  /// second speaker for overlapping speech, a 0..100 confidence, and whether
  /// the user set the speaker by hand (a manual choice is never overwritten).
  static Future<void> _migrateToV9(Database db) async {
    await db.execute('''
      CREATE TABLE people (
        client_id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        visibility TEXT NOT NULL DEFAULT 'private',
        version INTEGER NOT NULL DEFAULT 0,
        change_seq INTEGER NOT NULL DEFAULT 0,
        mine INTEGER NOT NULL DEFAULT 1,
        consent_at INTEGER,
        consent_version TEXT,
        updated_at INTEGER NOT NULL
      )
    ''');
    await db.execute('''
      CREATE TABLE voiceprints (
        client_id TEXT PRIMARY KEY,
        person_id TEXT NOT NULL REFERENCES people(client_id) ON DELETE CASCADE,
        model_id TEXT NOT NULL,
        model_version TEXT NOT NULL,
        dim INTEGER NOT NULL,
        embedding BLOB NOT NULL,
        quality INTEGER,
        duration_ms INTEGER,
        created_at INTEGER NOT NULL,
        synced INTEGER NOT NULL DEFAULT 0
      )
    ''');
    await db.execute(
      'CREATE INDEX idx_voiceprints_person ON voiceprints(person_id)',
    );
    await db.execute('''
      CREATE TABLE sync_outbox (
        entity_id TEXT PRIMARY KEY,
        op TEXT NOT NULL,
        rev INTEGER NOT NULL DEFAULT 1,
        removed_voiceprints TEXT NOT NULL DEFAULT '[]',
        attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at INTEGER,
        last_error_code TEXT,
        created_at INTEGER NOT NULL
      )
    ''');
    await db.execute('ALTER TABLE segments ADD COLUMN speaker_person_id TEXT');
    await db.execute('ALTER TABLE segments ADD COLUMN speaker2 TEXT');
    await db.execute('ALTER TABLE segments ADD COLUMN speaker2_person_id TEXT');
    await db.execute(
      'ALTER TABLE segments ADD COLUMN overlap INTEGER NOT NULL DEFAULT 0',
    );
    await db.execute(
      'ALTER TABLE segments ADD COLUMN speaker_confidence INTEGER',
    );
    await db.execute(
      'ALTER TABLE segments ADD COLUMN speaker_manual INTEGER NOT NULL DEFAULT 0',
    );
  }

  /// v10 adds speakers_state: 'pending' or 'analyzing' while the app still
  /// identifies the people of a new recording (the meeting is not sent until
  /// it is 'done'). Existing meetings count as done.
  static Future<void> _migrateToV10(Database db) async {
    await db.execute(
      "ALTER TABLE meetings ADD COLUMN speakers_state TEXT NOT NULL DEFAULT 'done'",
    );
  }

  /// v11 adds meeting_attendees: the people chosen as present before a
  /// recording starts. name_snapshot keeps the name if the person is deleted.
  static Future<void> _migrateToV11(Database db) async {
    await db.execute('''
      CREATE TABLE IF NOT EXISTS meeting_attendees (
        meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
        person_id TEXT NOT NULL,
        name_snapshot TEXT NOT NULL,
        PRIMARY KEY (meeting_id, person_id)
      )
    ''');
  }

  Future<String?> getSetting(String key) async {
    final rows = await db.query('settings', where: 'key = ?', whereArgs: [key]);
    return rows.isEmpty ? null : rows.first['value'] as String;
  }

  Future<void> setSetting(String key, String value) => db.insert('settings', {
    'key': key,
    'value': value,
  }, conflictAlgorithm: ConflictAlgorithm.replace);
}
