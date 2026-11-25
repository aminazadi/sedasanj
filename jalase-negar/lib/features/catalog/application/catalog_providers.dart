import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/platform/api_client.dart';
import '../../../core/platform/distribution.dart';
import '../../../core/providers.dart';
import '../../meetings/data/meeting.dart';
import '../../plans/data/billing_models.dart';
import '../../settings/application/connection_controller.dart';
import '../data/catalog_repository.dart';

/// The catalogue repository, pointed at the connected server or the default one. It is
/// usable without signing in.
final catalogRepositoryProvider = FutureProvider<CatalogRepository>((ref) async {
  final db = await ref.watch(appDatabaseProvider.future);
  final server =
      (await ref.watch(connectionControllerProvider.future)).connection?.serverUrl ??
      kDefaultServerUrl;
  return CatalogRepository(db: db, serverUrl: server);
});

/// The built-in category, always offered even when the catalogue cannot be reached yet.
const _builtinMinutes = OutputTypeInfo(
  code: kBuiltinOutputType,
  title: 'صورت جلسه عمومی',
  description: 'صورت‌جلسه‌ی کامل این جلسه؛ همیشه در دسترس است.',
  automatic: true,
  fields: [],
);

/// Every published category, the built-in minutes included (pre-recording picker).
final meetingTypesProvider = StreamProvider<List<OutputTypeInfo>>((ref) async* {
  final repo = await ref.watch(catalogRepositoryProvider.future);
  try {
    await for (final value in repo.outputTypes()) {
      yield value.value;
    }
  } on Object {
    yield const [_builtinMinutes];
  }
});

/// Categories for "add another category" (the built-in minutes is left out).
final outputTypesProvider = StreamProvider<List<OutputTypeInfo>>((ref) async* {
  final repo = await ref.watch(catalogRepositoryProvider.future);
  await for (final value in repo.outputTypes()) {
    yield [
      for (final type in value.value)
        if (!type.automatic) type,
    ];
  }
});

final plansProvider = StreamProvider<PlansResult>((ref) async* {
  final repo = await ref.watch(catalogRepositoryProvider.future);
  await for (final value in repo.plans()) {
    yield value.value;
  }
});

final tokenPackagesProvider = StreamProvider<List<PackInfo>>((ref) async* {
  final repo = await ref.watch(catalogRepositoryProvider.future);
  await for (final value in repo.tokenPackages()) {
    yield value.value;
  }
});
