import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/router.dart';
import '../../core/db/app_database.dart';
import '../../core/providers.dart';
import '../settings/application/connection_controller.dart';
import 'sedasanj_intro.dart';
import 'sedasanj_intro_sheet.dart';

const _firstUseKey = 'first_use_at';
const _shownKey = 'sedasanj_intro_shown_at';
const _dismissedKey = 'sedasanj_intro_dismissed';

/// Opens the "meet SedaSanj" drawer once per launch at a calm moment (home
/// screen, intro and tour finished, nothing else open) when the user has used
/// the app for a while without connecting it to SedaSanj.
class SedasanjIntroHost extends ConsumerStatefulWidget {
  const SedasanjIntroHost({super.key, required this.child});

  final Widget child;

  @override
  ConsumerState<SedasanjIntroHost> createState() => _SedasanjIntroHostState();
}

class _SedasanjIntroHostState extends ConsumerState<SedasanjIntroHost> {
  late final GoRouter _router;
  Timer? _poll;
  bool _done = false;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _router = ref.read(routerProvider);
    _router.routerDelegate.addListener(_schedule);
    _poll = Timer.periodic(const Duration(seconds: 2), (_) => _schedule());
    WidgetsBinding.instance.addPostFrameCallback((_) => _schedule());
  }

  @override
  void dispose() {
    _router.routerDelegate.removeListener(_schedule);
    _poll?.cancel();
    super.dispose();
  }

  BuildContext? get _calmContext {
    final context = _router.routerDelegate.navigatorKey.currentContext;
    if (context == null || !context.mounted) return null;
    final uri = _router.routerDelegate.currentConfiguration.uri;
    if (uri.path != '/' || uri.queryParameters.containsKey('tour')) return null;
    return Navigator.of(context).canPop() ? null : context;
  }

  Future<void> _schedule() async {
    if (_done) _poll?.cancel();
    if (!mounted || _done || _busy || _calmContext == null) return;
    _busy = true;
    try {
      await _maybeShow();
    } catch (_) {
      // A courtesy prompt: never disturb the app, and do not retry this launch.
      _done = true;
    } finally {
      _busy = false;
    }
  }

  Future<void> _maybeShow() async {
    final connection = ref.read(connectionControllerProvider);
    if (!connection.hasValue) return;
    final db = await ref.read(appDatabaseProvider.future);
    final now = DateTime.now();
    final firstUse = await _firstUse(db, now);
    final lastShown = DateTime.tryParse(await db.getSetting(_shownKey) ?? '');
    final connected = connection.requireValue.connection != null;
    final dismissed = await db.getSetting(_dismissedKey) == '1';
    // Cheap local checks first; the network is only used if the drawer is due.
    if (!shouldShowSedasanjIntro(
      now: now,
      firstUse: firstUse,
      lastShown: lastShown,
      dismissedForever: dismissed,
      connected: connected,
      delayDays: 0,
    )) {
      _done = true;
      return;
    }
    final content = await SedasanjIntroClient().fetch();
    _done = true;
    if (content == null || !mounted) return;
    if (!shouldShowSedasanjIntro(
      now: now,
      firstUse: firstUse,
      lastShown: lastShown,
      dismissedForever: dismissed,
      connected: connected,
      delayDays: content.delayDays,
      enabled: content.enabled,
    )) {
      return;
    }
    final context = _calmContext;
    if (context == null) return;
    await db.setSetting(_shownKey, now.toIso8601String());
    if (!context.mounted) return;
    final known = await showSedasanjIntroSheet(context, content);
    if (known) await db.setSetting(_dismissedKey, '1');
  }

  Future<DateTime> _firstUse(AppDatabase db, DateTime now) async {
    final stored = DateTime.tryParse(await db.getSetting(_firstUseKey) ?? '');
    if (stored != null) return stored;
    await db.setSetting(_firstUseKey, now.toIso8601String());
    return now;
  }

  @override
  Widget build(BuildContext context) => widget.child;
}
