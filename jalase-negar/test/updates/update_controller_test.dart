// ignore_for_file: library_private_types_in_public_api
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/features/updates/application/update_controller.dart';
import 'package:jalase_negar/features/updates/data/app_update.dart';
import 'package:jalase_negar/features/updates/data/update_client.dart';

import 'update_test_support.dart';

class _FakeClient extends UpdateClient {
  _FakeClient(this.answer);

  Object? answer;
  int calls = 0;

  @override
  Future<AppUpdateOffer?> check(UpdateEnvironment environment) async {
    calls++;
    final value = answer;
    if (value is UpdateCheckException) throw value;
    if (value is Error || value is Exception) throw value as Object;
    return AppUpdateOffer.fromResponse(value);
  }
}

ProviderContainer containerFor(
  _FakeClient client, {
  UpdateEnvironment? environment = installedApp,
  bool launches = true,
  List<Uri>? opened,
}) {
  return ProviderContainer(
    overrides: [
      updateClientProvider.overrideWithValue(client),
      updateEnvironmentProvider.overrideWithValue(() async => environment),
      updateLauncherProvider.overrideWithValue((uri) async {
        opened?.add(uri);
        return launches;
      }),
    ],
  );
}

void main() {
  test('launch check keeps a newer offer and stays quiet otherwise', () async {
    final client = _FakeClient(offerJson());
    final container = containerFor(client);
    addTearDown(container.dispose);
    await container.read(updateControllerProvider.notifier).checkOnLaunch();
    final state = container.read(updateControllerProvider);
    expect(state.pending, isTrue);
    expect(state.offer!.versionCode, 3);
    expect(state.installed!.versionName, '1.0.1');
  });

  test('launch check runs once per cold start', () async {
    final client = _FakeClient({'update': null});
    final container = containerFor(client);
    addTearDown(container.dispose);
    final notifier = container.read(updateControllerProvider.notifier);
    await notifier.checkOnLaunch();
    await notifier.checkOnLaunch();
    expect(client.calls, 1);
  });

  test('equal or older builds are never offered', () async {
    for (final code in [2, 1]) {
      final container = containerFor(_FakeClient(offerJson(code: code)));
      addTearDown(container.dispose);
      await container.read(updateControllerProvider.notifier).checkOnLaunch();
      expect(container.read(updateControllerProvider).pending, isFalse);
      expect(container.read(updateControllerProvider).offer, isNull);
    }
  });

  test('offline, timeout and bad answers are silent at launch', () async {
    for (final answer in <Object>[
      const UpdateCheckException('offline'),
      Exception('boom'),
      <String, Object?>{},
    ]) {
      final container = containerFor(_FakeClient(answer));
      addTearDown(container.dispose);
      await container.read(updateControllerProvider.notifier).checkOnLaunch();
      expect(container.read(updateControllerProvider).pending, isFalse);
    }
  });

  test('works without any pairing: no provider needs a connection', () async {
    final container = containerFor(_FakeClient(offerJson()));
    addTearDown(container.dispose);
    await container.read(updateControllerProvider.notifier).checkOnLaunch();
    expect(container.read(updateControllerProvider).pending, isTrue);
  });

  test('"later" hides the offer until the next cold start only', () async {
    final container = containerFor(_FakeClient(offerJson()));
    addTearDown(container.dispose);
    final notifier = container.read(updateControllerProvider.notifier);
    await notifier.checkOnLaunch();
    notifier.postpone();
    expect(container.read(updateControllerProvider).pending, isFalse);
    expect(container.read(updateControllerProvider).offer, isNotNull);

    // A new process starts with a fresh container and asks again.
    final next = containerFor(_FakeClient(offerJson()));
    addTearDown(next.dispose);
    await next.read(updateControllerProvider.notifier).checkOnLaunch();
    expect(next.read(updateControllerProvider).pending, isTrue);
  });

  test('manual check explains every outcome in Persian', () async {
    var container = containerFor(_FakeClient({'update': null}));
    addTearDown(container.dispose);
    var result = await container
        .read(updateControllerProvider.notifier)
        .checkManually();
    expect(result.offer, isNull);
    expect(result.message, contains('وجود ندارد'));

    container = containerFor(
      _FakeClient(const UpdateCheckException('اینترنت را بررسی کنید')),
    );
    addTearDown(container.dispose);
    result = await container
        .read(updateControllerProvider.notifier)
        .checkManually();
    expect(result.message, contains('اینترنت'));

    container = containerFor(_FakeClient(offerJson()), environment: null);
    addTearDown(container.dispose);
    result = await container
        .read(updateControllerProvider.notifier)
        .checkManually();
    expect(result.message, isNotNull);
  });

  test('manual check can bring back an offer that was set aside', () async {
    final container = containerFor(_FakeClient(offerJson()));
    addTearDown(container.dispose);
    final notifier = container.read(updateControllerProvider.notifier);
    await notifier.checkOnLaunch();
    notifier.postpone();
    final result = await notifier.checkManually();
    expect(result.offer, isNotNull);
    expect(container.read(updateControllerProvider).pending, isTrue);
  });

  test('download opens only the central origin and reports a failure', () async {
    final opened = <Uri>[];
    var container = containerFor(_FakeClient(offerJson()), opened: opened);
    addTearDown(container.dispose);
    var notifier = container.read(updateControllerProvider.notifier);
    await notifier.checkOnLaunch();
    expect(await notifier.download(), isNull);
    expect(opened.single.origin, 'https://api.sedasanj.ir');

    container = containerFor(_FakeClient(offerJson()), launches: false);
    addTearDown(container.dispose);
    notifier = container.read(updateControllerProvider.notifier);
    await notifier.checkOnLaunch();
    expect(await notifier.download(), contains('مرورگر'));
  });
}
