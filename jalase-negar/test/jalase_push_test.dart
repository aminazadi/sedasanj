import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/features/push/jalase_push.dart';

void main() {
  test(
    'notification IDs remain stable and replacement uses a separate slot',
    () {
      const first = '6c081cfe-1af8-4881-beb6-61955e2cd4c8';
      const second = 'b3d97465-b263-480f-9a31-352f0d23ca18';
      expect(notificationId(first, false), notificationId(first, false));
      expect(
        notificationId(first, false),
        isNot(notificationId(second, false)),
      );
      expect(notificationId(first, true), notificationId(second, true));
      expect(notificationId(first, true), isNot(notificationId(first, false)));
    },
  );

  test('notification taps resolve only supported app destinations', () {
    expect(pushRoutes['guide'], '/guide');
    expect(pushRoutes['models'], '/models');
    expect(pushRoutes['/meeting/private'], isNull);
    expect(pushRoutes['https://example.test'], isNull);
  });
}
