import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sqflite/sqflite.dart';
import 'package:sqflite_common_ffi_web/sqflite_ffi_web.dart';

import 'app/app.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  if (kIsWeb) {
    // Web dev preview only: sqflite has no web backend.
    databaseFactory = databaseFactoryFfiWebNoWebWorker;
  }
  runApp(const ProviderScope(child: JalaseNegarApp()));
}
