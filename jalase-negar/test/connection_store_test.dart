import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/db/app_database.dart';
import 'package:jalase_negar/core/platform/connection_store.dart';
import 'package:jalase_negar/core/platform/platform_config.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const _channel = MethodChannel('plugins.it_nomads.com/flutter_secure_storage');

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'saving the account survives the macOS keychain refusing to delete (-34018)',
    () async {
      // The macOS plugin's delete queries iCloud-synchronizable items, which needs an entitlement
      // this app does not have, so it fails with -34018 even for a key that does not exist.
      final written = <String, String>{};
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(_channel, (call) async {
            final args = call.arguments as Map<Object?, Object?>;
            switch (call.method) {
              case 'delete':
                throw PlatformException(
                  code: 'Unexpected security result code',
                  message: "A required entitlement isn't present.",
                  details: -34018,
                );
              case 'write':
                written['${args['key']}'] = '${args['value']}';
                return null;
              default:
                return null;
            }
          });
      addTearDown(
        () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(_channel, null),
      );

      sqfliteFfiInit();
      final dir = Directory.systemTemp.createTempSync('cs');
      addTearDown(() => dir.deleteSync(recursive: true));
      final db = await AppDatabase.open(
        '${dir.path}/a.db',
        factory: databaseFactoryFfi,
      );
      addTearDown(db.db.close);

      final store = ConnectionStore(db);
      await store.save(
        const PlatformConnection(
          serverUrl: 'https://example.test',
          userName: 'کاربر',
          tenantName: 'حساب شخصی',
          tokenPrefix: 'jn_abc',
          personal: true,
        ),
        'jn_abc-secret',
      );

      expect(written['platform_token'], 'jn_abc-secret');
      final loaded = await store.load();
      expect(loaded!.serverUrl, 'https://example.test');
      expect(loaded.personal, isTrue);
    },
  );
}
