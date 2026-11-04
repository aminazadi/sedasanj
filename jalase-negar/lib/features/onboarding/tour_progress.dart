import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

const _seenKey = 'onboarding_tour_seen';

final tourProgressProvider = AsyncNotifierProvider<TourProgress, bool>(
  TourProgress.new,
);

class TourProgress extends AsyncNotifier<bool> {
  @override
  Future<bool> build() async {
    try {
      final db = await ref.watch(appDatabaseProvider.future);
      return await db.getSetting(_seenKey) == '1';
    } catch (_) {
      return false;
    }
  }

  Future<void> finish({required bool persist}) async {
    await future;
    if (persist) {
      final db = await ref.read(appDatabaseProvider.future);
      await db.setSetting(_seenKey, '1');
    }
    state = const AsyncData(true);
  }
}
