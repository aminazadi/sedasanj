import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/router.dart';
import '../application/update_controller.dart';
import 'update_dialog.dart';

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

class _UpdatePromptHostState extends ConsumerState<UpdatePromptHost> {
  late final GoRouter _router;
  Timer? _poll;
  bool _showing = false;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _router = ref.read(routerProvider);
    _router.routerDelegate.addListener(_schedule);
    WidgetsBinding.instance.addPostFrameCallback((_) => _schedule());
  }

  @override
  void dispose() {
    _router.routerDelegate.removeListener(_schedule);
    _poll?.cancel();
    super.dispose();
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
    if (!ref.read(updateControllerProvider).pending) {
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
