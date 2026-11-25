import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_picker_sheet.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/utils/format.dart';
import '../application/people_providers.dart';
import '../data/person.dart';

/// Lets the user tick the people present in a meeting and add a new person
/// without leaving the flow. Returns the chosen client ids, or null when
/// dismissed.
Future<Set<String>?> showAttendeePicker(
  BuildContext context, {
  required Set<String> selected,
}) => showSsPickerSheet<Set<String>>(
  context,
  (_) => _AttendeePickerSheet(initial: selected),
);

class _AttendeePickerSheet extends ConsumerStatefulWidget {
  const _AttendeePickerSheet({required this.initial});

  final Set<String> initial;

  @override
  ConsumerState<_AttendeePickerSheet> createState() =>
      _AttendeePickerSheetState();
}

class _AttendeePickerSheetState extends ConsumerState<_AttendeePickerSheet> {
  late final Set<String> _selected = {...widget.initial};

  Future<void> _addPerson() async {
    final id = await context.push<String>('/people/new?return=1');
    if (id == null || !mounted) return;
    // The list refreshes from the repository after the save.
    ref.invalidate(peopleProvider);
    setState(() => _selected.add(id));
  }

  @override
  Widget build(BuildContext context) {
    final people = ref.watch(peopleProvider);
    return SsPickerSheet(
      title: 'حاضران جلسه',
      action: TextButton.icon(
        onPressed: _addPerson,
        icon: const Icon(Icons.person_add_alt_1),
        label: const Text('افزودن فرد جدید'),
      ),
      searchHint: 'جستجوی نام',
      bodyBuilder: (context, scroll, query) => people.when(
        loading: () => const Center(child: SsProcessingMark(size: 30)),
        error: (_, _) => const Center(
          child: Padding(
            padding: EdgeInsets.all(24),
            child: Text(
              'فهرست افراد بارگذاری نشد؛ برگردید و دوباره تلاش کنید.',
              textAlign: TextAlign.center,
            ),
          ),
        ),
        data: (all) {
          final shown = [
            for (final p in all)
              if (query.isEmpty || p.name.contains(query)) p,
          ];
          if (shown.isEmpty) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Text(
                  all.isEmpty
                      ? 'هنوز فردی ثبت نشده؛ با «افزودن فرد جدید» شروع کنید.'
                      : 'فردی با این نام پیدا نشد.',
                  textAlign: TextAlign.center,
                ),
              ),
            );
          }
          return ListView.builder(
            controller: scroll,
            itemCount: shown.length,
            itemBuilder: (context, i) => _PersonCheckTile(
              person: shown[i],
              checked: _selected.contains(shown[i].clientId),
              onChanged: (on) => setState(() {
                if (on) {
                  _selected.add(shown[i].clientId);
                } else {
                  _selected.remove(shown[i].clientId);
                }
              }),
            ),
          );
        },
      ),
      footer: SsPickerConfirm(
        label: _selected.isEmpty
            ? 'تأیید'
            : 'تأیید (${toPersianDigits('${_selected.length}')} نفر)',
        onPressed: () => Navigator.of(context).pop(_selected),
      ),
    );
  }
}

class _PersonCheckTile extends StatelessWidget {
  const _PersonCheckTile({
    required this.person,
    required this.checked,
    required this.onChanged,
  });

  final Person person;
  final bool checked;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    return CheckboxListTile(
      value: checked,
      onChanged: (v) => onChanged(v ?? false),
      controlAffinity: ListTileControlAffinity.trailing,
      activeColor: SsColors.of(context).primary,
      secondary: CircleAvatar(
        child: Text(person.name.isEmpty ? '؟' : person.name.characters.first),
      ),
      title: Text(person.name),
      subtitle: person.voiceprintCount == 0
          ? const Text('نمونهٔ صدا ثبت نشده')
          : null,
    );
  }
}
