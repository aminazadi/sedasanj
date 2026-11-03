import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/utils/format.dart';

void main() {
  final now = DateTime(2026, 11, 4, 0, 30);

  test('groups today, yesterday and the last week relatively', () {
    expect(meetingGroupLabel(DateTime(2026, 11, 4, 23, 59), now), 'امروز');
    expect(meetingGroupLabel(DateTime(2026, 11, 3, 23, 59), now), 'دیروز');
    expect(meetingGroupLabel(DateTime(2026, 10, 30, 8), now), 'این هفته');
  });

  test('older meetings group by Jalali month with Persian digits', () {
    expect(meetingGroupLabel(DateTime(2026, 10, 1, 8), now), 'مهر ۱۴۰۵');
  });
}
