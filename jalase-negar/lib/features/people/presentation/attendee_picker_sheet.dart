import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../core/utils/format.dart';
import '../application/people_providers.dart';
import '../data/person.dart';
import 'package:jalase_negar/app/widgets/ss_widgets.dart';

/// Lets the user tick the people present in a meeting and add a new person
/// without leaving the flow. Returns the chosen client ids, or null when
/// dismissed.
Future<Set<String>?> showAttendeePicker(
  BuildContext context, {
  required Set<String> selected,
}) => showModalBottomSheet<Set<String>>(
  context: context,
  showDragHandle: true,
  isScrollControlled: true,
  useSafeArea: true,
  builder: (_) => _AttendeePickerSheet(initial: selected),
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
  String _query = '';

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
                  child: Text(
                    'حاضران جلسه',
                    style: theme.textTheme.titleMedium,
                  ),
                ),
                TextButton.icon(
                  onPressed: _addPerson,
                  icon: const Icon(Icons.person_add_alt_1),
                  label: const Text('افزودن فرد جدید'),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: TextField(
              decoration: const InputDecoration(
                prefixIcon: Icon(Icons.search),
                hintText: 'جستجوی نام',
              ),
              onChanged: (v) => setState(() => _query = v.trim()),
            ),
          ),
          const SizedBox(height: 8),
          Expanded(
            child: people.when(
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
                    if (_query.isEmpty || p.name.contains(_query)) p,
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
          ),
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
              child: SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: () => Navigator.of(context).pop(_selected),
                  child: Text(
                    _selected.isEmpty
                        ? 'تأیید'
                        : 'تأیید (${toPersianDigits('${_selected.length}')} نفر)',
                  ),
                ),
              ),
            ),
          ),
        ],
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
      activeColor: SsColors.primary,
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
