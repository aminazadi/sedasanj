import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/providers.dart';
import '../features/updates/application/update_controller.dart';
import '../features/updates/presentation/update_prompt_host.dart';
import 'router.dart';
import 'splash_screen.dart';
import 'theme.dart';
import 'widgets/ss_toast.dart';

class JalaseNegarApp extends ConsumerStatefulWidget {
  const JalaseNegarApp({super.key});

  @override
  ConsumerState<JalaseNegarApp> createState() => _JalaseNegarAppState();
}

class _JalaseNegarAppState extends ConsumerState<JalaseNegarApp> {
  bool _splashDone = false;

  @override
  void initState() {
    super.initState();
    // Fire and forget: the splash, recording and sign-in never wait for the network.
    Future<void>.microtask(
      () => ref.read(updateControllerProvider.notifier).checkOnLaunch(),
    );
  }

  @override
  Widget build(BuildContext context) {
    final dbAsync = ref.watch(appDatabaseProvider);

    // The splash stays until its logo animation has finished, even when the
    // database is ready sooner; a start-up error replaces it immediately.
    if (!dbAsync.hasError && (dbAsync.isLoading || !_splashDone)) {
      return MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: buildAppTheme(),
        home: SplashScreen(
          onComplete: () =>
              Future<void>.delayed(const Duration(milliseconds: 300), () {
                if (mounted) setState(() => _splashDone = true);
              }),
        ),
      );
    }

    return dbAsync.when(
      loading: () => const SizedBox.shrink(),
      error: (e, _) => MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(body: Center(child: Text('خطا در راه‌اندازی: $e'))),
      ),
      data: (_) => const _RouterApp(),
    );
  }
}

class _RouterApp extends ConsumerStatefulWidget {
  const _RouterApp();

  @override
  ConsumerState<_RouterApp> createState() => _RouterAppState();
}

class _RouterAppState extends ConsumerState<_RouterApp> {
  @override
  void initState() {
    super.initState();
    // The database is open here, so the self-updater can read the upload
    // backlog. Fire and forget: it never delays the first frame.
    Future<void>.microtask(
      () =>
          ref.read(updateControllerProvider.notifier).startBackgroundUpdates(),
    );
  }

  @override
  Widget build(BuildContext context) {
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
      builder: (context, child) =>
          SsToastHost(child: UpdatePromptHost(child: child!)),
      routerConfig: ref.watch(routerProvider),
    );
  }
}
