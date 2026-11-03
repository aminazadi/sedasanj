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
    final db = await openDatabase(
      path,
      version: 6,
      onConfigure: (db) => db.execute('PRAGMA foreign_keys = ON'),
      onCreate: (db, version) async {
        await _createV4(db);
        await _migrateToV5(db);
        await _migrateToV6(db);
      },
      onUpgrade: (db, oldVersion, newVersion) async {
        if (oldVersion < 4) await _migrateToV4(db);
        if (oldVersion < 5) await _migrateToV5(db);
        if (oldVersion < 6) await _migrateToV6(db);
      },
    );
    _instance = AppDatabase._(db);
    return _instance!;
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
    await db.execute('''
      CREATE TABLE upload_chunks (
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

  Future<String?> getSetting(String key) async {
    final rows = await db.query('settings', where: 'key = ?', whereArgs: [key]);
    return rows.isEmpty ? null : rows.first['value'] as String;
  }

  Future<void> setSetting(String key, String value) => db.insert('settings', {
    'key': key,
    'value': value,
  }, conflictAlgorithm: ConflictAlgorithm.replace);
}
