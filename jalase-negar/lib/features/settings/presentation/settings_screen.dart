import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/providers.dart';
import '../../../core/utils/format.dart';
import '../../meetings/application/meeting_providers.dart';
import '../../meetings/data/meeting.dart'
    show Meeting, MeetingStatus, kWorkspaceOrg, kWorkspacePrimary;
import '../../models/presentation/models_screen.dart' show ModelsBody;
import '../../onboarding/tour_overlay.dart';
import '../../onboarding/tour_step.dart';
import '../../auth/presentation/delete_account_screen.dart';
import '../../plans/presentation/plans_screen.dart' show hoursText;
import '../../push/push_host.dart';
import '../../recording/application/live_engine_provider.dart';
import '../../updates/presentation/update_check_card.dart';
import '../../upload/upload_controller.dart';
import '../application/connection_controller.dart';
import 'cpu_limit_card.dart';
import 'meeting_upload_card.dart';
import '../../../core/platform/distribution.dart';
import 'qr_scan_screen.dart';
import 'theme_mode_card.dart';

/// SedaSanj connection screen: pair with a QR code, a config file or pasted
/// config text; shows who the app is connected as.
class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

/// Jumps to the tab a tour step's target lives on (the connection badge is
/// under "حساب", the upload switch under "ضبط و ارسال", the install status
/// under "مدل‌ها") so the tour's spotlight always lands on something visible
/// instead of a hidden tab.
class _SettingsScreenState extends ConsumerState<SettingsScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabs = TabController(length: 4, vsync: this);

  @override
  void dispose() {
    _tabs.dispose();
    super.dispose();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final tab = switch (TourStep.fromUri(GoRouterState.of(context).uri)) {
      TourStep.upload => 1,
      TourStep.models => 2,
      TourStep.connection => 0,
      _ => null,
    };
    if (tab != null && _tabs.index != tab) _tabs.index = tab;
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(connectionControllerProvider);
    final controller = ref.read(connectionControllerProvider.notifier);
    final state = async.value;
    final connection = state?.connection;
    final busy = state?.busy ?? async.isLoading;

    final account = <Widget>[
      SsCard(
        title: 'وضعیت اتصال',
        trailing: TourTarget(
          step: TourStep.connection,
          child: SsBadge(connection == null ? 'متصل نیست' : 'متصل'),
        ),
        child: connection == null
            ? const Text(
                'در پنل صداسنج از «تنظیمات حساب ← اتصال‌ها»، '
                'بخش «اتصال اپ جلسه‌نگار» را باز کنید '
                'و QR یا فایل کانفیگ را اینجا وارد کنید.',
              )
            : Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _Row('کاربر', connection.userName),
                  if (connection.personal)
                    const _PersonalUsageRows()
                  else
                    _Row('سازمان', connection.tenantName),
                  _Row('سرور', connection.serverUrl, ltr: true),
                  if (connection.tokenPrefix.isNotEmpty)
                    _Row('توکن', '${connection.tokenPrefix}…', ltr: true),
                  if (connection.personal)
                    TextButton(
                      onPressed: busy
                          ? null
                          : () => Navigator.of(context).push(
                              MaterialPageRoute<void>(
                                builder: (_) => const DeleteAccountScreen(),
                              ),
                            ),
                      child: Text(
                        'حذف حساب',
                        style: TextStyle(color: SsColors.of(context).danger),
                      ),
                    ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton(
                          onPressed: busy ? null : controller.recheck,
                          child: const Text('بررسی اتصال'),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: OutlinedButton(
                          onPressed: busy
                              ? null
                              : () => _confirmDisconnect(context, controller),
                          child: const Text('قطع اتصال'),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
      ),
      const SizedBox(height: 12),
      if (connection != null && connection.personal) ...[
        const _OrgLinkCard(),
        const SizedBox(height: 12),
      ],
      if (state?.error != null) ...[
        const SizedBox(height: 12),
        SsCard(
          child: Text(
            state!.error!,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
        ),
      ],
      const SizedBox(height: 12),
      if (busy)
        const Center(child: SsProcessingMark(size: 30))
      else if (connection == null)
        SsCard(
          title: 'اتصال',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              FilledButton.icon(
                icon: const Icon(Icons.phone_android),
                label: const Text('ورود با شماره موبایل'),
                onPressed: () => context.push('/login'),
              ),
              const SizedBox(height: 8),
              if (qrScanSupported) ...[
                OutlinedButton.icon(
                  icon: const Icon(Icons.qr_code_scanner),
                  label: const Text('اسکن QR'),
                  onPressed: () async {
                    final text =
                        await Navigator.of(
                          context,
                          rootNavigator: true,
                        ).push<String>(
                          MaterialPageRoute(
                            builder: (_) => const QrScanScreen(),
                          ),
                        );
                    if (text != null) controller.connectFromText(text);
                  },
                ),
                const SizedBox(height: 8),
              ],
              OutlinedButton.icon(
                icon: const Icon(Icons.file_open_outlined),
                label: const Text('انتخاب فایل کانفیگ'),
                onPressed: () async {
                  final res = await FilePicker.pickFiles(
                    type: FileType.custom,
                    allowedExtensions: const ['json'],
                  );
                  final path = res?.files.single.path;
                  if (path != null) {
                    controller.connectFromText(await File(path).readAsString());
                  }
                },
              ),
              const SizedBox(height: 8),
              OutlinedButton.icon(
                icon: const Icon(Icons.content_paste),
                label: const Text('چسباندن کانفیگ'),
                onPressed: () async {
                  final data = await Clipboard.getData(Clipboard.kTextPlain);
                  final text = data?.text;
                  if (text == null || text.trim().isEmpty) {
                    if (context.mounted) {
                      SsToastHost.show(
                        context,
                        'کلیپ‌بورد خالی است؛ متن کانفیگ را کپی کنید و دوباره بزنید.',
                      );
                    }
                    return;
                  }
                  controller.connectFromText(text);
                },
              ),
            ],
          ),
        ),
      const SizedBox(height: 12),
      const ThemeModeCard(),
    ];
    final recording = <Widget>[
      const _SendTranscriptCard(),
      const SizedBox(height: 12),
      const _SpeakerNameCard(),
      const SizedBox(height: 12),
      const CpuLimitCard(),
      const SizedBox(height: 12),
      const _SoundEventsCard(),
    ];
    final models = <Widget>[const ModelsBody()];
    final app = <Widget>[
      const UpdateCheckCard(),
      const SizedBox(height: 12),
      const PushSettingsCard(),
    ];

    Widget tab(List<Widget> children) => ListView(
      padding: EdgeInsets.fromLTRB(
        16,
        16,
        16,
        16 + MediaQuery.paddingOf(context).bottom,
      ),
      children: children,
    );

    return Column(
      children: [
        TabBar(
          controller: _tabs,
          // Four tabs no longer fit equally divided on a narrow phone
          // (the longest label, "ضبط و ارسال", got clipped); scrolling
          // gives every label its natural width instead.
          isScrollable: true,
          tabAlignment: TabAlignment.start,
          tabs: const [
            Tab(text: 'حساب'),
            Tab(text: 'ضبط و ارسال'),
            Tab(text: 'مدل‌ها'),
            Tab(text: 'نسخه اپ'),
          ],
        ),
        Expanded(
          child: TabBarView(
            controller: _tabs,
            children: [tab(account), tab(recording), tab(models), tab(app)],
          ),
        ),
      ],
    );
  }

  Future<void> _confirmDisconnect(
    BuildContext context,
    ConnectionController controller,
  ) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('قطع اتصال'),
        content: const Text(
          'توکن از این گوشی پاک می‌شود. برای ابطال کامل، دستگاه را در پنل هم حذف کنید.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('انصراف'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('قطع اتصال'),
          ),
        ],
      ),
    );
    if (ok == true) await controller.disconnect();
  }
}

class _Row extends StatelessWidget {
  const _Row(this.label, this.value, {this.ltr = false});

  final String label;
  final String value;
  final bool ltr;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 64,
            child: Text(label, style: Theme.of(context).textTheme.bodySmall),
          ),
          Expanded(
            child: Text(
              value,
              textDirection: ltr ? TextDirection.ltr : null,
              textAlign: ltr ? TextAlign.left : null,
            ),
          ),
        ],
      ),
    );
  }
}

/// Links the personal account to a SedaSanj organization and chooses where new
/// meetings go ("حساب شخصی" or the organization).
class _OrgLinkCard extends ConsumerStatefulWidget {
  const _OrgLinkCard();

  @override
  ConsumerState<_OrgLinkCard> createState() => _OrgLinkCardState();
}

class _OrgLinkCardState extends ConsumerState<_OrgLinkCard> {
  final _code = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _link() async {
    final code = _code.text.trim();
    if (code.isEmpty || _busy) return;
    setState(() => _busy = true);
    final error = await ref
        .read(connectionControllerProvider.notifier)
        .linkOrganization(code);
    if (!mounted) return;
    setState(() => _busy = false);
    if (error == null) {
      _code.clear();
      await SsToastHost.show(context, 'به سازمان متصل شد.');
    } else {
      await SsToastHost.show(context, error);
    }
  }

  Future<void> _import() async {
    final all = await ref.read(meetingsProvider.future);
    final candidates = [
      for (final m in all)
        if (m.status == MeetingStatus.complete &&
            m.remoteMeetingId != null &&
            m.workspace == kWorkspacePrimary)
          m,
    ];
    if (!mounted) return;
    if (candidates.isEmpty) {
      await SsToastHost.show(
        context,
        'جلسهٔ تمام‌شدهٔ شخصی برای کپی وجود ندارد.',
      );
      return;
    }
    final chosen = await showDialog<List<String>>(
      context: context,
      builder: (context) => _ImportDialog(meetings: candidates),
    );
    if (chosen == null || chosen.isEmpty || !mounted) return;
    setState(() => _busy = true);
    final message = await ref
        .read(connectionControllerProvider.notifier)
        .importMeetings(chosen);
    if (!mounted) return;
    setState(() => _busy = false);
    await SsToastHost.show(context, message);
  }

  Future<void> _unlink() async {
    setState(() => _busy = true);
    await ref.read(connectionControllerProvider.notifier).unlinkOrganization();
    if (!mounted) return;
    setState(() => _busy = false);
    await SsToastHost.show(
      context,
      'اتصال به سازمان قطع شد؛ جلسه‌های ارسال‌نشده به حساب شخصی برگشتند.',
    );
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(orgLinkProvider).value;
    final link = state?.link;
    final controller = ref.read(connectionControllerProvider.notifier);
    return SsCard(
      title: 'اتصال به سازمان صداسنج',
      child: link == null
          ? Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'کد اتصال را مدیر سازمان در پنل صداسنج می‌سازد. پس از اتصال '
                  'می‌توانید جلسه‌ها را به‌جای حساب شخصی به سازمان بفرستید.',
                ),
                const SizedBox(height: 8),
                TextField(
                  controller: _code,
                  textDirection: TextDirection.ltr,
                  decoration: const InputDecoration(labelText: 'کد اتصال'),
                  onSubmitted: (_) => _link(),
                ),
                const SizedBox(height: 8),
                FilledButton(
                  onPressed: _busy ? null : _link,
                  child: const Text('اتصال به سازمان'),
                ),
              ],
            )
          : Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _Row('سازمان', link.organization),
                SsSwitchTile(
                  title: const Text('ارسال جلسه‌های جدید به سازمان'),
                  subtitle: const Text(
                    'روشن: از اشتراک سازمان کم می‌شود و مدیر سازمان آن را در '
                    'پنل می‌بیند. خاموش: در حساب شخصی شما می‌ماند.',
                  ),
                  value: state?.workspace == kWorkspaceOrg,
                  onChanged: (value) => controller.setDefaultWorkspace(
                    value ? kWorkspaceOrg : kWorkspacePrimary,
                  ),
                ),
                const SizedBox(height: 8),
                OutlinedButton(
                  onPressed: _busy ? null : _import,
                  child: const Text('کپی جلسه‌های شخصی به سازمان'),
                ),
                const SizedBox(height: 8),
                OutlinedButton(
                  onPressed: _busy ? null : _unlink,
                  child: const Text('قطع اتصال از سازمان'),
                ),
              ],
            ),
    );
  }
}

class _ImportDialog extends StatefulWidget {
  const _ImportDialog({required this.meetings});

  final List<Meeting> meetings;

  @override
  State<_ImportDialog> createState() => _ImportDialogState();
}

class _ImportDialogState extends State<_ImportDialog> {
  final _picked = <String>{};

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('کپی جلسه‌ها به سازمان'),
      content: SizedBox(
        width: double.maxFinite,
        child: ListView(
          shrinkWrap: true,
          children: [
            const Text(
              'اصل جلسه در حساب شخصی می‌ماند. جلسه‌ای که روی سرور پاک شده کپی نمی‌شود.',
            ),
            for (final m in widget.meetings)
              CheckboxListTile(
                value: _picked.contains(m.remoteMeetingId),
                title: Text(m.title),
                onChanged: (on) => setState(() {
                  final id = m.remoteMeetingId!;
                  on == true ? _picked.add(id) : _picked.remove(id);
                }),
              ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('انصراف'),
        ),
        FilledButton(
          onPressed: _picked.isEmpty
              ? null
              : () => Navigator.pop(context, _picked.toList()),
          child: const Text('کپی'),
        ),
      ],
    );
  }
}

class _SendTranscriptCard extends ConsumerWidget {
  const _SendTranscriptCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final enabled = ref.watch(sendTranscriptEnabledProvider).value ?? true;
    return MeetingUploadCard(
      enabled: enabled,
      onChanged: (value) async {
        await ref.read(sendTranscriptEnabledProvider.notifier).set(value);
        if (value) {
          final repo = await ref.read(meetingRepositoryProvider.future);
          await repo.enableSendForUnsent();
          ref.invalidate(meetingsProvider);
          ref.read(uploadQueueProvider.notifier).kick();
        }
      },
    );
  }
}

class _SpeakerNameCard extends ConsumerWidget {
  const _SpeakerNameCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final enabled = ref.watch(speakerIdEnabledProvider).value ?? true;
    const title = 'نوشتن نام گوینده در متن';
    return SsCard(
      title: title,
      trailing: Semantics(
        label: title,
        toggled: enabled,
        child: SsSwitch(
          value: enabled,
          onChanged: (v) => ref.read(speakerIdEnabledProvider.notifier).set(v),
        ),
      ),
      child: Text(
        'هنگام ضبط، نام هر گوینده کنار متن می‌آید. روی گوشی‌های ضعیف '
        'می‌توانید خاموشش کنید.',
        style: Theme.of(
          context,
        ).textTheme.bodySmall?.copyWith(color: SsColors.of(context).ink),
      ),
    );
  }
}

class _SoundEventsCard extends ConsumerWidget {
  const _SoundEventsCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final enabled = ref.watch(soundEventsEnabledProvider).value ?? true;
    const title = 'نوشتن خنده، گریه و صداهای دیگر در متن';
    return SsCard(
      title: title,
      trailing: Semantics(
        label: title,
        toggled: enabled,
        child: SsSwitch(
          value: enabled,
          onChanged: (v) =>
              ref.read(soundEventsEnabledProvider.notifier).set(v),
        ),
      ),
      child: Text(
        'هنگام ضبط، صداهایی مثل خنده، قهقهه، گریه، آه، سرفه و عطسه بین [ ] '
        'در متن می‌آیند، مثلاً [خنده]. این بخش به مدل «تشخیص صداهای انسانی» '
        'در بخش «مدل‌ها» نیاز دارد و روی گوشی‌های ضعیف می‌توانید خاموشش کنید.',
        style: Theme.of(
          context,
        ).textTheme.bodySmall?.copyWith(color: SsColors.of(context).ink),
      ),
    );
  }
}

/// Plan name and remaining minutes of a personal account.
class _PersonalUsageRows extends ConsumerWidget {
  const _PersonalUsageRows();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(personalProfileProvider);
    return profile.when(
      loading: () => const _Row('ساعت باقی‌مانده', '…'),
      error: (_, _) => const _Row('ساعت باقی‌مانده', 'نامشخص'),
      data: (p) {
        final usage = p.usage;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (p.planName != null) _Row('پلن', p.planName!),
            _Row(
              'ساعت باقی‌مانده',
              usage == null
                  ? '${toPersianDigits('${p.remainingSeconds ~/ 60}')} دقیقه'
                  : usage.unlimited
                  ? 'نامحدود'
                  : 'حدود ${hoursText(usage.remainingHours)} ساعت',
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => context.push('/plans'),
                    child: const Text('پلن و مصرف'),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => context.push('/progress'),
                    child: const Text('پیشرفت و دعوت'),
                  ),
                ),
              ],
            ),
          ],
        );
      },
    );
  }
}
