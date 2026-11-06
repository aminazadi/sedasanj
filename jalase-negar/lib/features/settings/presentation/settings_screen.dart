import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../onboarding/tour_overlay.dart';
import '../../onboarding/tour_step.dart';
import '../../push/push_host.dart';
import '../../recording/application/live_engine_provider.dart';
import '../../updates/presentation/update_check_card.dart';
import '../../upload/upload_controller.dart';
import '../application/connection_controller.dart';
import 'cpu_limit_card.dart';
import 'meeting_upload_card.dart';
import '../../../core/platform/distribution.dart';
import 'qr_scan_screen.dart';

/// SedaSanj connection screen: pair with a QR code, a config file or pasted
/// config text; shows who the app is connected as.
class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(connectionControllerProvider);
    final controller = ref.read(connectionControllerProvider.notifier);
    final state = async.value;
    final connection = state?.connection;
    final busy = state?.busy ?? async.isLoading;

    return ListView(
      padding: EdgeInsets.fromLTRB(
        16,
        16,
        16,
        16 + MediaQuery.paddingOf(context).bottom,
      ),
      children: [
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
                    _Row('سازمان', connection.tenantName),
                    _Row('سرور', connection.serverUrl, ltr: true),
                    if (connection.tokenPrefix.isNotEmpty)
                      _Row('توکن', '${connection.tokenPrefix}…', ltr: true),
                  ],
                ),
        ),
        const SizedBox(height: 12),
        const _SendTranscriptCard(),
        const SizedBox(height: 12),
        const _SpeakerNameCard(),
        const SizedBox(height: 12),
        const CpuLimitCard(),
        const SizedBox(height: 12),
        const _SoundEventsCard(),
        const SizedBox(height: 12),
        const UpdateCheckCard(),
        const PushSettingsCard(),
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
          const Center(child: CircularProgressIndicator())
        else if (connection == null)
          SsCard(
            title: 'اتصال',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (qrScanSupported) ...[
                  FilledButton.icon(
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
                      controller.connectFromText(
                        await File(path).readAsString(),
                      );
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
          )
        else
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: controller.recheck,
                  child: const Text('بررسی اتصال'),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: OutlinedButton(
                  onPressed: () => _confirmDisconnect(context, controller),
                  child: const Text('قطع اتصال'),
                ),
              ),
            ],
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

class _SendTranscriptCard extends ConsumerWidget {
  const _SendTranscriptCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final enabled = ref.watch(sendTranscriptEnabledProvider).value ?? true;
    return MeetingUploadCard(
      enabled: enabled,
      onChanged: (value) async {
        await ref.read(sendTranscriptEnabledProvider.notifier).set(value);
        if (value) ref.read(uploadQueueProvider.notifier).kick();
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
        ).textTheme.bodySmall?.copyWith(color: SsColors.ink),
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
        ).textTheme.bodySmall?.copyWith(color: SsColors.ink),
      ),
    );
  }
}
