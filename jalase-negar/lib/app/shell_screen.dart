import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../features/upload/upload_controller.dart';
import 'theme.dart';
import 'widgets/ss_widgets.dart';

class ShellScreen extends ConsumerWidget {
  const ShellScreen({super.key, required this.child});

  final Widget child;

  int _currentIndex(BuildContext context) {
    final location = GoRouterState.of(context).uri.path;
    if (location.startsWith('/settings')) return 1;
    return 0;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Keeps the upload queue alive for the whole app session.
    ref.watch(uploadQueueProvider.select((s) => s.running));
    final index = _currentIndex(context);

    return Scaffold(
      appBar: SsAppBar(
        title: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(index == 0 ? 'جلسه‌نگار' : 'تنظیمات'),
            const SizedBox(width: 8),
            const SsBadge('آزمایشی', color: SsColors.accent),
          ],
        ),
        centerTitle: false,
        actions: [
          // Info/Team icon
          IconButton(
            tooltip: 'تولیدکنندگان',
            icon: const Icon(Icons.info_outline),
            onPressed: () => context.push('/team'),
          ),
          // Models icon
          IconButton(
            tooltip: 'مدل‌ها',
            icon: const Icon(Icons.download_for_offline_outlined),
            onPressed: () => context.push('/models'),
          ),
        ],
      ),
      body: child,
      bottomNavigationBar: DecoratedBox(
        decoration: const BoxDecoration(
          border: Border(top: BorderSide(color: SsColors.line)),
        ),
        child: NavigationBar(
          selectedIndex: index,
          onDestinationSelected: (i) {
            switch (i) {
              case 0:
                context.go('/');
              case 1:
                context.go('/settings');
            }
          },
          destinations: const [
            NavigationDestination(
              icon: Icon(Icons.mic_outlined),
              selectedIcon: Icon(Icons.mic),
              label: 'جلسات',
            ),
            NavigationDestination(
              icon: Icon(Icons.settings_outlined),
              selectedIcon: Icon(Icons.settings),
              label: 'تنظیمات',
            ),
          ],
        ),
      ),
    );
  }
}
