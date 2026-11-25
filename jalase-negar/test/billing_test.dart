import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart' hide ConnectionState;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:jalase_negar/features/catalog/application/catalog_providers.dart';
import 'package:jalase_negar/app/widgets/ss_toast.dart';
import 'package:jalase_negar/core/platform/api_client.dart';
import 'package:jalase_negar/core/platform/platform_config.dart';
import 'package:jalase_negar/features/plans/data/billing_models.dart';
import 'package:jalase_negar/features/plans/presentation/plans_screen.dart';
import 'package:jalase_negar/features/plans/presentation/progress_screen.dart';
import 'package:jalase_negar/features/settings/application/connection_controller.dart';

class _Adapter implements HttpClientAdapter {
  _Adapter(this.handler);
  final ResponseBody Function(RequestOptions) handler;
  @override
  void close({bool force = false}) {}
  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<List<int>>? requestStream,
    Future<void>? cancelFuture,
  ) async => handler(options);
}

ResponseBody _json(Object body, {int status = 200}) => ResponseBody.fromString(
  jsonEncode(body),
  status,
  headers: {
    Headers.contentTypeHeader: ['application/json'],
  },
);

const _usage = {
  'unlimited': false,
  'plan_hours': 20.0,
  'used_hours': 5.5,
  'plan_remaining_hours': 14.5,
  'bonus_hours': 2.0,
  'remaining_hours': 16.5,
  'exhausted': false,
  'resets_at': '2026-12-15T00:00:00Z',
};

const _plans = {
  'free': {
    'code': 'jn_free',
    'name': 'جلسه‌نگار رایگان',
    'monthly_price_toman': 0,
    'monthly_hours': 3.0,
    'buyable': false,
  },
  'plans': [
    {
      'code': 'jn_bronze',
      'name': 'جلسه‌نگار برنزی',
      'monthly_price_toman': 280000,
      'monthly_hours': 20.0,
      'buyable': true,
    },
  ],
};

class _PersonalConnected extends ConnectionController {
  @override
  Future<ConnectionState> build() async => const ConnectionState(
    connection: PlatformConnection(
      serverUrl: 'https://sedasanj.test',
      userName: 'کاربر',
      tenantName: '',
      tokenPrefix: 'jn_test',
      personal: true,
    ),
  );
}

void main() {
  test('usage and plans keep hours and prices', () {
    final usage = UsageInfo.fromJson(_usage);
    expect(usage.remainingHours, 16.5);
    expect(usage.bonusHours, 2.0);
    expect(usage.resetsAt, DateTime.utc(2026, 12, 15));
    final plans = PlansResult.fromJson(_plans);
    expect(plans.free!.buyable, isFalse);
    expect(plans.plans.single.monthlyPriceToman, 280000);
    expect(plans.plans.single.monthlyHours, 20.0);
  });

  test('numbers are shown in Persian digits with grouped prices', () {
    expect(hoursText(1.5), '۱٫۵'.replaceAll('٫', '.'));
    expect(hoursText(20), '۲۰');
    expect(tomanText(280000), '۲۸۰٬۰۰۰ تومان');
    expect(tomanText(680000), '۶۸۰٬۰۰۰ تومان');
  });

  test('progress shows how far the level bar is and what to celebrate', () {
    final progress = ProgressInfo.fromJson({
      'xp': 60,
      'level': 2,
      'level_xp': 25,
      'next_level_xp': 100,
      'metrics': {'streak_weeks': 3},
      'badges': [
        {
          'code': 'first_meeting',
          'title': 'اولین جلسه',
          'description': 'اولین جلسه‌تان را ثبت کردید.',
          'current': 1,
          'threshold': 1,
          'earned': true,
        },
        {
          'code': 'five_meetings',
          'title': 'پنج جلسه',
          'description': 'پنج جلسه ثبت کرده‌اید.',
          'current': 3,
          'threshold': 5,
          'earned': false,
        },
      ],
      'newly_earned': [
        {'title': 'اولین جلسه'},
      ],
      'gift': {'left_hours': 0.4, 'limit_hours': 0.6},
    });
    expect(progress.levelFraction, closeTo(35 / 75, 1e-9));
    expect(progress.streakWeeks, 3);
    expect(progress.badges.where((b) => b.earned).single.code, 'first_meeting');
    expect(progress.newlyEarned, ['اولین جلسه']);
    expect(progress.giftLeftHours, 0.4);
  });

  test(
    'buying a plan creates the order once-keyed, then asks for the pay url',
    () async {
      final seen = <RequestOptions>[];
      final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
      dio.httpClientAdapter = _Adapter((o) {
        seen.add(o);
        if (o.path == '/v1/jalase-negar/orders') {
          return _json({'id': 'o1', 'amount_toman': 308000}, status: 201);
        }
        if (o.path == '/v1/jalase-negar/token-orders') {
          return _json({'id': 'o2', 'amount_toman': 66000}, status: 201);
        }
        if (o.path.endsWith('/pay')) {
          return _json({
            'payment_id': 'p',
            'redirect_url': 'https://bank.test/pay',
          });
        }
        return _json({'id': 'o1', 'status': 'paid'});
      });
      final api = ApiClient(serverUrl: 'https://example.test', dio: dio);
      final plan = await api.startPurchase(
        planCode: 'jn_bronze',
        idempotencyKey: 'key-12345678',
      );
      expect(plan.orderId, 'o1');
      expect(plan.payUrl, 'https://bank.test/pay');
      expect(seen.first.headers['Idempotency-Key'], 'key-12345678');
      expect(seen.first.data, {'plan_code': 'jn_bronze'});
      final pack = await api.startPurchase(
        packageId: 'pk1',
        idempotencyKey: 'key-87654321',
      );
      expect(pack.orderId, 'o2');
      expect(seen.firstWhere((o) => o.path.endsWith('token-orders')).data, {
        'package_id': 'pk1',
      });
      expect((await api.orderStatus('o1')).paid, isTrue);
    },
  );

  test(
    'an exhausted plan keeps the server message that names the next step',
    () async {
      final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
      dio.httpClientAdapter = _Adapter(
        (o) => _json({
          'error': {
            'code': 'subscription_exists',
            'message': 'پلن پولی فعالی دارید؛ پس از پایان ماه تمدید کنید.',
          },
        }, status: 409),
      );
      final api = ApiClient(serverUrl: 'https://example.test', dio: dio);
      await expectLater(
        api.startPurchase(planCode: 'jn_gold', idempotencyKey: 'key-12345678'),
        throwsA(
          isA<ApiException>().having(
            (e) => e.message,
            'message',
            contains('پس از پایان ماه'),
          ),
        ),
      );
    },
  );

  testWidgets(
    'the plans screen shows hours, buys a plan and confirms payment',
    (tester) async {
      final fake = _FakeClient();
      final opened = <Uri>[];
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            usageProvider.overrideWith(
              (ref) async => UsageInfo.fromJson(_usage),
            ),
            plansProvider.overrideWith(
              (ref) => Stream.value(PlansResult.fromJson(_plans)),
            ),
            tokenPackagesProvider.overrideWith(
              (ref) => Stream.value(const [
                PackInfo(id: 'pk1', name: 'بسته', hours: 4, priceToman: 160000),
              ]),
            ),
            connectionControllerProvider.overrideWith(_PersonalConnected.new),
            personalClientProvider.overrideWith((ref) async => fake),
          ],
          child: MaterialApp(
            home: SsToastHost(
              child: PlansScreen(
                launcher: (url) async {
                  opened.add(url);
                  return true;
                },
              ),
            ),
          ),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      expect(
        find.textContaining('حدود ۱۶٫۵'.replaceAll('٫', '.')),
        findsOneWidget,
      );
      expect(find.textContaining('۲۸۰٬۰۰۰ تومان'), findsWidgets);

      await tester.tap(find.widgetWithText(FilledButton, 'خرید'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      expect(fake.started, ['plan:jn_bronze']);
      expect(opened.single.toString(), 'https://bank.test/pay');
      expect(find.text('پرداخت انجام شد؟'), findsOneWidget);

      await tester.tap(find.text('بررسی پرداخت'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      expect(fake.checked, ['o1']);
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.text('پرداخت انجام شد؟'), findsNothing);
      await tester.pump(const Duration(seconds: 6));
    },
  );
  testWidgets('coming back from the bank page confirms the payment by itself', (
    tester,
  ) async {
    final fake = _FakeClient();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          usageProvider.overrideWith((ref) async => UsageInfo.fromJson(_usage)),
          plansProvider.overrideWith(
            (ref) => Stream.value(PlansResult.fromJson(_plans)),
          ),
          tokenPackagesProvider.overrideWith((ref) => Stream.value(const [])),
          connectionControllerProvider.overrideWith(_PersonalConnected.new),
          personalClientProvider.overrideWith((ref) async => fake),
        ],
        child: MaterialApp(
          home: SsToastHost(child: PlansScreen(launcher: (url) async => true)),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(find.widgetWithText(FilledButton, 'خرید'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('پرداخت انجام شد؟'), findsOneWidget);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(fake.checked, ['o1']);
    expect(find.text('پرداخت انجام شد؟'), findsNothing);
    await tester.pump(const Duration(seconds: 6));
  });

  testWidgets('the iOS screen shows plans without a buy button', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          usageProvider.overrideWith((ref) async => UsageInfo.fromJson(_usage)),
          plansProvider.overrideWith(
            (ref) => Stream.value(PlansResult.fromJson(_plans)),
          ),
          tokenPackagesProvider.overrideWith(
            (ref) => Stream.value(const [
              PackInfo(id: 'pk1', name: 'بسته', hours: 4, priceToman: 160000),
            ]),
          ),
          personalClientProvider.overrideWith((ref) async => _FakeClient()),
        ],
        child: MaterialApp(
          home: SsToastHost(child: PlansScreen(canBuy: false)),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.widgetWithText(FilledButton, 'خرید'), findsNothing);
    await tester.drag(find.byType(ListView), const Offset(0, -900));
    await tester.pump();
    expect(find.textContaining('نسخهٔ iOS'), findsOneWidget);
  });
  testWidgets(
    'a signed-out visitor sees plans and packs; buying asks them to sign in',
    (tester) async {
      final router = GoRouter(
        routes: [
          GoRoute(
            path: '/',
            builder: (context, state) =>
                SsToastHost(child: PlansScreen(launcher: (url) async => true)),
          ),
          GoRoute(
            path: '/login',
            builder: (context, state) =>
                const Scaffold(body: Text('صفحهٔ ورود')),
          ),
        ],
      );
      // Tall enough that the packs below the plans are built too.
      await tester.binding.setSurfaceSize(const Size(400, 1800));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            plansProvider.overrideWith(
              (ref) => Stream.value(PlansResult.fromJson(_plans)),
            ),
            tokenPackagesProvider.overrideWith(
              (ref) => Stream.value(const [
                PackInfo(id: 'pk1', name: 'بسته', hours: 4, priceToman: 160000),
              ]),
            ),
          ],
          child: MaterialApp.router(routerConfig: router),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      // Browsing needs no account: plans and packs show, the usage card does not.
      expect(find.textContaining('۲۸۰٬۰۰۰ تومان'), findsWidgets);
      expect(find.textContaining('۱۶۰٬۰۰۰ تومان'), findsWidgets);
      expect(find.textContaining('حدود'), findsNothing);
      expect(
        find.text('برای خرید و دیدن میزان مصرف، وارد حساب شوید.'),
        findsOneWidget,
      );

      // Choosing is what needs the account.
      await tester.tap(find.widgetWithText(FilledButton, 'خرید'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.text('صفحهٔ ورود'), findsOneWidget);
      await tester.pump(const Duration(seconds: 6));
    },
  );

  testWidgets('a failed catalogue shows the reason and can be retried', (
    tester,
  ) async {
    var calls = 0;
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          plansProvider.overrideWith((ref) {
            calls++;
            return Stream<PlansResult>.error(
              const ApiException(
                message:
                    'فهرست دریافت نشد؛ اینترنت را بررسی کنید و دوباره تلاش کنید.',
                code: 'catalog_unavailable',
              ),
            );
          }),
          tokenPackagesProvider.overrideWith((ref) => Stream.value(const [])),
        ],
        child: MaterialApp(home: SsToastHost(child: PlansScreen())),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.textContaining('فهرست دریافت نشد'), findsOneWidget);
    expect(calls, 1);
    await tester.tap(find.text('تلاش دوباره'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(calls, 2);
  });

  testWidgets('the progress screen lists badges and sends a friend code', (
    tester,
  ) async {
    final fake = _FakeClient();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          progressProvider.overrideWith(
            (ref) async => const ProgressInfo(
              xp: 30,
              level: 2,
              levelXp: 25,
              nextLevelXp: 100,
              streakWeeks: 1,
              badges: [
                BadgeInfo(
                  code: 'first_meeting',
                  title: 'اولین جلسه',
                  description: 'اولین جلسه‌تان را ثبت کردید.',
                  current: 1,
                  threshold: 1,
                  earned: true,
                ),
                BadgeInfo(
                  code: 'five_meetings',
                  title: 'پنج جلسه',
                  description: 'پنج جلسه ثبت کرده‌اید.',
                  current: 3,
                  threshold: 5,
                  earned: false,
                ),
              ],
              newlyEarned: [],
              giftLeftHours: 0.5,
              giftLimitHours: 0.6,
            ),
          ),
          inviteProvider.overrideWith(
            (ref) async => const InviteInfo(
              code: 'MNPQ2345',
              joined: 2,
              rewardHours: 0.5,
              enabled: true,
            ),
          ),
          connectionControllerProvider.overrideWith(_PersonalConnected.new),
          personalClientProvider.overrideWith((ref) async => fake),
        ],
        child: const MaterialApp(home: SsToastHost(child: ProgressScreen())),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('اولین جلسه'), findsOneWidget);
    expect(find.text('پنج جلسه'), findsOneWidget);
    expect(find.text('MNPQ2345'), findsOneWidget);

    await tester.enterText(find.byType(TextField), 'WXYZ6789');
    await tester.ensureVisible(find.widgetWithText(FilledButton, 'ثبت'));
    await tester.pump();
    await tester.tap(find.widgetWithText(FilledButton, 'ثبت'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(fake.redeemed, ['WXYZ6789']);
    await tester.pump(const Duration(seconds: 6));
  });
}

class _FakeClient extends ApiClient {
  _FakeClient() : super(serverUrl: 'https://example.test');

  final started = <String>[];
  final checked = <String>[];
  final redeemed = <String>[];

  @override
  Future<void> redeemInvite(String code) async => redeemed.add(code);

  @override
  Future<({String orderId, String payUrl})> startPurchase({
    String? planCode,
    String? packageId,
    required String idempotencyKey,
  }) async {
    started.add(planCode != null ? 'plan:$planCode' : 'pack:$packageId');
    return (orderId: 'o1', payUrl: 'https://bank.test/pay');
  }

  @override
  Future<OrderStatus> orderStatus(String orderId) async {
    checked.add(orderId);
    return const OrderStatus(status: 'paid');
  }
}
