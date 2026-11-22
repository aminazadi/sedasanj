import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../../../app/widgets/markdown_view.dart';
import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/platform/api_client.dart';
import '../../settings/application/connection_controller.dart';

String _errorText(Object error) => error is ApiException
    ? error.message
    : 'ارتباط با سرور برقرار نشد؛ اینترنت را بررسی کنید و دوباره تلاش کنید.';

String _statusLabel(DocumentInfo d) => switch (d.status) {
  'queued' => 'در صف',
  'running' => 'در حال ساخت (${d.progressPct}٪)',
  'failed' => 'ناموفق',
  _ => 'آماده',
};

/// Documents (counseling report, lecture notes, ...) made from one meeting.
class DocumentsTab extends ConsumerStatefulWidget {
  const DocumentsTab({super.key, required this.remoteMeetingId});

  final String remoteMeetingId;

  @override
  ConsumerState<DocumentsTab> createState() => _DocumentsTabState();
}

class _DocumentsTabState extends ConsumerState<DocumentsTab> {
  Timer? _poll;

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  void _refresh() =>
      ref.invalidate(meetingDocumentsProvider(widget.remoteMeetingId));

  /// While any document is still being made, check again every few seconds.
  void _schedulePoll(bool pending) {
    if (!pending) {
      _poll?.cancel();
      _poll = null;
    } else {
      _poll ??= Timer.periodic(const Duration(seconds: 4), (_) {
        if (mounted) _refresh();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final docs = ref.watch(meetingDocumentsProvider(widget.remoteMeetingId));
    final titles = {
      for (final t
          in ref.watch(outputTypesProvider).value ?? const <OutputTypeInfo>[])
        t.code: t.title,
    };
    return docs.when(
      skipLoadingOnReload: true,
      loading: () => const Center(child: SsProcessingMark(size: 30)),
      error: (error, _) => _Message(
        message: _errorText(error),
        action: 'بررسی دوباره',
        onTap: _refresh,
      ),
      data: (items) {
        WidgetsBinding.instance.addPostFrameCallback(
          (_) => _schedulePoll(items.any((d) => d.inProgress)),
        );
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            FilledButton.icon(
              icon: const Icon(Icons.add),
              label: const Text('ساخت سند در دستهٔ دیگر'),
              onPressed: () async {
                final made = await showModalBottomSheet<bool>(
                  context: context,
                  isScrollControlled: true,
                  showDragHandle: true,
                  builder: (_) => CategoryPickerSheet(
                    remoteMeetingId: widget.remoteMeetingId,
                    existing: {for (final d in items) d.outputType},
                  ),
                );
                if (made == true) _refresh();
              },
            ),
            const SizedBox(height: 12),
            if (items.isEmpty)
              const Text(
                'هنوز سندی در دسته‌های دیگر ساخته نشده است؛ «ساخت سند» را بزنید و دسته‌ها را انتخاب کنید.',
              ),
            for (final d in items)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: SsCard(
                  onTap: () => Navigator.of(context).push<void>(
                    MaterialPageRoute(
                      builder: (_) => DocumentScreen(
                        documentId: d.id,
                        title: titles[d.outputType] ?? d.outputType,
                      ),
                    ),
                  ),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(
                          titles[d.outputType] ?? d.outputType,
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                      ),
                      SsBadge(_statusLabel(d)),
                    ],
                  ),
                ),
              ),
          ],
        );
      },
    );
  }
}

class _Message extends StatelessWidget {
  const _Message({
    required this.message,
    required this.action,
    required this.onTap,
  });

  final String message;
  final String action;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(message, textAlign: TextAlign.center),
          const SizedBox(height: 12),
          OutlinedButton(onPressed: onTap, child: Text(action)),
        ],
      ),
    ),
  );
}

/// Pick one or more categories, fill their inputs, and start the documents.
class CategoryPickerSheet extends ConsumerStatefulWidget {
  const CategoryPickerSheet({
    super.key,
    required this.remoteMeetingId,
    this.existing = const {},
  });

  final String remoteMeetingId;

  /// Categories this meeting already has a document for.
  final Set<String> existing;

  @override
  ConsumerState<CategoryPickerSheet> createState() =>
      _CategoryPickerSheetState();
}

class _CategoryPickerSheetState extends ConsumerState<CategoryPickerSheet> {
  final _selected = <String>{};
  final _values = <String, Map<String, String>>{};
  bool _busy = false;
  String? _error;

  bool _complete(OutputTypeInfo type) => type.fields.every(
    (f) => !f.required || (_values[type.code]?[f.key] ?? '').trim().isNotEmpty,
  );

  Future<void> _submit(List<OutputTypeInfo> types) async {
    final chosen = [
      for (final t in types)
        if (_selected.contains(t.code)) t,
    ];
    final missing = chosen.where((t) => !_complete(t)).toList();
    if (missing.isNotEmpty) {
      setState(
        () => _error = 'فیلدهای اجباری «${missing.first.title}» را پر کنید.',
      );
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final client = await ref.read(personalClientProvider.future);
      await client.createDocuments(widget.remoteMeetingId, [
        for (final t in chosen)
          (
            code: t.code,
            values: {
              for (final e in (_values[t.code] ?? <String, String>{}).entries)
                if (e.value.trim().isNotEmpty) e.key: e.value.trim(),
            },
          ),
      ]);
      if (mounted) Navigator.of(context).pop(true);
    } on Object catch (e) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = _errorText(e);
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final types = ref.watch(outputTypesProvider);
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.only(
          bottom: MediaQuery.viewInsetsOf(context).bottom,
        ),
        child: types.when(
          loading: () => const SizedBox(
            height: 160,
            child: Center(child: SsProcessingMark(size: 30)),
          ),
          error: (e, _) => Padding(
            padding: const EdgeInsets.all(24),
            child: Text(_errorText(e)),
          ),
          data: (all) {
            final available = [
              for (final t in all)
                if (!widget.existing.contains(t.code)) t,
            ];
            if (available.isEmpty) {
              return const Padding(
                padding: EdgeInsets.all(24),
                child: Text('دستهٔ دیگری برای ساخت سند در دسترس نیست.'),
              );
            }
            return Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Flexible(
                  child: ListView(
                    shrinkWrap: true,
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    children: [
                      for (final t in available) ...[
                        _CategoryCard(
                          type: t,
                          selected: _selected.contains(t.code),
                          values: _values.putIfAbsent(t.code, () => {}),
                          onToggle: (on) => setState(
                            () => on
                                ? _selected.add(t.code)
                                : _selected.remove(t.code),
                          ),
                        ),
                        const SizedBox(height: 8),
                      ],
                    ],
                  ),
                ),
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                    child: Text(
                      _error!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ),
                Padding(
                  padding: const EdgeInsets.all(16),
                  child: FilledButton(
                    onPressed: _busy || _selected.isEmpty
                        ? null
                        : () => _submit(available),
                    child: Text(
                      _busy
                          ? 'در حال ارسال…'
                          : 'ساخت سند (${_selected.length})',
                    ),
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _CategoryCard extends StatelessWidget {
  const _CategoryCard({
    required this.type,
    required this.selected,
    required this.values,
    required this.onToggle,
  });

  final OutputTypeInfo type;
  final bool selected;
  final Map<String, String> values;
  final ValueChanged<bool> onToggle;

  @override
  Widget build(BuildContext context) => SsCard(
    selected: selected,
    onTap: () => onToggle(!selected),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            if (type.thumbnailUrl != null)
              Padding(
                padding: const EdgeInsetsDirectional.only(end: 12),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(8),
                  child: Image.network(
                    type.thumbnailUrl!,
                    width: 56,
                    height: 56,
                    fit: BoxFit.cover,
                    errorBuilder: (_, _, _) =>
                        const SizedBox(width: 56, height: 56),
                  ),
                ),
              ),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    type.title,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  if (type.description.isNotEmpty)
                    Text(
                      type.description,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                ],
              ),
            ),
            Checkbox(value: selected, onChanged: (v) => onToggle(v ?? false)),
          ],
        ),
        if (selected)
          for (final f in type.fields)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: f.type == 'select'
                  ? DropdownButtonFormField<String>(
                      initialValue: values[f.key],
                      decoration: InputDecoration(
                        labelText: f.required ? '${f.label} *' : f.label,
                      ),
                      items: [
                        for (final o in f.options)
                          DropdownMenuItem(value: o, child: Text(o)),
                      ],
                      onChanged: (v) => values[f.key] = v ?? '',
                    )
                  : TextFormField(
                      initialValue: values[f.key],
                      keyboardType: f.type == 'number'
                          ? TextInputType.number
                          : TextInputType.text,
                      decoration: InputDecoration(
                        labelText: f.required ? '${f.label} *' : f.label,
                      ),
                      onChanged: (v) => values[f.key] = v,
                    ),
            ),
      ],
    ),
  );
}

/// One document: read, copy, share, edit (a new version) and make again.
class DocumentScreen extends ConsumerStatefulWidget {
  const DocumentScreen({
    super.key,
    required this.documentId,
    required this.title,
  });

  final String documentId;
  final String title;

  @override
  ConsumerState<DocumentScreen> createState() => _DocumentScreenState();
}

class _DocumentScreenState extends ConsumerState<DocumentScreen> {
  Timer? _poll;
  bool _editing = false;
  bool _busy = false;
  final _controller = TextEditingController();

  @override
  void dispose() {
    _poll?.cancel();
    _controller.dispose();
    super.dispose();
  }

  void _refresh() => ref.invalidate(documentDetailProvider(widget.documentId));

  Future<void> _act(
    Future<void> Function(ApiClient client) action,
    String done,
  ) async {
    setState(() => _busy = true);
    try {
      await action(await ref.read(personalClientProvider.future));
      _refresh();
      if (mounted) SsToastHost.show(context, done);
    } on Object catch (e) {
      if (mounted) SsToastHost.show(context, _errorText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Downloads the PDF or Word file and opens the system share sheet with it.
  Future<void> _export(String format) async {
    setState(() => _busy = true);
    try {
      final client = await ref.read(personalClientProvider.future);
      final bytes = await client.exportDocument(widget.documentId, format);
      final dir = await getTemporaryDirectory();
      final file = File('${dir.path}/jalase-${widget.documentId}.$format');
      await file.writeAsBytes(bytes, flush: true);
      await SharePlus.instance.share(
        ShareParams(
          files: [
            XFile(
              file.path,
              mimeType: format == 'pdf'
                  ? 'application/pdf'
                  : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            ),
          ],
          title: widget.title,
        ),
      );
    } on Object catch (e) {
      if (mounted) SsToastHost.show(context, _errorText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final detail = ref.watch(documentDetailProvider(widget.documentId));
    final markdown = detail.value?.markdown;
    final info = detail.value?.info;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (info?.inProgress == true) {
        _poll ??= Timer.periodic(const Duration(seconds: 4), (_) {
          if (mounted) _refresh();
        });
      } else {
        _poll?.cancel();
        _poll = null;
      }
    });
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.title),
        actions: [
          if (markdown != null && !_editing) ...[
            IconButton(
              tooltip: 'کپی',
              icon: const Icon(Icons.copy),
              onPressed: () async {
                await Clipboard.setData(ClipboardData(text: markdown));
                if (context.mounted) SsToastHost.show(context, 'سند کپی شد.');
              },
            ),
            IconButton(
              tooltip: 'اشتراک‌گذاری',
              icon: const Icon(Icons.ios_share),
              onPressed: () =>
                  SharePlus.instance.share(ShareParams(text: markdown)),
            ),
            PopupMenuButton<String>(
              tooltip: 'دریافت فایل',
              icon: const Icon(Icons.download),
              enabled: !_busy,
              onSelected: _export,
              itemBuilder: (_) => const [
                PopupMenuItem(value: 'pdf', child: Text('PDF')),
                PopupMenuItem(value: 'docx', child: Text('Word')),
              ],
            ),
            IconButton(
              tooltip: 'ویرایش',
              icon: const Icon(Icons.edit),
              onPressed: () {
                _controller.text = markdown;
                setState(() => _editing = true);
              },
            ),
          ],
        ],
      ),
      body: detail.when(
        skipLoadingOnReload: true,
        loading: () => const Center(child: SsProcessingMark(size: 30)),
        error: (e, _) => Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text(_errorText(e)),
          ),
        ),
        data: (d) {
          if (d.info.inProgress) {
            return Center(
              child: Text('در حال ساخت سند… ${d.info.progressPct}٪'),
            );
          }
          if (d.markdown == null || d.info.status == 'failed') {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Text(
                      'ساخت سند ناموفق بود؛ «ساخت دوباره» را بزنید. اگر ادامه داشت، بعداً دوباره تلاش کنید.',
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 12),
                    FilledButton(
                      onPressed: _busy
                          ? null
                          : () => _act(
                              (c) => c.regenerateDocument(widget.documentId),
                              'ساخت دوباره شروع شد.',
                            ),
                      child: const Text('ساخت دوباره'),
                    ),
                  ],
                ),
              ),
            );
          }
          if (_editing) {
            return Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _controller,
                      maxLines: null,
                      expands: true,
                      textAlignVertical: TextAlignVertical.top,
                      decoration: const InputDecoration(
                        border: OutlineInputBorder(),
                      ),
                    ),
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton(
                          onPressed: _busy
                              ? null
                              : () => setState(() => _editing = false),
                          child: const Text('انصراف'),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: FilledButton(
                          onPressed: _busy || _controller.text.trim().isEmpty
                              ? null
                              : () async {
                                  await _act(
                                    (c) => c.editDocument(
                                      widget.documentId,
                                      _controller.text,
                                    ),
                                    'نسخهٔ جدید ذخیره شد.',
                                  );
                                  if (mounted) setState(() => _editing = false);
                                },
                          child: const Text('ذخیره'),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            );
          }
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              MarkdownView(markdown: d.markdown!),
              const SizedBox(height: 16),
              OutlinedButton.icon(
                icon: const Icon(Icons.refresh),
                label: const Text('ساخت دوباره (نسخهٔ جدید)'),
                onPressed: _busy
                    ? null
                    : () => _act(
                        (c) => c.regenerateDocument(widget.documentId),
                        'ساخت دوباره شروع شد.',
                      ),
              ),
            ],
          );
        },
      ),
    );
  }
}
