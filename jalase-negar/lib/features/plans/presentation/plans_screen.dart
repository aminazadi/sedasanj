import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/platform/api_client.dart';
import '../../../core/utils/format.dart';
import '../../settings/application/connection_controller.dart';
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

  @override
  Widget build(BuildContext context) {
    final usage = ref.watch(usageProvider);
    final plans = ref.watch(plansProvider);
    final packs = ref.watch(tokenPackagesProvider);
    return Scaffold(
      appBar: SsAppBar(title: const Text('پلن و مصرف')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          usage.when(
            loading: () => const SsCard(child: Text('…')),
            error: (e, _) => SsCard(child: Text(_errorText(e))),
            data: (u) => _UsageCard(usage: u),
          ),
          const SizedBox(height: 12),
          const SsSectionTitle(title: 'پلن‌ها'),
          plans.when(
            loading: () => const SsCard(child: Text('…')),
            error: (e, _) => SsCard(child: Text(_errorText(e))),
            data: (p) => Column(
              children: [
                if (p.free != null) _PlanCard(plan: p.free!, onBuy: null),
                for (final plan in p.plans)
                  _PlanCard(
                    plan: plan,
                    onBuy: !widget.canBuy || _busy
                        ? null
                        : () => _buy(planCode: plan.code),
                    showBuy: widget.canBuy,
                  ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          const SsSectionTitle(title: 'ساعت اضافه'),
          packs.when(
            loading: () => const SsCard(child: Text('…')),
            error: (e, _) => SsCard(child: Text(_errorText(e))),
            data: (items) => items.isEmpty
                ? const SsCard(
                    child: Text('فعلاً بستهٔ ساعت اضافه‌ای در دسترس نیست.'),
                  )
                : Column(
                    children: [
                      for (final pack in items)
                        SsCard(
                          title: '${hoursText(pack.hours)} ساعت',
                          trailing: FilledButton(
                            onPressed: !widget.canBuy || _busy
                                ? null
                                : () => _buy(packageId: pack.id),
                            child: Text(tomanText(pack.priceToman)),
                          ),
                          child: const Text(
                            'پس از ساعت‌های ماهانه مصرف می‌شود و تمام نمی‌شود مگر با استفاده.',
                          ),
                        ),
                    ],
                  ),
          ),
          const SizedBox(height: 8),
          if (!widget.canBuy)
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

class _UsageCard extends StatelessWidget {
  const _UsageCard({required this.usage});

  final UsageInfo usage;

  @override
  Widget build(BuildContext context) {
    if (usage.unlimited) {
      return const SsCard(
        title: 'مصرف',
        child: Text('پلن شما محدودیت ساعتی ندارد.'),
      );
    }
    final fraction = usage.planHours <= 0
        ? 0.0
        : (usage.planRemainingHours / usage.planHours).clamp(0.0, 1.0);
    final resets = usage.resetsAt;
    return SsCard(
      title: 'حدود ${hoursText(usage.remainingHours)} ساعت جلسه باقی مانده',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          LinearProgressIndicator(
            value: fraction,
            minHeight: 10,
            color: usage.exhausted
                ? SsColors.of(context).danger
                : SsColors.of(context).primary,
            backgroundColor: SsColors.of(context).selected,
          ),
          const SizedBox(height: 8),
          Text(
            'سهمیهٔ این ماه: ${hoursText(usage.planRemainingHours)} از '
            '${hoursText(usage.planHours)} ساعت',
          ),
          if (usage.bonusHours > 0)
            Text(
              'ساعت اضافه (خریداری‌شده یا هدیه): ${hoursText(usage.bonusHours)}',
            ),
          if (resets != null)
            Text(
              'شارژ ماهانه بعدی: ${toPersianDigits('${resets.toLocal().year}/${resets.toLocal().month}/${resets.toLocal().day}')} (میلادی)',
            ),
          if (usage.exhausted)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                'ساعت‌هایتان تمام شده است؛ پلن را ارتقا دهید یا ساعت اضافه بخرید.',
                style: TextStyle(color: SsColors.of(context).danger),
              ),
            ),
        ],
      ),
    );
  }
}

class _PlanCard extends StatelessWidget {
  const _PlanCard({
    required this.plan,
    required this.onBuy,
    this.showBuy = true,
  });

  final bool showBuy;
  final PlanInfo plan;
  final VoidCallback? onBuy;

  @override
  Widget build(BuildContext context) {
    final hours = plan.monthlyHours;
    return SsCard(
      title: plan.name,
      trailing: plan.buyable && showBuy
          ? FilledButton(onPressed: onBuy, child: const Text('خرید'))
          : null,
      child: Text(
        [
          if (hours != null) '${hoursText(hours)} ساعت جلسه در ماه',
          plan.monthlyPriceToman == 0
              ? 'رایگان'
              : '${tomanText(plan.monthlyPriceToman)} در ماه',
        ].join(' · '),
      ),
    );
  }
}
