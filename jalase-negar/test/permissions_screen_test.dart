import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/app/theme.dart';
import 'package:jalase_negar/core/platform/app_permissions.dart';
import 'package:jalase_negar/features/onboarding/permissions_screen.dart';

class _FakeGateway implements PermissionGateway {
  _FakeGateway({this.denyBackground = false});

  final bool denyBackground;
  final granted = <AppPermission>{};
  final asked = <AppPermission>[];

  @override
  List<AppPermission> get supported => AppPermission.values;

  @override
  Future<bool> isGranted(AppPermission permission) async =>
      granted.contains(permission);

  @override
  Future<bool> request(AppPermission permission) async {
    asked.add(permission);
    if (permission == AppPermission.background && denyBackground) return false;
    granted.add(permission);
    return true;
  }
}

void _tall(WidgetTester tester) {
  tester.view.physicalSize = const Size(800, 2400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

Widget _app(PermissionGateway gateway, VoidCallback onDone) => MaterialApp(
  theme: buildAppTheme(),
  home: PermissionsScreen(gateway: gateway, onDone: onDone),
);

void main() {
  testWidgets('asks microphone, notification and background in one go', (
    tester,
  ) async {
    _tall(tester);
    final gateway = _FakeGateway();
    var done = 0;
    await tester.pumpWidget(_app(gateway, () => done++));
    await tester.pumpAndSettle();
    expect(find.text('فعلاً رد می‌کنم'), findsOneWidget);

    await tester.tap(find.text('اجازه دادن'));
    await tester.pumpAndSettle();
    expect(gateway.asked, AppPermission.values);
    expect(find.text('ادامه'), findsOneWidget);

    await tester.tap(find.text('ادامه'));
    expect(done, 1);
  });

  testWidgets('a refused permission never blocks the user', (tester) async {
    _tall(tester);
    final gateway = _FakeGateway(denyBackground: true);
    var done = 0;
    await tester.pumpWidget(_app(gateway, () => done++));
    await tester.pumpAndSettle();
    await tester.tap(find.text('اجازه دادن'));
    await tester.pumpAndSettle();
    // Still offered again, and the user can leave anyway.
    expect(find.text('اجازه دادن'), findsOneWidget);
    await tester.tap(find.text('فعلاً رد می‌کنم'));
    expect(done, 1);
  });

  test('every permission has a Persian explanation', () {
    for (final p in AppPermission.values) {
      expect(kPermissionInfo[p], isNotNull, reason: '$p');
    }
  });
}
