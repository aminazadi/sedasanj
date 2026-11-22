import 'package:flutter/material.dart' hide ConnectionState;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/platform/api_client.dart';
import 'package:jalase_negar/core/platform/platform_config.dart';
import 'package:jalase_negar/features/meetings/presentation/meeting_output_tab.dart';
import 'package:jalase_negar/features/plans/data/billing_models.dart';
import 'package:jalase_negar/features/settings/application/connection_controller.dart';

const _connection = PlatformConnection(
  serverUrl: 'https://example.test',
  userName: 'کاربر',
  tenantName: '',
  tokenPrefix: 'abc',
  personal: true,
);

class _Disconnected extends ConnectionController {
  @override
  Future<ConnectionState> build() async => const ConnectionState();
}

class _Connected extends ConnectionController {
  @override
  Future<ConnectionState> build() async =>
      const ConnectionState(connection: _connection);
}

Future<void> _pump(
  WidgetTester tester, {
  required List<Override> overrides,
}) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: overrides,
      child: const MaterialApp(
        home: Directionality(
          textDirection: TextDirection.rtl,
          child: Scaffold(body: MeetingOutputTab(remoteMeetingId: 'remote-1')),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('asks a signed-out account to sign in', (tester) async {
    await _pump(
      tester,
      overrides: [connectionControllerProvider.overrideWith(_Disconnected.new)],
    );

    expect(find.text('برای دیدن خروجی جلسه وارد حساب شوید'), findsOneWidget);
    expect(find.text('ورود با شماره موبایل'), findsOneWidget);
    expect(find.text('صورت‌جلسه'), findsNothing);
  });

  testWidgets('asks a signed-in account with no usable plan to buy one', (
    tester,
  ) async {
    await _pump(
      tester,
      overrides: [
        connectionControllerProvider.overrideWith(_Connected.new),
        usageProvider.overrideWith(
          (ref) async => const UsageInfo(unlimited: false, exhausted: true),
        ),
      ],
    );

    expect(
      find.text('برای دریافت خروجی جلسه، به پلن فعال نیاز دارید'),
      findsOneWidget,
    );
    expect(find.text('پلن و مصرف'), findsOneWidget);
    expect(find.text('صورت‌جلسه'), findsNothing);
  });

  testWidgets(
    'keeps the output visible with a banner when the plan check fails',
    (tester) async {
      await _pump(
        tester,
        overrides: [
          connectionControllerProvider.overrideWith(_Connected.new),
          usageProvider.overrideWith(
            (ref) async => throw const ApiException(
              message: 'خطای سرور (500)؛ کمی بعد دوباره تلاش کنید.',
              statusCode: 500,
            ),
          ),
          meetingMinutesProvider('remote-1').overrideWith(
            (ref) async => const MinutesResult(
              status: 'ready',
              markdown: 'صورت‌جلسه آماده است',
            ),
          ),
          meetingDocumentsProvider(
            'remote-1',
          ).overrideWith((ref) async => const []),
          outputTypesProvider.overrideWith((ref) async => const []),
        ],
      );

      expect(find.textContaining('HTTP 500'), findsOneWidget);
      expect(find.text('بررسی دوباره'), findsOneWidget);
      expect(find.text('صورت‌جلسه آماده است'), findsOneWidget);
    },
  );

  testWidgets(
    'a revoked device asks to sign in again instead of showing output',
    (tester) async {
      await _pump(
        tester,
        overrides: [
          connectionControllerProvider.overrideWith(_Connected.new),
          usageProvider.overrideWith(
            (ref) async => throw const ApiException(
              message: 'توکن ابطال شده است',
              code: 'unauthorized',
              statusCode: 401,
              requiresReconnect: true,
            ),
          ),
        ],
      );

      expect(find.textContaining('نشست این دستگاه معتبر نیست'), findsOneWidget);
      expect(find.text('صورت‌جلسه'), findsNothing);
    },
  );

  testWidgets('shows the minutes and documents sub-tabs when entitled', (
    tester,
  ) async {
    await _pump(
      tester,
      overrides: [
        connectionControllerProvider.overrideWith(_Connected.new),
        usageProvider.overrideWith(
          (ref) async => const UsageInfo(unlimited: false, exhausted: false),
        ),
        meetingMinutesProvider('remote-1').overrideWith(
          (ref) async => const MinutesResult(
            status: 'ready',
            markdown: 'صورت‌جلسه آماده است',
          ),
        ),
        meetingDocumentsProvider(
          'remote-1',
        ).overrideWith((ref) async => const []),
        outputTypesProvider.overrideWith((ref) async => const []),
      ],
    );

    expect(find.text('صورت‌جلسه'), findsOneWidget);
    expect(find.text('اسناد'), findsOneWidget);
    expect(find.text('صورت‌جلسه آماده است'), findsOneWidget);

    await tester.tap(find.widgetWithText(Tab, 'اسناد'));
    await tester.pumpAndSettle();
    expect(find.text('ساخت سند در دستهٔ دیگر'), findsOneWidget);
  });
}
