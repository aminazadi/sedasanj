import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers.dart';

const _seenKey = 'intro_slides_seen';

/// Whether the first-run intro slides were already shown on this install.
final introProgressProvider = AsyncNotifierProvider<IntroProgress, bool>(
  IntroProgress.new,
);

class IntroProgress extends AsyncNotifier<bool> {
  @override
  Future<bool> build() async {
    final db = await ref.watch(appDatabaseProvider.future);
    return await db.getSetting(_seenKey) == '1';
  }

  Future<void> markSeen() async {
    final db = await ref.read(appDatabaseProvider.future);
    await db.setSetting(_seenKey, '1');
    state = const AsyncData(true);
  }
}
