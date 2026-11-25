import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/platform/api_client.dart';
import '../../../core/utils/format.dart';
import '../../settings/application/connection_controller.dart';
import '../../catalog/application/catalog_providers.dart';
import '../../../core/platform/distribution.dart';
import '../data/billing_models.dart';
import '../store_purchase.dart';
import '../store_sdk.dart';

String _errorText(Object error) => error is ApiException
    ? error.message
    : error is StateError
    ? error.message
    : 'ارتباط با سرور برقرار نشد؛ اینترنت را بررسی کنید و دوباره تلاش کنید.';

/// "۱٫۵" style number with at most one decimal.
String hoursText(double hours) {
  final text = hours == hours.roundToDouble()
      ? hours.toStringAsFixed(0)
      : hours.toStringAsFixed(1);
  return toPersianDigits(text);
}

String tomanText(int toman) {
  final digits = toman.toString();
  final grouped = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) grouped.write('٬');
    grouped.write(digits[i]);
  }
  return '${toPersianDigits(grouped.toString())} تومان';
}

/// Opens the payment page, then lets the user confirm once they are back.
typedef PaymentLauncher = Future<bool> Function(Uri url);

Future<bool> _launch(Uri url) =>
    launchUrl(url, mode: LaunchMode.externalApplication);

/// Hours left, the plans and token packs; buying opens the bank page in the browser.
class PlansScreen extends ConsumerStatefulWidget {
  PlansScreen({
    super.key,
    this.launcher = _launch,
    bool? canBuy,
    StoreBillingSdk? storeSdk,
    this.storeChannel,
  }) : canBuy = canBuy ?? !Platform.isIOS,
       storeSdk = storeSdk ?? currentStoreSdk;

  final PaymentLauncher launcher;

  /// Buying is hidden on iOS: Apple restricts paying outside the app for digital
  /// goods, so the iOS app only shows the plan; buying happens on Android or
  /// the web. ⚠ Needs a decision before an App Store release.
  final bool canBuy;

  /// Set in the Bazaar and Myket builds: purchases go through the store's own payment sheet
  /// and the server verifies them, instead of the bank page.
  final StoreBillingSdk? storeSdk;
  final String? storeChannel;

  @override
  ConsumerState<PlansScreen> createState() => _PlansScreenState();
}

class _PlansScreenState extends ConsumerState<PlansScreen>
    with WidgetsBindingObserver {
  bool _busy = false;

  /// While the "پرداخت انجام شد؟" dialog is open: asks the server whether the
  /// order is paid when the user comes back from the bank page.
  Future<void> Function()? _autoCheck;
  bool _autoPaid = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _autoCheck?.call();
  }

  void _paidDone() {
    ref
      ..invalidate(usageProvider)
      ..invalidate(plansProvider)
      ..invalidate(personalProfileProvider);
  }

  Future<void> _buy({String? planCode, String? packageId}) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final client = await ref.read(personalClientProvider.future);
      final sdk = widget.storeSdk;
      if (sdk != null) {
        final result = await buyFromStore(
          api: client,
          sdk: sdk,
          store: widget.storeChannel ?? kStoreChannel,
          planCode: planCode,
          packageId: packageId,
        );
        if (result.activated) {
          _paidDone();
          if (mounted) {
            await SsToastHost.show(context, 'خرید تأیید شد؛ ساعت‌ها اضافه شد.');
          }
        }
        return;
      }
      final key = 'jn-${DateTime.now().microsecondsSinceEpoch}';
      final purchase = await client.startPurchase(
        planCode: planCode,
        packageId: packageId,
        idempotencyKey: key,
      );
      final opened = await widget.launcher(Uri.parse(purchase.payUrl));
      if (!opened) {
        if (mounted) {
          await SsToastHost.show(
            context,
            'صفحهٔ پرداخت باز نشد؛ مرورگر گوشی را بررسی کنید و دوباره تلاش کنید.',
          );
        }
        return;
      }
      if (!mounted) return;
      await _confirmPaid(client, purchase.orderId);
    } on Object catch (error) {
      if (mounted) await SsToastHost.show(context, _errorText(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _confirmPaid(ApiClient client, String orderId) async {
    var message = 'پرداخت هنوز تأیید نشده است.';
    while (true) {
      if (!mounted) return;
      _autoPaid = false;
      _autoCheck = () async {
        try {
          final status = await client.orderStatus(orderId);
          if (status.paid && mounted && !_autoPaid) {
            _autoPaid = true;
            Navigator.of(context, rootNavigator: true).pop(false);
          }
        } on Object {
          // The button below still lets the user check by hand.
        }
      };
      final done = await showDialog<bool>(
        context: context,
        barrierDismissible: false,
        builder: (context) => AlertDialog(
          title: const Text('پرداخت انجام شد؟'),
          content: Text(
            '$message\nپس از پرداخت در مرورگر، به اینجا برگردید و «بررسی پرداخت» را بزنید.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('بعداً'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('بررسی پرداخت'),
            ),
          ],
        ),
      );
      _autoCheck = null;
      if (_autoPaid) {
        _autoPaid = false;
        _paidDone();
        if (mounted) {
          await SsToastHost.show(context, 'پرداخت تأیید شد؛ ساعت‌ها اضافه شد.');
        }
        return;
      }
      if (done != true) return;
      try {
        final status = await client.orderStatus(orderId);
        if (status.paid) {
          _paidDone();
          if (mounted) {
            await SsToastHost.show(
              context,
              'پرداخت تأیید شد؛ ساعت‌ها اضافه شد.',
            );
          }
          return;
        }
        message = status.closed
            ? 'این پرداخت ناموفق بود؛ دوباره تلاش کنید.'
            : 'پرداخت هنوز تأیید نشده است.';
        if (status.closed) return;
      } on Object catch (error) {
        message = _errorText(error);
      }
    }
  }

  /// Plans and packs are public, so anyone can look; only buying needs an account. A signed-out
  /// user who taps a buy button is sent to sign in and comes back to this screen.
  void _select({required bool personal, String? planCode, String? packageId}) {
    if (!personal) {
      unawaited(
        SsToastHost.show(context, 'برای خرید ابتدا وارد حساب خود شوید.'),
      );
      context.push('/login?back=1');
      return;
    }
    _buy(planCode: planCode, packageId: packageId);
  }

  @override
  Widget build(BuildContext context) {
    final personal =
        ref.watch(connectionControllerProvider).value?.connection?.personal ??
        false;
    final plans = ref.watch(plansProvider);
    final packs = ref.watch(tokenPackagesProvider);
    final canBuy = widget.canBuy;
    return Scaffold(
      appBar: SsAppBar(title: const Text('پلن و مصرف')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (personal)
            ref
                .watch(usageProvider)
                .when(
                  loading: () => const _LoadingCard(),
                  error: (e, _) => _ErrorCard(
                    message: _errorText(e),
                    onRetry: () => ref.invalidate(usageProvider),
                  ),
                  data: (u) => _UsageCard(usage: u),
                )
          else
            const _SignedOutCard(),
          const SizedBox(height: 24),
          const _SectionHeading(
            title: 'پلن‌ها',
            caption: 'ساعت جلسهٔ هر پلن هر ماه دوباره شارژ می‌شود.',
          ),
          plans.when(
            loading: () => const _LoadingCard(),
            error: (e, _) => _ErrorCard(
              message: _errorText(e),
              onRetry: () => ref.invalidate(plansProvider),
            ),
            data: (p) => Column(
              children: [
                if (p.free != null)
                  _PlanCard(plan: p.free!, busy: _busy, onChoose: null),
                for (final plan in p.plans)
                  _PlanCard(
                    plan: plan,
                    busy: _busy,
                    onChoose: plan.buyable && canBuy
                        ? () => _select(personal: personal, planCode: plan.code)
                        : null,
                  ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          const _SectionHeading(
            title: 'ساعت اضافه',
            caption:
                'پس از ساعت‌های ماهانه مصرف می‌شود و تمام نمی‌شود مگر با استفاده.',
          ),
          packs.when(
            loading: () => const _LoadingCard(),
            error: (e, _) => _ErrorCard(
              message: _errorText(e),
              onRetry: () => ref.invalidate(tokenPackagesProvider),
            ),
            data: (items) => items.isEmpty
                ? const SsCard(
                    child: Text('فعلاً بستهٔ ساعت اضافه‌ای در دسترس نیست.'),
                  )
                : LayoutBuilder(
                    builder: (context, constraints) {
                      const gap = 12.0;
                      final width = (constraints.maxWidth - gap) / 2;
                      return Wrap(
                        spacing: gap,
                        runSpacing: gap,
                        children: [
                          for (final pack in items)
                            SizedBox(
                              width: width,
                              child: _PackTile(
                                pack: pack,
                                busy: _busy,
                                onChoose: canBuy
                                    ? () => _select(
                                        personal: personal,
                                        packageId: pack.id,
                                      )
                                    : null,
                              ),
                            ),
                        ],
                      );
                    },
                  ),
          ),
          const SizedBox(height: 20),
          if (!canBuy)
            const Padding(
              padding: EdgeInsets.only(bottom: 8),
              child: Text(
                'خرید پلن و ساعت اضافه در نسخهٔ iOS فعال نیست؛ از نسخهٔ اندروید یا وب خرید کنید. حساب شما همه‌جا یکی است.',
              ),
            ),
          Text(
            'ساعت‌ها تقریبی‌اند و از روی مصرف واقعی هوش مصنوعی حساب می‌شوند.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

/// A section's title with a one-line caption under it.
class _SectionHeading extends StatelessWidget {
  const _SectionHeading({required this.title, required this.caption});

  final String title;
  final String caption;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = SsColors.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: theme.textTheme.titleMedium?.copyWith(color: colors.primary),
          ),
          const SizedBox(height: 2),
          Text(
            caption,
            style: theme.textTheme.bodySmall?.copyWith(color: colors.neutral),
          ),
        ],
      ),
    );
  }
}

class _LoadingCard extends StatelessWidget {
  const _LoadingCard();

  @override
  Widget build(BuildContext context) => const Padding(
    padding: EdgeInsets.only(bottom: 12),
    child: SsCard(
      child: SizedBox(
        height: 72,
        child: Center(child: SsProcessingMark(size: 28)),
      ),
    ),
  );
}

/// A failed load, with the reason and a retry (every error names an action).
class _ErrorCard extends StatelessWidget {
  const _ErrorCard({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: SsCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                Icons.cloud_off_outlined,
                size: 22,
                color: SsColors.of(context).danger,
              ),
              const SizedBox(width: 10),
              Expanded(child: Text(message)),
            ],
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: onRetry,
            icon: const Icon(Icons.refresh, size: 18),
            label: const Text('تلاش دوباره'),
          ),
        ],
      ),
    ),
  );
}

/// Shown instead of the usage card while signed out: browsing is open, buying needs an account.
class _SignedOutCard extends StatelessWidget {
  const _SignedOutCard();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = SsColors.of(context);
    return SsCard(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Container(
            width: 48,
            height: 48,
            decoration: BoxDecoration(
              color: colors.selected,
              borderRadius: BorderRadius.circular(8),
            ),
            child: Icon(Icons.auto_awesome, color: colors.primary),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'پلن مناسب خود را ببینید',
                  style: theme.textTheme.titleSmall,
                ),
                const SizedBox(height: 2),
                Text(
                  'برای خرید و دیدن میزان مصرف، وارد حساب شوید.',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: colors.neutral,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _UsageCard extends StatelessWidget {
  const _UsageCard({required this.usage});

  final UsageInfo usage;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = SsColors.of(context);
    if (usage.unlimited) {
      return SsCard(
        child: Row(
          children: [
            Icon(Icons.all_inclusive, size: 36, color: colors.primary),
            const SizedBox(width: 14),
            Expanded(
              child: Text(
                'پلن شما محدودیت ساعتی ندارد.',
                style: theme.textTheme.titleSmall,
              ),
            ),
          ],
        ),
      );
    }
    final fraction = usage.planHours <= 0
        ? 0.0
        : (usage.planRemainingHours / usage.planHours).clamp(0.0, 1.0);
    final resets = usage.resetsAt?.toLocal();
    final tone = usage.exhausted ? colors.danger : colors.primary;
    return SsCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              SizedBox(
                width: 92,
                height: 92,
                child: Stack(
                  alignment: Alignment.center,
                  children: [
                    SizedBox.expand(
                      child: CircularProgressIndicator(
                        value: fraction,
                        strokeWidth: 9,
                        strokeCap: StrokeCap.round,
                        color: tone,
                        backgroundColor: colors.selected,
                      ),
                    ),
                    Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          hoursText(usage.remainingHours),
                          style: theme.textTheme.titleLarge?.copyWith(
                            color: tone,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        Text('ساعت', style: theme.textTheme.bodySmall),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'حدود ${hoursText(usage.remainingHours)} ساعت جلسه باقی مانده',
                      style: theme.textTheme.titleSmall,
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'سهمیهٔ این ماه: ${hoursText(usage.planRemainingHours)} از '
                      '${hoursText(usage.planHours)} ساعت',
                      style: theme.textTheme.bodySmall,
                    ),
                    if (usage.bonusHours > 0)
                      Text(
                        'ساعت اضافه: ${hoursText(usage.bonusHours)}',
                        style: theme.textTheme.bodySmall,
                      ),
                  ],
                ),
              ),
            ],
          ),
          if (resets != null) ...[
            const SizedBox(height: 12),
            Divider(height: 1, color: colors.line),
            const SizedBox(height: 10),
            Row(
              children: [
                Icon(Icons.event_repeat, size: 16, color: colors.neutral),
                const SizedBox(width: 6),
                Text(
                  'شارژ ماهانه بعدی: ${toPersianDigits('${resets.year}/${resets.month}/${resets.day}')} (میلادی)',
                  style: theme.textTheme.bodySmall,
                ),
              ],
            ),
          ],
          if (usage.exhausted)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Text(
                'ساعت‌هایتان تمام شده است؛ پلن را ارتقا دهید یا ساعت اضافه بخرید.',
                style: TextStyle(color: colors.danger),
              ),
            ),
        ],
      ),
    );
  }
}

/// One big number with its caption under it.
class _Figure extends StatelessWidget {
  const _Figure({required this.value, required this.caption});

  final String value;
  final String caption;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          value,
          style: theme.textTheme.titleLarge?.copyWith(
            color: SsColors.of(context).primary,
            fontWeight: FontWeight.w700,
          ),
        ),
        Text(
          caption,
          style: theme.textTheme.bodySmall?.copyWith(
            color: SsColors.of(context).neutral,
          ),
        ),
      ],
    );
  }
}

class _PlanCard extends StatelessWidget {
  const _PlanCard({
    required this.plan,
    required this.busy,
    required this.onChoose,
  });

  final PlanInfo plan;
  final bool busy;

  /// Null: no buy button (the free plan, a plan that is not for sale, or iOS).
  final VoidCallback? onChoose;

  @override
  Widget build(BuildContext context) {
    final hours = plan.monthlyHours;
    final free = plan.monthlyPriceToman == 0;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: SsCard(
        title: plan.name,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: _Figure(
                    value: hours == null ? 'نامحدود' : hoursText(hours),
                    caption: 'ساعت جلسه در ماه',
                  ),
                ),
                Container(
                  width: 1,
                  height: 40,
                  color: SsColors.of(context).line,
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: _Figure(
                    value: free ? 'رایگان' : tomanText(plan.monthlyPriceToman),
                    caption: free ? 'بدون هزینه' : 'در ماه',
                  ),
                ),
              ],
            ),
            if (onChoose != null) ...[
              const SizedBox(height: 14),
              FilledButton(
                onPressed: busy ? null : onChoose,
                child: const Text('خرید'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _PackTile extends StatelessWidget {
  const _PackTile({
    required this.pack,
    required this.busy,
    required this.onChoose,
  });

  final PackInfo pack;
  final bool busy;

  /// Null on iOS: the price is shown without a button.
  final VoidCallback? onChoose;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = SsColors.of(context);
    final price = tomanText(pack.priceToman);
    return SsCard(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Icon(Icons.bolt, color: colors.accent, size: 26),
          const SizedBox(height: 4),
          Text(
            hoursText(pack.hours),
            textAlign: TextAlign.center,
            style: theme.textTheme.headlineSmall?.copyWith(
              color: colors.primary,
              fontWeight: FontWeight.w700,
            ),
          ),
          Text(
            'ساعت اضافه',
            textAlign: TextAlign.center,
            style: theme.textTheme.bodySmall?.copyWith(color: colors.neutral),
          ),
          const SizedBox(height: 12),
          if (onChoose != null)
            FilledButton(onPressed: busy ? null : onChoose, child: Text(price))
          else
            Text(
              price,
              textAlign: TextAlign.center,
              style: theme.textTheme.titleSmall,
            ),
        ],
      ),
    );
  }
}
