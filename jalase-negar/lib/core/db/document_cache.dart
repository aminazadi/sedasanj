import 'package:sqflite/sqflite.dart';

import 'app_database.dart';

/// Documents fetched from the server, kept so they open without a connection.
class DocumentCache {
  DocumentCache(this._db);

  final AppDatabase _db;

  Future<void> cacheDocument({
    required String documentId,
    String? remoteMeetingId,
    required String outputType,
    required String status,
    required int progressPct,
    int? selectedVersion,
    String? markdown,
  }) async {
    await _db.db.insert('document_cache', {
      'document_id': documentId,
      'remote_meeting_id': remoteMeetingId,
      'output_type': outputType,
      'status': status,
      'progress_pct': progressPct,
      'selected_version': selectedVersion,
      'markdown': markdown,
      'updated_at': DateTime.now().millisecondsSinceEpoch,
    }, conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<Map<String, Object?>?> cachedDocument(String documentId) async {
    final rows = await _db.db.query(
      'document_cache',
      where: 'document_id = ?',
      whereArgs: [documentId],
    );
    return rows.isEmpty ? null : rows.first;
  }

  Future<List<Map<String, Object?>>> cachedDocuments(String remoteMeetingId) =>
      _db.db.query(
        'document_cache',
        where: 'remote_meeting_id = ?',
        whereArgs: [remoteMeetingId],
        orderBy: 'updated_at ASC',
      );
}
