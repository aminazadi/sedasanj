import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/features/updates/application/update_background.dart';
import 'package:jalase_negar/features/updates/application/update_controller.dart';
import 'package:jalase_negar/features/updates/data/app_update.dart';
import 'package:jalase_negar/features/updates/data/update_client.dart';
import 'package:jalase_negar/features/updates/data/update_native.dart';

import 'update_test_support.dart';

class _Native extends UpdateNative {
  _Native({this.ready = false});

  final bool ready;
  int installCalls = 0;
  int scheduled = 0;

  @override
  Future<bool> installDownloaded() async {
    installCalls++;
    return ready;
  }

  @override
  Future<void> scheduleBackgroundUpdates() async => scheduled++;
}

class _Client extends UpdateClient {
  @override
  Future<AppUpdateOffer?> check(UpdateEnvironment environment) async =>
      AppUpdateOffer.fromResponse(offerJson());
}

class _NoPublisher extends UpdateCalmPublisher {
  @override
  void build() {}
}

ProviderContainer _container(_Native native, List<Uri> opened) =>
    ProviderContainer(
      overrides: [
        updateNativeProvider.overrideWithValue(native),
        updateCalmPublisherProvider.overrideWith(_NoPublisher.new),
        updateClientProvider.overrideWithValue(_Client()),
        updateEnvironmentProvider.overrideWithValue(() async => installedApp),
        updateLauncherProvider.overrideWithValue((uri) async {
          opened.add(uri);
          return true;
        }),
      ],
    );

Map<String, Object?> _with(String key, Object? value) => {
  'update': <String, Object?>{
    ...(offerJson()['update']! as Map<String, Object?>),
    key: value,
  },
};

void main() {
  test('offer carries sha256, min_sdk and the mandatory flag', () {
    final offer = AppUpdateOffer.fromResponse(offerJson())!;
    expect(offer.sha256, 'f' * 64);
    expect(offer.minSdk, 24);
    expect(offer.mandatory, isFalse);
    expect(offer.canAutoInstall, isTrue);

    expect(
      AppUpdateOffer.fromResponse(_with('mandatory', true))!.mandatory,
      isTrue,
    );
  });

  test('a missing or malformed checksum disables automatic install', () {
    for (final Object? bad in <Object?>[null, 'xyz', 'F' * 63]) {
      final offer = AppUpdateOffer.fromResponse(_with('sha256', bad))!;
      expect(offer.sha256, isEmpty);
      expect(offer.canAutoInstall, isFalse);
    }
  });

  test('uppercase checksums are normalised to lowercase hex', () {
    final body = offerJson();
    (body['update']! as Map)['sha256'] = 'AB' * 32;
    expect(AppUpdateOffer.fromResponse(body)!.sha256, 'ab' * 32);
  });

  test('install id joins the query only when present', () {
    expect(installedApp.toQuery().containsKey('install_id'), isFalse);
    const withId = UpdateEnvironment(
      versionName: '1.0.1',
      versionCode: 2,
      sdkInt: 34,
      abis: ['arm64-v8a'],
      certSha256: 'a',
      installId: '3f2b8c1e-5d4a-4e7b-9a10-6c2d8e4f1a77',
    );
    expect(withId.toQuery()['install_id'], withId.installId);
  });

  test(
    '"دریافت نسخه" installs a downloaded update before opening the browser',
    () async {
      final native = _Native(ready: true);
      final opened = <Uri>[];
      final container = _container(native, opened);
      addTearDown(container.dispose);
      final notifier = container.read(updateControllerProvider.notifier);
      await notifier.checkOnLaunch();
      expect(await notifier.download(), isNull);
      expect(native.installCalls, 1);
      expect(opened, isEmpty);
    },
  );

  test('without a downloaded update the browser fallback is used', () async {
    final native = _Native();
    final opened = <Uri>[];
    final container = _container(native, opened);
    addTearDown(container.dispose);
    final notifier = container.read(updateControllerProvider.notifier);
    await notifier.checkOnLaunch();
    expect(await notifier.download(), isNull);
    expect(native.installCalls, 1);
    expect(opened.single.path, contains('/download'));
  });

  test(
    'background updates are registered through the native channel',
    () async {
      final native = _Native();
      final container = _container(native, []);
      addTearDown(container.dispose);
      await container
          .read(updateControllerProvider.notifier)
          .startBackgroundUpdates();
      expect(native.scheduled, 1);
    },
  );
}
