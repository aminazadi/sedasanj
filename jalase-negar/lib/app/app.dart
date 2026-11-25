import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/providers.dart';
import '../features/app_lock/application/app_lock_providers.dart';
import '../features/push/push_host.dart';
import '../features/plans/store_purchase.dart';
import '../features/plans/store_purchase_store.dart';
import '../features/plans/store_sdk.dart';
import '../features/settings/application/connection_controller.dart';
import '../features/sedasanj_intro/sedasanj_intro_host.dart';
import '../features/updates/application/update_controller.dart';
import '../features/updates/presentation/update_prompt_host.dart';
import 'router.dart';
import 'splash_screen.dart';
import 'theme.dart';
import 'theme_mode_controller.dart';
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
        darkTheme: buildAppTheme(Brightness.dark),
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
        darkTheme: buildAppTheme(Brightness.dark),
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

class _RouterAppState extends ConsumerState<_RouterApp>
    with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // The database is open here, so the self-updater can read the upload
    // backlog. Fire and forget: it never delays the first frame.
    Future<void>.microtask(
      () =>
          ref.read(updateControllerProvider.notifier).startBackgroundUpdates(),
    );
    Future<void>.microtask(_retryPendingStorePurchase);
  }

  /// Finishes a store purchase that was paid but whose confirmation failed
  /// last time, so the person does not have to buy it again.
  Future<void> _retryPendingStorePurchase() async {
    final sdk = currentStoreSdk;
    if (sdk == null) return;
    try {
      final client = await ref.read(personalClientProvider.future);
      final done = await retryPendingPurchase(
        api: client,
        sdk: sdk,
        pending: SecurePendingPurchaseStore(),
      );
      if (!done) return;
      ref
        ..invalidate(usageProvider)
        ..invalidate(personalProfileProvider);
    } on Object {
      // Kept for the next start or a visit to the plan page.
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // `paused` is true backgrounding; `inactive` also fires for transient
    // system overlays (camera/file-picker/share-sheet dialogs, and the
    // biometric prompt itself), which would otherwise re-lock the app out
    // from under the user mid-task.
    if (state == AppLifecycleState.paused &&
        (ref.read(appLockEnabledProvider).value ?? false)) {
      ref.read(appLockRuntimeProvider).lock();
    }
  }

  @override
  Widget build(BuildContext context) {
    final themeMode = ref.watch(themeModeProvider).value ?? ThemeMode.system;
    // Lock immediately once the saved preference resolves after a cold
    // start, so the real screen is never shown even for a single frame.
    ref.listen(appLockEnabledProvider, (previous, next) {
      if (previous == null && (next.value ?? false)) {
        ref.read(appLockRuntimeProvider).lock();
      }
    });
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
      darkTheme: buildAppTheme(Brightness.dark),
      themeMode: themeMode,
      builder: (context, child) => SsToastHost(
        child: PushHost(
          child: UpdatePromptHost(child: SedasanjIntroHost(child: child!)),
        ),
      ),
      routerConfig: ref.watch(routerProvider),
    );
  }
}
