import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/db/app_database.dart';
import 'package:jalase_negar/features/meetings/data/meeting_repository.dart';
import 'package:sqflite/sqflite.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'restores the upload queue table when opening an existing database',
    () async {
      databaseFactory = databaseFactorySqflitePlugin;
      addTearDown(() => databaseFactory = null);
      const channel = MethodChannel('com.tekartik.sqflite');
      final messenger =
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      var hasQueueTable = false;
      messenger.setMockMethodCallHandler(channel, (call) async {
        final sql = (call.arguments as Map?)?['sql'] as String?;
        switch (call.method) {
          case 'getDatabasesPath':
            return '/test/databases';
          case 'openDatabase':
            return {'id': 1};
          case 'execute':
            if (sql!.contains('CREATE TABLE IF NOT EXISTS upload_chunks')) {
              hasQueueTable = true;
            }
            return null;
          case 'query':
            if (sql == 'PRAGMA user_version') {
              return [
                {'user_version': 7},
              ];
            }
            expect(sql, contains('FROM upload_chunks'));
            expect(
              hasQueueTable,
              isTrue,
              reason: 'Recovery reads the queue table',
            );
            return <Map<String, Object?>>[];
          case 'closeDatabase':
            return null;
        }
        throw UnsupportedError(call.method);
      });
      addTearDown(() => messenger.setMockMethodCallHandler(channel, null));

      final database = await AppDatabase.instance();
      addTearDown(database.db.close);

      expect(
        await MeetingRepository(database).chunkRows('interrupted-meeting'),
        isEmpty,
      );
    },
  );
}
