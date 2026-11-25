import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/widgets/ss_picker_sheet.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/platform/api_client.dart';
import '../../recording/application/pending_meeting_type.dart';
import '../../catalog/application/catalog_providers.dart';

/// Lets the user pick the category this meeting will be converted into, before
/// recording starts. "صورت جلسه عمومی" (the builtin type) is always offered
/// and selected by default; picking anything else carries its required field
/// values along. Returns null when dismissed without confirming.
Future<PendingMeetingType?> showMeetingTypePicker(
  BuildContext context, {
  required PendingMeetingType initial,
}) => showSsPickerSheet<PendingMeetingType>(
  context,
  (_) => _MeetingTypePickerSheet(initial: initial),
);

class _MeetingTypePickerSheet extends ConsumerStatefulWidget {
  const _MeetingTypePickerSheet({required this.initial});

  final PendingMeetingType initial;

  @override
  ConsumerState<_MeetingTypePickerSheet> createState() =>
      _MeetingTypePickerSheetState();
}

class _MeetingTypePickerSheetState
    extends ConsumerState<_MeetingTypePickerSheet> {
  late String _selected = widget.initial.code;
  late final Map<String, Map<String, String>> _values = {
    widget.initial.code: {...widget.initial.values},
  };
  String? _error;

  /// Automatic types first, then the rest, in the order the server sent them.
  static List<OutputTypeInfo> _sorted(List<OutputTypeInfo> all) => [
    ...all.where((t) => t.automatic),
    ...all.where((t) => !t.automatic),
  ];

  bool _complete(OutputTypeInfo type) => type.fields.every(
    (f) => !f.required || (_values[type.code]?[f.key] ?? '').trim().isNotEmpty,
  );

  void _confirm(List<OutputTypeInfo> types) {
    final type = types.firstWhere((t) => t.code == _selected);
    if (!_complete(type)) {
      setState(() => _error = 'فیلدهای اجباری «${type.title}» را پر کنید.');
      return;
    }
    final values = {
      for (final e in (_values[_selected] ?? const {}).entries)
        if (e.value.trim().isNotEmpty) e.key: e.value.trim(),
    };
    Navigator.of(context).pop((code: _selected, values: values));
  }

  @override
  Widget build(BuildContext context) {
    final types = ref.watch(meetingTypesProvider);
    final all = types.value;
    return SsPickerSheet(
      title: 'نوع جلسه',
      searchHint: 'جستجوی نوع جلسه',
      bodyBuilder: (context, scroll, query) => types.when(
        loading: () => const Center(child: SsProcessingMark(size: 30)),
        error: (_, _) => const Center(
          child: Padding(
            padding: EdgeInsets.all(24),
            child: Text(
              'فهرست دسته‌ها بارگذاری نشد؛ برگردید و دوباره تلاش کنید.',
              textAlign: TextAlign.center,
            ),
          ),
        ),
        data: (list) {
          final shown = [
            for (final t in _sorted(list))
              if (query.isEmpty ||
                  t.title.contains(query) ||
                  t.description.contains(query))
                t,
          ];
          if (shown.isEmpty) {
            return const Center(
              child: Padding(
                padding: EdgeInsets.all(24),
                child: Text(
                  'نوع جلسه‌ای با این نام پیدا نشد.',
                  textAlign: TextAlign.center,
                ),
              ),
            );
          }
          return ListView.builder(
            controller: scroll,
            padding: const EdgeInsets.symmetric(horizontal: 16),
            itemCount: shown.length,
            itemBuilder: (context, i) {
              final t = shown[i];
              return Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: _MeetingTypeCard(
                  key: ValueKey(t.code),
                  type: t,
                  selected: _selected == t.code,
                  values: _values.putIfAbsent(t.code, () => {}),
                  onSelect: () => setState(() {
                    _selected = t.code;
                    _error = null;
                  }),
                ),
              );
            },
          );
        },
      ),
      footer: SsPickerConfirm(
        label: 'تأیید',
        error: _error,
        onPressed: all == null ? null : () => _confirm(_sorted(all)),
      ),
    );
  }
}

class _MeetingTypeCard extends StatelessWidget {
  const _MeetingTypeCard({
    super.key,
    required this.type,
    required this.selected,
    required this.values,
    required this.onSelect,
  });

  final OutputTypeInfo type;
  final bool selected;
  final Map<String, String> values;
  final VoidCallback onSelect;

  @override
  Widget build(BuildContext context) => SsCard(
    selected: selected,
    onTap: onSelect,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
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
            Icon(
              selected
                  ? Icons.radio_button_checked
                  : Icons.radio_button_unchecked,
              color: selected ? Theme.of(context).colorScheme.primary : null,
            ),
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
