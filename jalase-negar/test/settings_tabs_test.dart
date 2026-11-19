import 'package:flutter/material.dart' hide ConnectionState;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/app/theme.dart';
import 'package:jalase_negar/core/models/model_catalog.dart';
import 'package:jalase_negar/features/models/application/models_controller.dart';
import 'package:jalase_negar/features/settings/application/connection_controller.dart';
import 'package:jalase_negar/features/settings/presentation/settings_screen.dart';

class _Disconnected extends ConnectionController {
  @override
  Future<ConnectionState> build() async => const ConnectionState();
}

class _ReadyModels extends ModelsController {
  @override
  ModelsState build() => ModelsState(
    loading: false,
    items: [
      for (final spec in ModelCatalog.all)
        ModelItemState(spec: spec, installed: true, selected: true),
    ],
  );
}

void main() {
  testWidgets('settings are split into account, recording, models and app '
      'tabs', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          connectionControllerProvider.overrideWith(_Disconnected.new),
          modelsControllerProvider.overrideWith(_ReadyModels.new),
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

    for (final label in ['حساب', 'ضبط و ارسال', 'مدل‌ها', 'برنامه']) {
      expect(find.widgetWithText(Tab, label), findsOneWidget);
    }
    // The account tab opens first and holds the connection status and sign-in.
    expect(find.text('وضعیت اتصال'), findsOneWidget);
    expect(find.text('ورود با شماره موبایل'), findsOneWidget);
    // Recording options are not crowding the account tab.
    expect(find.text('نوشتن نام گوینده در متن'), findsNothing);

    await tester.tap(find.widgetWithText(Tab, 'مدل‌ها'));
    await tester.pumpAndSettle();
    expect(find.text('نصب و فعال است'), findsOneWidget);
  });
}
