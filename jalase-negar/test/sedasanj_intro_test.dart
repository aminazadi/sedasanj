import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/features/sedasanj_intro/sedasanj_intro.dart';

Map<String, Object?> _json({
  String video = '',
  String button = 'https://sedasanj.ir',
}) => {
  'enabled': true,
  'delay_days': 3,
  'title': 'عنوان',
  'body': 'متن',
  'video_url': video,
  'button_label': 'آشنایی',
  'button_url': button,
};

void main() {
  group('SedasanjIntroContent.fromJson', () {
    test('reads content with and without video', () {
      final a = SedasanjIntroContent.fromJson(_json());
      expect(a.videoUrl, isNull);
      expect(a.buttonUrl.toString(), 'https://sedasanj.ir');
      final b = SedasanjIntroContent.fromJson(
        _json(video: 'https://x.ir/a.mp4'),
      );
      expect(b.videoUrl?.host, 'x.ir');
    });

    test('rejects non-https links and malformed bodies', () {
      expect(
        () => SedasanjIntroContent.fromJson(_json(button: 'http://x.ir')),
        throwsFormatException,
      );
      expect(
        () =>
            SedasanjIntroContent.fromJson(_json(video: 'javascript:alert(1)')),
        throwsFormatException,
      );
      expect(() => SedasanjIntroContent.fromJson('x'), throwsFormatException);
    });
  });

  group('shouldShowSedasanjIntro', () {
    final now = DateTime(2026, 11, 10);
    bool call({
      DateTime? firstUse,
      DateTime? lastShown,
      bool dismissed = false,
      bool connected = false,
      int delay = 3,
      bool enabled = true,
    }) => shouldShowSedasanjIntro(
      now: now,
      firstUse: firstUse ?? DateTime(2026, 11, 1),
      lastShown: lastShown,
      dismissedForever: dismissed,
      connected: connected,
      delayDays: delay,
      enabled: enabled,
    );

    test(
      'shows after the delay when not connected',
      () => expect(call(), isTrue),
    );
    test(
      'waits for the delay',
      () => expect(call(firstUse: DateTime(2026, 11, 9)), isFalse),
    );
    test('never when connected, dismissed or disabled', () {
      expect(call(connected: true), isFalse);
      expect(call(dismissed: true), isFalse);
      expect(call(enabled: false), isFalse);
    });
    test('repeats only after a week', () {
      expect(call(lastShown: DateTime(2026, 11, 5)), isFalse);
      expect(call(lastShown: DateTime(2026, 11, 2)), isTrue);
    });
  });
}
