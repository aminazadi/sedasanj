import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/app/theme.dart';
import 'package:jalase_negar/app/theme_mode_controller.dart';
import 'package:jalase_negar/features/settings/presentation/theme_mode_card.dart';

class _Fixed extends ThemeModeNotifier {
  _Fixed(this.initial);
  final ThemeMode initial;
  ThemeMode? chosen;

  @override
  Future<ThemeMode> build() async => initial;

  @override
  Future<void> setMode(ThemeMode mode) async {
    chosen = mode;
    state = AsyncData(mode);
  }
}

void main() {
  test('a stored string round-trips through ThemeMode', () {
    expect(themeModeFromStored('light'), ThemeMode.light);
    expect(themeModeFromStored('dark'), ThemeMode.dark);
    expect(themeModeFromStored('system'), ThemeMode.system);
    // Unknown or missing values default to following the system.
    expect(themeModeFromStored(null), ThemeMode.system);
    expect(themeModeFromStored('junk'), ThemeMode.system);

    expect(themeModeToStored(ThemeMode.light), 'light');
    expect(themeModeToStored(ThemeMode.dark), 'dark');
    expect(themeModeToStored(ThemeMode.system), 'system');
  });

  test('the dark palette resolves into the dark ThemeData', () {
    final theme = buildAppTheme(Brightness.dark);
    expect(theme.brightness, Brightness.dark);
    final palette = theme.extension<SsColors>();
    expect(palette, isNotNull);
    expect(palette, SsColors.dark);
    expect(theme.scaffoldBackgroundColor, SsColors.dark.canvas);
  });

  testWidgets('the three segments pick light, dark and system', (tester) async {
    final notifier = _Fixed(ThemeMode.system);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [themeModeProvider.overrideWith(() => notifier)],
        child: MaterialApp(
          theme: buildAppTheme(),
          home: const Directionality(
            textDirection: TextDirection.rtl,
            child: Scaffold(body: ThemeModeCard()),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final segmented = tester.widget<SegmentedButton<ThemeMode>>(
      find.byType(SegmentedButton<ThemeMode>),
    );
    expect(segmented.selected, {ThemeMode.system});

    segmented.onSelectionChanged!({ThemeMode.dark});
    await tester.pump();
    expect(notifier.chosen, ThemeMode.dark);
  });
}
