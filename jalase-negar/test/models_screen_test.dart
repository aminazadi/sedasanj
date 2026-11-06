import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/app/theme.dart';
import 'package:jalase_negar/core/models/model_catalog.dart';
import 'package:jalase_negar/features/models/application/models_controller.dart';
import 'package:jalase_negar/features/models/presentation/models_screen.dart';

class _Models extends ModelsController {
  _Models(this._ready);
  final bool _ready;
  var installs = 0;

  @override
  ModelsState build() => ModelsState(
    loading: false,
    items: [
      for (final spec in ModelCatalog.all)
        ModelItemState(spec: spec, installed: _ready, selected: _ready),
    ],
  );

  @override
  Future<void> installAll() async => installs++;
}

Future<_Models> _open(WidgetTester tester, {required bool ready}) async {
  final fake = _Models(ready);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [modelsControllerProvider.overrideWith(() => fake)],
      child: MaterialApp(
        theme: buildAppTheme(),
        home: const Directionality(
          textDirection: TextDirection.rtl,
          child: ModelsScreen(),
        ),
      ),
    ),
  );
  return fake;
}

void main() {
  testWidgets('shows one install-all action and no model names', (
    tester,
  ) async {
    final fake = await _open(tester, ready: false);
    expect(find.text('دانلود، نصب و فعال‌سازی'), findsOneWidget);
    for (final spec in ModelCatalog.all) {
      expect(find.textContaining(spec.nameFa), findsNothing);
    }
    expect(find.text('پیشنهادی'), findsNothing);
    await tester.tap(find.text('شروع'));
    expect(fake.installs, 1);
  });

  testWidgets('shows only the ready state once everything is active', (
    tester,
  ) async {
    await _open(tester, ready: true);
    expect(find.text('نصب و فعال است'), findsOneWidget);
    expect(find.text('شروع'), findsNothing);
  });
}
