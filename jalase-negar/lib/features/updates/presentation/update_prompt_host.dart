import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/router.dart';
import '../../../app/widgets/ss_toast.dart';
import '../application/update_background.dart';
import '../application/update_controller.dart';
import 'update_dialog.dart';
import 'update_permission_dialog.dart';

/// Shows the update dialog at a calm moment: on the home screen, with the
/// intro and guided tour finished, and nothing else open on top. While the
/// user records, is in the tour, or has another dialog up, the offer waits and
/// appears once they are back on the home screen.
class UpdatePromptHost extends ConsumerStatefulWidget {
  const UpdatePromptHost({super.key, required this.child});

  final Widget child;

  @override
  ConsumerState<UpdatePromptHost> createState() => _UpdatePromptHostState();
}

class _UpdatePromptHostState extends ConsumerState<UpdatePromptHost>
    with WidgetsBindingObserver {
  late final GoRouter _router;
  Timer? _poll;
  bool _showing = false;
  bool _failed = false;

  /// The post-update toast and the one-time permission explainer ran.
  bool _introduced = false;

  @override
  void initState() {
    super.initState();
    _router = ref.read(routerProvider);
    _router.routerDelegate.addListener(_schedule);
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) => _schedule());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _router.routerDelegate.removeListener(_schedule);
    _poll?.cancel();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Leaving the app is the calm moment the installer waits for: publish the
    // latest state and let the worker apply a downloaded update.
    if (state == AppLifecycleState.paused) {
      unawaited(ref.read(updateControllerProvider.notifier).onAppPaused());
    }
  }

  /// Once per launch, at the first calm moment: a quiet "updated" toast after
  /// an update, then (only if never answered) the permission explainer.
  Future<void> _introduce() async {
    final context = _router.routerDelegate.navigatorKey.currentContext;
    if (context == null || !context.mounted) return;
    final native = ref.read(updateNativeProvider);
    try {
      final from = await native.consumeUpdatedFrom();
      if (from != null && context.mounted) {
        unawaited(SsToastHost.show(context, 'جلسه‌نگار به‌روز شد.'));
      }
      final unanswered = !await native.explainerShown();
      if (unanswered && context.mounted) {
        await showUpdatePermissionDialog(context, native);
      }
    } catch (_) {
      // Purely cosmetic; never block the app.
    }
  }

  bool get _calm {
    final context = _router.routerDelegate.navigatorKey.currentContext;
    if (context == null || !context.mounted) return false;
    final uri = _router.routerDelegate.currentConfiguration.uri;
    if (uri.path != '/' || uri.queryParameters.containsKey('tour')) {
      return false;
    }
    // Any dialog or pushed screen makes the root navigator poppable.
    return !Navigator.of(context).canPop();
  }

  void _schedule() {
    if (!mounted || _showing || _failed) return;
    if (!_introduced && _calm) {
      _introduced = true;
      unawaited(_introduce());
    }
    if (!ref.read(updateControllerProvider).pending) {
      if (!_introduced) {
        _poll ??= Timer.periodic(const Duration(milliseconds: 700), (_) {
          _schedule();
        });
        return;
      }
      _poll?.cancel();
      _poll = null;
      return;
    }
    if (_calm) {
      _poll?.cancel();
      _poll = null;
      unawaited(_show());
      return;
    }
    // Dialogs open and close without notifying the router, so keep looking.
    _poll ??= Timer.periodic(const Duration(milliseconds: 700), (_) {
      _schedule();
    });
  }

  Future<void> _show() async {
    final context = _router.routerDelegate.navigatorKey.currentContext;
    if (context == null) return;
    _showing = true;
    try {
      await showUpdateDialog(context);
    } catch (error, stack) {
      // Report once and stop prompting: retrying a broken dialog would only spin.
      _failed = true;
      FlutterError.reportError(
        FlutterErrorDetails(
          exception: error,
          stack: stack,
          library: 'update prompt',
        ),
      );
    } finally {
      _showing = false;
      // Give the navigator a moment before looking again (for example after
      // "later" the offer is no longer pending and this returns at once).
      if (mounted && !_failed) {
        _poll ??= Timer(const Duration(milliseconds: 300), () {
          _poll = null;
          _schedule();
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    ref.listen(updateControllerProvider.select((s) => s.pending), (_, now) {
      if (now) _schedule();
    });
    return widget.child;
  }
}
