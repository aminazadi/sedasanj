import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/widgets/ss_widgets.dart';
import '../application/people_providers.dart';
import '../data/person.dart';

/// First step of adding a person: name and sharing. The explicit consent
/// screen follows, and the person is only created once it was accepted.
class NewPersonScreen extends ConsumerStatefulWidget {
  const NewPersonScreen({super.key});

  @override
  ConsumerState<NewPersonScreen> createState() => _NewPersonScreenState();
}

class _NewPersonScreenState extends ConsumerState<NewPersonScreen> {
  final _name = TextEditingController();
  bool _shared = false;
  bool _busy = false;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  Future<void> _continue() async {
    final name = _name.text.trim();
    if (name.isEmpty) return;
    final accepted = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => ConsentScreen(name: name, shared: _shared)),
    );
    if (accepted != true || !mounted) return;
    setState(() => _busy = true);
    final person = await ref
        .read(peopleActionsProvider)
        .create(
          name: name,
          visibility: _shared ? PersonVisibility.org : PersonVisibility.private,
        );
    if (!mounted) return;
    context.pushReplacement('/people/${person.clientId}/enroll');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: SsAppBar(title: const Text('افزودن فرد')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          SsCard(
            title: 'مشخصات',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TextField(
                  controller: _name,
                  autofocus: true,
                  maxLength: 80,
                  textInputAction: TextInputAction.done,
                  onChanged: (_) => setState(() {}),
                  decoration: const InputDecoration(
                    labelText: 'نام فرد',
                    hintText: 'مثلاً علی رضایی',
                  ),
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  value: _shared,
                  onChanged: (v) => setState(() => _shared = v),
                  title: const Text('اشتراک با سازمان'),
                  subtitle: const Text(
                    'اگر روشن باشد، همکاران متصل به همین سازمان هم می‌توانند از این صدا برای تشخیص گوینده استفاده کنند؛ ویرایش یا حذف فقط با شماست. به‌طور پیش‌فرض فقط برای خودتان است.',
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: _name.text.trim().isEmpty || _busy ? null : _continue,
            child: const Text('ادامه: رضایت‌نامه'),
          ),
        ],
      ),
    );
  }
}

/// Explicit, separate consent for storing a voiceprint. Pops `true` only when
/// the person themselves agreed.
class ConsentScreen extends StatefulWidget {
  const ConsentScreen({super.key, required this.name, required this.shared});

  final String name;
  final bool shared;

  @override
  State<ConsentScreen> createState() => _ConsentScreenState();
}

class _ConsentScreenState extends State<ConsentScreen> {
  bool _agreed = false;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    Widget point(String title, String body) => Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: theme.textTheme.titleSmall),
          const SizedBox(height: 2),
          Text(body, style: theme.textTheme.bodyMedium),
        ],
      ),
    );
    return Scaffold(
      appBar: SsAppBar(title: const Text('رضایت‌نامه‌ی ثبت صدا')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          SsCard(
            title: 'ثبت ردصدای «${widget.name}»',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                point(
                  'چه چیزی ذخیره می‌شود؟',
                  'از صدای خوانده‌شده یک «ردصدا» ساخته می‌شود؛ فهرستی از عددها که '
                      'برای شناسایی گوینده کافی است. فایل صوتی ثبت‌نام ذخیره نمی‌شود.',
                ),
                point(
                  'برای چه؟',
                  'فقط برای اینکه در جلسه‌ها نام این فرد کنار گفته‌هایش نوشته شود.',
                ),
                point(
                  'کجا نگهداری می‌شود؟',
                  'روی همین گوشی، رمزشده. اگر اپ به صداسنج وصل باشد، نسخه‌ی رمزشده‌ی '
                      'آن در سرور سازمان شما هم نگه‌داری می‌شود تا روی گوشی دیگر شما '
                      'برگردد. ${widget.shared ? 'چون «اشتراک با سازمان» روشن است، همکاران متصل به سازمان هم می‌توانند از آن برای تشخیص گوینده استفاده کنند.' : 'فقط شما به آن دسترسی دارید.'}',
                ),
                point(
                  'چطور حذف می‌شود؟',
                  'هر زمان از صفحه‌ی همین فرد در «افراد و صدا»؛ نام و ردصدا از گوشی، '
                      'سرور و گوشی‌های دیگر شما پاک می‌شود. متن جلسه‌های قبلی با همان نامی که '
                      'نوشته شده می‌ماند و می‌توانید ویرایشش کنید.',
                ),
                const Divider(),
                CheckboxListTile(
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                  value: _agreed,
                  onChanged: (v) => setState(() => _agreed = v ?? false),
                  title: Text(
                    'خودِ «${widget.name}» موافقت صریح خود را با ثبت و نگه‌داری ردصدایش اعلام کرد '
                    '(یا خودم هستم).',
                  ),
                ),
                Text(
                  'ثبت صدای شخص دیگر بدون اطلاع و موافقت او مجاز نیست.',
                  style: theme.textTheme.bodySmall,
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: _agreed ? () => Navigator.pop(context, true) : null,
            child: const Text('موافقم؛ شروع ثبت صدا'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('انصراف'),
          ),
        ],
      ),
    );
  }
}
