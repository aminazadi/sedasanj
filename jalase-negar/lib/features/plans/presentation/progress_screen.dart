import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:share_plus/share_plus.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/platform/api_client.dart';
import '../../../core/utils/format.dart';
import '../../settings/application/connection_controller.dart';
import '../data/billing_models.dart';
import 'plans_screen.dart' show hoursText;

String _errorText(Object error) => error is ApiException
    ? error.message
    : 'ارتباط با سرور برقرار نشد؛ اینترنت را بررسی کنید و دوباره تلاش کنید.';

/// Level, badges, the month's gift allowance and friend invites.
class ProgressScreen extends ConsumerStatefulWidget {
  const ProgressScreen({super.key});

  @override
  ConsumerState<ProgressScreen> createState() => _ProgressScreenState();
}

class _ProgressScreenState extends ConsumerState<ProgressScreen> {
  final _code = TextEditingController();
  bool _celebrated = false;
  bool _busy = false;

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _redeem() async {
    if (_busy || _code.text.trim().length < 6) return;
    setState(() => _busy = true);
    try {
      final client = await ref.read(personalClientProvider.future);
      await client.redeemInvite(_code.text);
      _code.clear();
      ref
        ..invalidate(usageProvider)
        ..invalidate(inviteProvider)
        ..invalidate(progressProvider);
      if (mounted) {
        await SsToastHost.show(context, 'کد دعوت ثبت شد؛ ساعت هدیه اضافه شد.');
      }
    } on Object catch (error) {
      if (mounted) await SsToastHost.show(context, _errorText(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final progress = ref.watch(progressProvider);
    final invite = ref.watch(inviteProvider);
    progress.whenData((p) {
      if (!_celebrated && p.newlyEarned.isNotEmpty) {
        _celebrated = true;
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) {
            SsToastHost.show(context, 'نشان جدید: ${p.newlyEarned.join('، ')}');
          }
        });
      }
    });
    return Scaffold(
      appBar: SsAppBar(title: const Text('پیشرفت من')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          progress.when(
            loading: () => const SsCard(child: Text('…')),
            error: (e, _) => SsCard(child: Text(_errorText(e))),
            data: (p) => Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _LevelCard(progress: p),
                const SizedBox(height: 12),
                const SsSectionTitle(title: 'نشان‌ها'),
                for (final badge in p.badges) _BadgeTile(badge: badge),
              ],
            ),
          ),
          const SizedBox(height: 12),
          const SsSectionTitle(title: 'دعوت دوستان'),
          invite.when(
            loading: () => const SsCard(child: Text('…')),
            error: (e, _) => SsCard(child: Text(_errorText(e))),
            data: (info) => _InviteCard(
              info: info,
              controller: _code,
              busy: _busy,
              onRedeem: _redeem,
            ),
          ),
        ],
      ),
    );
  }
}

class _LevelCard extends StatelessWidget {
  const _LevelCard({required this.progress});

  final ProgressInfo progress;

  @override
  Widget build(BuildContext context) {
    final p = progress;
    return SsCard(
      title: 'سطح ${toPersianDigits('${p.level}')}',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          LinearProgressIndicator(
            value: p.levelFraction,
            minHeight: 10,
            color: SsColors.primary,
            backgroundColor: SsColors.selected,
          ),
          const SizedBox(height: 8),
          Text(
            '${toPersianDigits('${p.xp}')} امتیاز از '
            '${toPersianDigits('${p.nextLevelXp}')} برای سطح بعد',
          ),
          Text(
            'هفته‌های پیاپی دارای جلسه: ${toPersianDigits('${p.streakWeeks}')}',
          ),
          if (p.giftLimitHours > 0)
            Text(
              'هدیهٔ نشان‌های این ماه: ${hoursText(p.giftLeftHours)} از '
              '${hoursText(p.giftLimitHours)} ساعت باقی مانده',
            )
          else
            const Text(
              'هدیهٔ نشان‌ها فعلاً خاموش است؛ نشان‌ها همچنان ثبت می‌شوند.',
            ),
        ],
      ),
    );
  }
}

class _BadgeTile extends StatelessWidget {
  const _BadgeTile({required this.badge});

  final BadgeInfo badge;

  @override
  Widget build(BuildContext context) {
    return SsCard(
      selected: badge.earned,
      title: badge.title,
      trailing: Icon(
        badge.earned ? Icons.emoji_events : Icons.lock_outline,
        color: badge.earned ? SsColors.primary : SsColors.neutral,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(badge.description),
          if (!badge.earned)
            Text(
              '${toPersianDigits('${badge.current}')} از ${toPersianDigits('${badge.threshold}')}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
        ],
      ),
    );
  }
}

class _InviteCard extends StatelessWidget {
  const _InviteCard({
    required this.info,
    required this.controller,
    required this.busy,
    required this.onRedeem,
  });

  final InviteInfo info;
  final TextEditingController controller;
  final bool busy;
  final VoidCallback onRedeem;

  @override
  Widget build(BuildContext context) {
    if (!info.enabled) {
      return const SsCard(child: Text('دعوت دوستان فعلاً فعال نیست.'));
    }
    return SsCard(
      title: 'کد دعوت شما',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: SelectableText(
                  info.code,
                  textDirection: TextDirection.ltr,
                  style: Theme.of(context).textTheme.titleLarge,
                ),
              ),
              IconButton(
                tooltip: 'کپی',
                icon: const Icon(Icons.copy),
                onPressed: () async {
                  await Clipboard.setData(ClipboardData(text: info.code));
                  if (context.mounted) {
                    await SsToastHost.show(context, 'کد کپی شد.');
                  }
                },
              ),
              IconButton(
                tooltip: 'اشتراک‌گذاری',
                icon: const Icon(Icons.share),
                onPressed: () => SharePlus.instance.share(
                  ShareParams(
                    text:
                        'با کد ${info.code} در جلسه‌نگار ثبت‌نام کن و '
                        '${hoursText(info.rewardHours)} ساعت هدیه بگیر.',
                  ),
                ),
              ),
            ],
          ),
          Text(
            'هر دوستی که با این کد ثبت‌نام کند، شما و او '
            '${hoursText(info.rewardHours)} ساعت هدیه می‌گیرید. '
            'دوستان دعوت‌شده: ${toPersianDigits('${info.joined}')}',
          ),
          const Divider(height: 24),
          const Text('کد دعوت دوستتان را دارید؟ (تا یک هفته پس از ساخت حساب)'),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: controller,
                  textDirection: TextDirection.ltr,
                  textCapitalization: TextCapitalization.characters,
                  decoration: const InputDecoration(hintText: 'ABCD2345'),
                ),
              ),
              const SizedBox(width: 8),
              FilledButton(
                onPressed: busy ? null : onRedeem,
                child: const Text('ثبت'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
