import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/providers.dart';

const kThemeModeSettingKey = 'theme_mode';

ThemeMode themeModeFromStored(String? value) => switch (value) {
  'light' => ThemeMode.light,
  'dark' => ThemeMode.dark,
  _ => ThemeMode.system,
};

String themeModeToStored(ThemeMode mode) => switch (mode) {
  ThemeMode.light => 'light',
  ThemeMode.dark => 'dark',
  ThemeMode.system => 'system',
};

/// The owner's chosen appearance (light/dark/follow system), persisted like
/// the rest of the app's local settings (see [kCpuCoresSettingKey]).
final themeModeProvider = AsyncNotifierProvider<ThemeModeNotifier, ThemeMode>(
  ThemeModeNotifier.new,
);

class ThemeModeNotifier extends AsyncNotifier<ThemeMode> {
  @override
  Future<ThemeMode> build() async {
    final db = await ref.watch(appDatabaseProvider.future);
    final raw = await db.getSetting(kThemeModeSettingKey);
    return themeModeFromStored(raw);
  }

  Future<void> setMode(ThemeMode mode) async {
    final db = await ref.read(appDatabaseProvider.future);
    await db.setSetting(kThemeModeSettingKey, themeModeToStored(mode));
    state = AsyncData(mode);
  }
}
