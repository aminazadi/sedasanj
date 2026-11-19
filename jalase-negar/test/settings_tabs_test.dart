import 'package:flutter/material.dart' hide ConnectionState;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/app/theme.dart';
import 'package:jalase_negar/features/settings/application/connection_controller.dart';
import 'package:jalase_negar/features/settings/presentation/settings_screen.dart';

class _Disconnected extends ConnectionController {
  @override
  Future<ConnectionState> build() async => const ConnectionState();
}

void main() {
  testWidgets('settings are split into account, recording and app tabs', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          connectionControllerProvider.overrideWith(_Disconnected.new),
        ],
        child: MaterialApp(
          theme: buildAppTheme(),
          home: const Directionality(
            textDirection: TextDirection.rtl,
            child: Scaffold(body: SettingsScreen()),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    for (final label in ['حساب', 'ضبط و ارسال', 'برنامه']) {
      expect(find.widgetWithText(Tab, label), findsOneWidget);
    }
    // The account tab opens first and holds the connection status and sign-in.
    expect(find.text('وضعیت اتصال'), findsOneWidget);
    expect(find.text('ورود با شماره موبایل'), findsOneWidget);
    // Recording options are not crowding the account tab.
    expect(find.text('نوشتن نام گوینده در متن'), findsNothing);
  });
}
