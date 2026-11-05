import 'package:shamsi_date/shamsi_date.dart';

const List<String> _persianDigits = [
  '۰',
  '۱',
  '۲',
  '۳',
  '۴',
  '۵',
  '۶',
  '۷',
  '۸',
  '۹',
];

String toPersianDigits(String input) {
  final buffer = StringBuffer();
  for (final code in input.codeUnits) {
    if (code >= 0x30 && code <= 0x39) {
      buffer.write(_persianDigits[code - 0x30]);
    } else {
      buffer.writeCharCode(code);
    }
  }
  return buffer.toString();
}

String formatDuration(Duration d) {
  final h = d.inHours;
  final m = d.inMinutes % 60;
  final s = d.inSeconds % 60;
  String two(int v) => v.toString().padLeft(2, '0');
  final text = h > 0 ? '$h:${two(m)}:${two(s)}' : '${two(m)}:${two(s)}';
  return toPersianDigits(text);
}

String formatBytes(int bytes) {
  const gb = 1024 * 1024 * 1024;
  const mb = 1024 * 1024;
  final String text;
  if (bytes >= gb) {
    text = '${(bytes / gb).toStringAsFixed(1)} گیگابایت';
  } else if (bytes >= mb) {
    text = '${(bytes / mb).toStringAsFixed(0)} مگابایت';
  } else {
    text = '${(bytes / 1024).toStringAsFixed(0)} کیلوبایت';
  }
  return toPersianDigits(text);
}

String formatJalaliDate(DateTime dateTime) {
  final j = Jalali.fromDateTime(dateTime);
  final f = j.formatter;
  final time =
      '${dateTime.hour.toString().padLeft(2, '0')}:'
      '${dateTime.minute.toString().padLeft(2, '0')}';
  return toPersianDigits('${f.d} ${f.mN} ${f.yyyy} - $time');
}

String formatJalaliDay(DateTime dateTime) {
  final f = Jalali.fromDateTime(dateTime).formatter;
  return toPersianDigits('${f.d} ${f.mN} ${f.yyyy}');
}

String formatClock(DateTime dateTime) => toPersianDigits(
  '${dateTime.hour.toString().padLeft(2, '0')}:'
  '${dateTime.minute.toString().padLeft(2, '0')}',
);

/// Meetings recorded by older builds were titled with a Gregorian date
/// ("Meeting 2026/11/1"); show those as Jalali with Persian digits.
String displayMeetingTitle(String title) {
  final m = RegExp(r'^جلسه (\d{4})/(\d{1,2})/(\d{1,2})$').firstMatch(title);
  if (m != null) {
    final day = DateTime(int.parse(m[1]!), int.parse(m[2]!), int.parse(m[3]!));
    return 'جلسه ${formatJalaliDay(day)}';
  }
  return toPersianDigits(title);
}

/// Section label for the meetings list: relative for the last week, then the
/// Jalali month.
String meetingGroupLabel(DateTime dateTime, DateTime now) {
  final day = DateTime.utc(dateTime.year, dateTime.month, dateTime.day);
  final today = DateTime.utc(now.year, now.month, now.day);
  final diff = today.difference(day).inDays;
  if (diff <= 0) return 'امروز';
  if (diff == 1) return 'دیروز';
  if (diff < 7) return 'این هفته';
  final f = Jalali.fromDateTime(dateTime).formatter;
  return toPersianDigits('${f.mN} ${f.yyyy}');
}
