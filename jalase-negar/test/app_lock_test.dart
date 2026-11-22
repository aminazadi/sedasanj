import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/app/widgets/ss_widgets.dart';
import 'package:jalase_negar/features/app_lock/application/app_lock_providers.dart';
import 'package:jalase_negar/features/app_lock/application/app_lock_service.dart';
import 'package:jalase_negar/features/app_lock/presentation/app_lock_settings_card.dart';
import 'package:jalase_negar/app/widgets/ss_toast.dart';

class _FakeService implements AppLockService {
  _FakeService({this.supported = true, required this.result});

  bool supported;
  AppLockAuthResult result;
  int authenticateCalls = 0;

  @override
  Future<bool> isSupported() async => supported;

  @override
  Future<AppLockAuthResult> authenticate() async {
    authenticateCalls++;
    return result;
  }
}

class _FixedEnabled extends AppLockEnabled {
  _FixedEnabled(this.initial);
  final bool initial;

  @override
  Future<bool> build() async => initial;

  @override
  Future<void> set(bool enabled) async {
    state = AsyncData(enabled);
  }
}

void main() {
  group('AppLockRuntime', () {
    test('lock/unlock only notify on an actual change', () {
      final runtime = AppLockRuntime();
      var notifications = 0;
      runtime.addListener(() => notifications++);

      runtime.lock();
      expect(runtime.locked, isTrue);
      expect(notifications, 1);

      runtime.lock(); // already locked: no extra notification
      expect(notifications, 1);

      runtime.unlock();
      expect(runtime.locked, isFalse);
      expect(notifications, 2);
    });
  });

  group('mapAuthException', () {
    test('maps each local_auth code to a Persian message and the right type', () {
      expect(
        mapAuthException(PlatformException(code: 'NotAvailable')),
        isA<AppLockUnsupported>(),
      );
      expect(
        mapAuthException(PlatformException(code: 'NotEnrolled')),
        isA<AppLockUnsupported>(),
      );
      expect(
        mapAuthException(PlatformException(code: 'PasscodeNotSet')),
        isA<AppLockUnsupported>(),
      );
      final lockedOut = mapAuthException(PlatformException(code: 'LockedOut'));
      expect(lockedOut, isA<AppLockFailed>());
      expect((lockedOut as AppLockFailed).canRetry, isTrue);
      expect(
        mapAuthException(PlatformException(code: 'PermanentlyLockedOut')),
        isA<AppLockFailed>(),
      );
      expect(
        mapAuthException(PlatformException(code: 'something_else')),
        isA<AppLockFailed>(),
      );
    });
  });

  group('AppLockSettingsCard', () {
    Widget harness(ProviderContainer container) => UncontrolledProviderScope(
      container: container,
      child: MaterialApp(
        builder: (context, child) => SsToastHost(child: child!),
        home: const Directionality(
          textDirection: TextDirection.rtl,
          child: Scaffold(body: AppLockSettingsCard()),
        ),
      ),
    );

    testWidgets('disables the switch and explains when unsupported', (
      tester,
    ) async {
      final container = ProviderContainer(
        overrides: [
          appLockServiceProvider.overrideWithValue(
            _FakeService(
              supported: false,
              result: const AppLockFailed(''),
            ),
          ),
          appLockEnabledProvider.overrideWith(() => _FixedEnabled(false)),
        ],
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(harness(container));
      await tester.pumpAndSettle();

      final switchWidget = tester.widget<SsSwitch>(find.byType(SsSwitch));
      expect(switchWidget.onChanged, isNull);
      expect(find.textContaining('باید اثر انگشت'), findsOneWidget);
    });

    testWidgets('enabling requires a successful authentication first', (
      tester,
    ) async {
      final fakeService = _FakeService(
        supported: true,
        result: const AppLockFailed('شکست'),
      );
      final container = ProviderContainer(
        overrides: [
          appLockServiceProvider.overrideWithValue(fakeService),
          appLockEnabledProvider.overrideWith(() => _FixedEnabled(false)),
        ],
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(harness(container));
      await tester.pumpAndSettle();

      await tester.tap(find.byType(SsSwitch));
      await tester.pumpAndSettle();
      expect(container.read(appLockEnabledProvider).value, isFalse);
      expect(fakeService.authenticateCalls, 1);

      fakeService.result = const AppLockSuccess();
      await tester.tap(find.byType(SsSwitch));
      await tester.pumpAndSettle();
      expect(container.read(appLockEnabledProvider).value, isTrue);
    });
  });
}
