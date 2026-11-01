import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/providers.dart';
import 'router.dart';
import 'theme.dart';

class JalaseNegarApp extends ConsumerWidget {
  const JalaseNegarApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final dbAsync = ref.watch(appDatabaseProvider);

    return dbAsync.when(
      loading: () => MaterialApp(
        theme: buildAppTheme(),
        home: const Scaffold(body: Center(child: CircularProgressIndicator())),
      ),
      error: (e, _) => MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(body: Center(child: Text('خطا در راه‌اندازی: $e'))),
      ),
      data: (_) => const _RouterApp(),
    );
  }
}

class _RouterApp extends ConsumerWidget {
  const _RouterApp();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return MaterialApp.router(
      title: 'جلسه‌نگار',
      debugShowCheckedModeBanner: false,
      locale: const Locale('fa'),
      supportedLocales: const [Locale('fa')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      theme: buildAppTheme(),
      routerConfig: ref.watch(routerProvider),
    );
  }
}
