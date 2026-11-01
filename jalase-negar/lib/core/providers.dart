import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../features/meetings/data/meeting_repository.dart';
import 'db/app_database.dart';
import 'io/app_paths.dart';
import 'models/download_manager.dart';
import 'models/model_store.dart';

final appPathsProvider = FutureProvider<AppPaths>((ref) => AppPaths.instance());

final appDatabaseProvider = FutureProvider<AppDatabase>(
  (ref) => AppDatabase.instance(),
);

final modelStoreProvider = FutureProvider<ModelStore>((ref) async {
  final paths = await ref.watch(appPathsProvider.future);
  return ModelStore(paths);
});

final modelDownloaderProvider = FutureProvider<ModelDownloader>((ref) async {
  final store = await ref.watch(modelStoreProvider.future);
  return ModelDownloader(store);
});

final meetingRepositoryProvider = FutureProvider<MeetingRepository>((
  ref,
) async {
  final db = await ref.watch(appDatabaseProvider.future);
  final paths = await ref.watch(appPathsProvider.future);
  final repo = MeetingRepository(db);
  await repo.recoverStaleStatuses();
  await repo.recoverInterruptedRecordings(paths.chunksDir.path);
  return repo;
});
