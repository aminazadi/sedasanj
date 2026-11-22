import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/theme_mode_controller.dart';
import '../../../app/widgets/ss_widgets.dart';

/// Settings entry for choosing the app's appearance: light, dark or follow
/// the phone's own setting.
class ThemeModeCard extends ConsumerWidget {
  const ThemeModeCard({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(themeModeProvider).value ?? ThemeMode.system;
    final notifier = ref.read(themeModeProvider.notifier);
    return SsCard(
      title: 'ظاهر برنامه',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text('روشن، تاریک یا پیروی از تنظیمات گوشی را انتخاب کنید.'),
          const SizedBox(height: 12),
          SegmentedButton<ThemeMode>(
            segments: const [
              ButtonSegment(
                value: ThemeMode.light,
                label: Text('روشن'),
                icon: Icon(Icons.light_mode_outlined),
              ),
              ButtonSegment(
                value: ThemeMode.dark,
                label: Text('تاریک'),
                icon: Icon(Icons.dark_mode_outlined),
              ),
              ButtonSegment(
                value: ThemeMode.system,
                label: Text('سیستم'),
                icon: Icon(Icons.brightness_auto_outlined),
              ),
            ],
            selected: {mode},
            onSelectionChanged: (selection) =>
                notifier.setMode(selection.first),
          ),
        ],
      ),
    );
  }
}
