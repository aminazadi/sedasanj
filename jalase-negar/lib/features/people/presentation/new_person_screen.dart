import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../application/people_providers.dart';
import '../data/person.dart';

/// Adds a person in two steps: this page asks for the name and consent, then
/// the voice enrolment (a ring that fills as each text is read) takes over.
/// If the person leaves without any voice stored, the empty person is removed.
class NewPersonScreen extends ConsumerStatefulWidget {
  const NewPersonScreen({super.key, this.returnPerson = false});

  /// When true (opened from the attendee picker) a finished enrolment pops
  /// back with the new person's client id instead of going to the people list.
  final bool returnPerson;

  @override
  ConsumerState<NewPersonScreen> createState() => _NewPersonScreenState();
}

class _NewPersonScreenState extends ConsumerState<NewPersonScreen> {
  final _name = TextEditingController();
  bool _shared = false;
  bool _busy = false;
  String? _message;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  bool get _canContinue => _name.text.trim().isNotEmpty && !_busy;

  Future<void> _continue() async {
    if (!_canContinue) return;
    setState(() {
      _busy = true;
      _message = null;
    });
    final actions = ref.read(peopleActionsProvider);
    Person? person;
    try {
      person = await actions.create(
        name: _name.text.trim(),
        visibility: _shared ? PersonVisibility.org : PersonVisibility.private,
      );
      if (!mounted) return;
      await context.push<void>('/people/${person.clientId}/enroll?return=1');
      if (!mounted) return;
      final stored = (await ref.read(
        peopleProvider.future,
      )).where((p) => p.clientId == person!.clientId).firstOrNull;
      if (stored == null || stored.voiceprintCount == 0) {
        // Nothing was recorded: do not leave a person nobody can be matched to.
        await actions.delete(person.clientId);
        if (!mounted) return;
        setState(() {
          _busy = false;
          _message =
              'صدایی ثبت نشد و فرد ذخیره نشد؛ دوباره «ادامه» را بزنید و متن‌ها را بخوانید.';
        });
        return;
      }
      if (!mounted) return;
      if (widget.returnPerson) {
        context.pop(person.clientId);
      } else {
        context.go('/people/${person.clientId}');
      }
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _message = 'ذخیره‌ی فرد انجام نشد؛ دوباره «ادامه» را بزنید.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: SsAppBar(title: const Text('افزودن فرد')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          SsCard(
            title: 'فرد جدید',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TextField(
                  controller: _name,
                  autofocus: true,
                  maxLength: 80,
                  buildCounter:
                      (
                        context, {
                        required currentLength,
                        required isFocused,
                        required maxLength,
                      }) => null,
                  textInputAction: TextInputAction.done,
                  onChanged: (_) => setState(() {}),
                  onSubmitted: (_) => _continue(),
                  decoration: const InputDecoration(
                    labelText: 'نام فرد',
                    hintText: 'مثلاً علی رضایی',
                  ),
                ),
                const SizedBox(height: 8),
                SsSwitchTile(
                  value: _shared,
                  onChanged: (v) => setState(() => _shared = v),
                  title: const Text('اشتراک با سازمان'),
                ),
              ],
            ),
          ),
          if (_message != null) ...[
            const SizedBox(height: 8),
            Text(
              _message!,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: SsColors.danger,
              ),
            ),
          ],
          const SizedBox(height: 12),
          FilledButton(
            onPressed: _canContinue ? _continue : null,
            child: Text(_busy ? 'لطفاً صبر کنید…' : 'ادامه: ثبت صدا'),
          ),
        ],
      ),
    );
  }
}
