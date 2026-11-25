import 'package:flutter/material.dart';

/// Shared shell for the recording-screen pickers («نوع جلسه», «حاضران»).
///
/// Both pickers look and behave the same: a title row with an optional
/// trailing action, a search field, a scrollable body that filters by the
/// current query, and a confirm footer. Callers only supply the content.
class SsPickerSheet extends StatefulWidget {
  const SsPickerSheet({
    super.key,
    required this.title,
    this.action,
    required this.searchHint,
    required this.bodyBuilder,
    required this.footer,
  });

  final String title;

  /// Optional trailing control in the title row (for example «افزودن فرد جدید»).
  final Widget? action;

  final String searchHint;

  /// Builds the scrollable body. [scroll] must be attached to the body's
  /// scrollable so the sheet can be dragged; [query] is the trimmed search text.
  final Widget Function(
    BuildContext context,
    ScrollController scroll,
    String query,
  )
  bodyBuilder;

  /// Usually an [SsPickerConfirm].
  final Widget footer;

  @override
  State<SsPickerSheet> createState() => _SsPickerSheetState();
}

class _SsPickerSheetState extends State<SsPickerSheet> {
  String _query = '';

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.75,
      maxChildSize: 0.95,
      builder: (context, scroll) => Column(
        children: [
          Padding(
            padding: const EdgeInsetsDirectional.fromSTEB(16, 0, 16, 8),
            child: Row(
              children: [
                Expanded(
                  child: Text(widget.title, style: theme.textTheme.titleMedium),
                ),
                if (widget.action != null) widget.action!,
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: TextField(
              decoration: InputDecoration(
                prefixIcon: const Icon(Icons.search),
                hintText: widget.searchHint,
              ),
              onChanged: (v) => setState(() => _query = v.trim()),
            ),
          ),
          const SizedBox(height: 8),
          Expanded(child: widget.bodyBuilder(context, scroll, _query)),
          Padding(
            padding: EdgeInsets.only(
              bottom: MediaQuery.viewInsetsOf(context).bottom,
            ),
            child: SafeArea(top: false, child: widget.footer),
          ),
        ],
      ),
    );
  }
}

/// Full-width confirm button of [SsPickerSheet], with an optional error line
/// above it.
class SsPickerConfirm extends StatelessWidget {
  const SsPickerConfirm({
    super.key,
    required this.label,
    required this.onPressed,
    this.error,
  });

  final String label;
  final VoidCallback? onPressed;
  final String? error;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (error != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(
                error!,
                style: TextStyle(color: theme.colorScheme.error),
              ),
            ),
          FilledButton(onPressed: onPressed, child: Text(label)),
        ],
      ),
    );
  }
}

/// Opens an [SsPickerSheet] with the options every picker shares.
Future<T?> showSsPickerSheet<T>(
  BuildContext context,
  WidgetBuilder builder,
) => showModalBottomSheet<T>(
  context: context,
  showDragHandle: true,
  isScrollControlled: true,
  useSafeArea: true,
  builder: builder,
);
