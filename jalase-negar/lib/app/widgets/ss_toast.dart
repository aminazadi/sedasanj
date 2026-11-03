import 'dart:async';
import 'dart:collection';

import 'package:flutter/material.dart';

enum SsToastResult { action, dismissed, disposed }

enum SsToastQueue { append, dismissCurrent, clear }

/// Keeps transient messages below the top toolbar across route changes.
class SsToastHost extends StatefulWidget {
  const SsToastHost({super.key, required this.child});

  final Widget child;

  static Future<SsToastResult> show(
    BuildContext context,
    String message, {
    String? actionLabel,
    Duration duration = const Duration(seconds: 4),
    SsToastQueue queue = SsToastQueue.append,
  }) {
    final host = context.findAncestorStateOfType<_SsToastHostState>()!;
    final toast = _Toast(message, actionLabel, duration);
    host._show(toast, queue);
    return toast.result.future;
  }

  @override
  State<SsToastHost> createState() => _SsToastHostState();
}

class _SsToastHostState extends State<SsToastHost> {
  final _waiting = Queue<_Toast>();
  _Toast? _current;
  Timer? _timer;
  bool _accessibleNavigation = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final accessibleNavigation = MediaQuery.accessibleNavigationOf(context);
    if (accessibleNavigation != _accessibleNavigation) {
      _accessibleNavigation = accessibleNavigation;
      _armTimer();
    }
  }

  void _show(_Toast toast, SsToastQueue queue) {
    setState(() {
      if (queue == SsToastQueue.clear) {
        while (_waiting.isNotEmpty) {
          _waiting.removeFirst().result.complete(SsToastResult.dismissed);
        }
      }
      if (queue != SsToastQueue.append) {
        _current?.result.complete(SsToastResult.dismissed);
        _current = null;
      }
      _waiting.addLast(toast);
      if (_current == null) _advance();
    });
  }

  void _advance() {
    _current = _waiting.isEmpty ? null : _waiting.removeFirst();
    _armTimer();
  }

  void _armTimer() {
    _timer?.cancel();
    final toast = _current;
    if (toast == null || (_accessibleNavigation && toast.actionLabel != null)) {
      return;
    }
    _timer = Timer(
      toast.duration,
      () => _finish(toast, SsToastResult.dismissed),
    );
  }

  void _finish(_Toast toast, SsToastResult result) {
    if (!identical(_current, toast)) return;
    toast.result.complete(result);
    setState(_advance);
  }

  @override
  void dispose() {
    _timer?.cancel();
    _current?.result.complete(SsToastResult.disposed);
    for (final toast in _waiting) {
      toast.result.complete(SsToastResult.disposed);
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final toast = _current;
    return Stack(
      fit: StackFit.expand,
      children: [
        widget.child,
        if (toast != null)
          Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: SafeArea(
              bottom: false,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(
                  14,
                  kToolbarHeight + 8,
                  14,
                  0,
                ),
                child: Align(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 560),
                    child: _ToastCard(
                      key: ObjectKey(toast),
                      toast: toast,
                      onDismiss: () => _finish(toast, SsToastResult.dismissed),
                      onAction: () => _finish(toast, SsToastResult.action),
                    ),
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }
}

class _Toast {
  _Toast(this.message, this.actionLabel, this.duration);

  final String message;
  final String? actionLabel;
  final Duration duration;
  final result = Completer<SsToastResult>();
}

class _ToastCard extends StatelessWidget {
  const _ToastCard({
    super.key,
    required this.toast,
    required this.onDismiss,
    required this.onAction,
  });

  final _Toast toast;
  final VoidCallback onDismiss;
  final VoidCallback onAction;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final style = theme.snackBarTheme;
    return Dismissible(
      key: ObjectKey(toast),
      direction: DismissDirection.up,
      resizeDuration: null,
      onDismissed: (_) => onDismiss(),
      child: Semantics(
        liveRegion: true,
        onDismiss: onDismiss,
        child: Material(
          color: style.backgroundColor ?? theme.colorScheme.inverseSurface,
          shape: style.shape,
          elevation: style.elevation ?? 0,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 32),
              child: Row(
                children: [
                  Expanded(
                    child: Text(toast.message, style: style.contentTextStyle),
                  ),
                  if (toast.actionLabel case final label?)
                    TextButton(
                      style: TextButton.styleFrom(
                        foregroundColor: theme.colorScheme.onInverseSurface,
                      ),
                      onPressed: onAction,
                      child: Text(label),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
