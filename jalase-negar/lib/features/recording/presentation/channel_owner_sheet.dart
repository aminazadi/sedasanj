import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/theme.dart';
import '../../people/application/people_providers.dart';
import '../../people/data/person.dart';

/// What the user chose in [showChannelOwnerPicker]: [person] null means
/// "nobody" (the voices on this microphone are recognised automatically).
class OwnerChoice {
  const OwnerChoice(this.person);
  final Person? person;
}

/// Lets the user hand a microphone to a registered person (searchable), or
/// take the assignment away. Returns null when dismissed.
Future<OwnerChoice?> showChannelOwnerPicker(
  BuildContext context, {
  required String channelLabel,
  String? currentPersonId,
}) => showModalBottomSheet<OwnerChoice>(
  context: context,
  showDragHandle: true,
  isScrollControlled: true,
  useSafeArea: true,
  builder: (_) =>
      _OwnerSheet(channelLabel: channelLabel, currentPersonId: currentPersonId),
);

class _OwnerSheet extends ConsumerStatefulWidget {
  const _OwnerSheet({required this.channelLabel, this.currentPersonId});

  final String channelLabel;
  final String? currentPersonId;

  @override
  ConsumerState<_OwnerSheet> createState() => _OwnerSheetState();
}

class _OwnerSheetState extends ConsumerState<_OwnerSheet> {
  String _query = '';

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final people = ref.watch(peopleProvider);
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.7,
      maxChildSize: 0.95,
      builder: (context, scroll) => Column(
        children: [
          Padding(
            padding: const EdgeInsetsDirectional.fromSTEB(16, 0, 16, 8),
            child: Align(
              alignment: AlignmentDirectional.centerStart,
              child: Text(
                'صاحب ${widget.channelLabel}',
                style: theme.textTheme.titleMedium,
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: TextField(
              onChanged: (v) => setState(() => _query = v.trim()),
              decoration: const InputDecoration(
                hintText: 'جست‌وجوی فرد',
                prefixIcon: Icon(Icons.search),
              ),
            ),
          ),
          Expanded(
            child: people.when(
              loading: () => const SizedBox.shrink(),
              error: (_, _) => const Center(
                child: Text('فهرست افراد خوانده نشد؛ دوباره باز کنید.'),
              ),
              data: (all) {
                final shown = [
                  for (final p in all)
                    if (p.voiceprintCount > 0 && p.name.contains(_query)) p,
                ];
                return ListView(
                  controller: scroll,
                  children: [
                    if (widget.currentPersonId != null)
                      ListTile(
                        leading: const Icon(Icons.person_off_outlined),
                        title: const Text('بدون صاحب (تشخیص خودکار)'),
                        onTap: () =>
                            Navigator.of(context).pop(const OwnerChoice(null)),
                      ),
                    for (final p in shown)
                      ListTile(
                        leading: Icon(
                          p.clientId == widget.currentPersonId
                              ? Icons.check
                              : Icons.person_outline,
                          color: SsColors.primary,
                        ),
                        title: Text(p.name),
                        onTap: () => Navigator.of(context).pop(OwnerChoice(p)),
                      ),
                    if (shown.isEmpty)
                      const Padding(
                        padding: EdgeInsets.all(24),
                        child: Center(child: Text('فردی پیدا نشد.')),
                      ),
                  ],
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
