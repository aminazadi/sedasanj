import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/platform/api_client.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';
import 'package:jalase_negar/features/meetings/presentation/meeting_type_picker_sheet.dart';
import 'package:jalase_negar/features/recording/application/pending_meeting_type.dart';
import 'package:jalase_negar/features/settings/application/connection_controller.dart';

const _types = [
  OutputTypeInfo(
    code: 'minutes',
    title: 'صورت جلسه عمومی',
    description: '',
    automatic: true,
    fields: [],
  ),
  OutputTypeInfo(
    code: 'counseling',
    title: 'گزارش مشاوره',
    description: '',
    automatic: false,
    fields: [
      OutputField(key: 'client', label: 'نام مشتری', type: 'text', required: true),
    ],
  ),
];

Future<PendingMeetingType?> _open(
  WidgetTester tester, {
  PendingMeetingType initial = (code: kBuiltinOutputType, values: const {}),
}) async {
  PendingMeetingType? result;
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        meetingTypesProvider.overrideWith((ref) async => _types),
      ],
      child: MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => TextButton(
              onPressed: () async {
                result = await showMeetingTypePicker(context, initial: initial);
              },
              child: const Text('open'),
            ),
          ),
        ),
      ),
    ),
  );
  await tester.tap(find.text('open'));
  await tester.pumpAndSettle();
  return result;
}

void main() {
  testWidgets('the builtin category is shown first and preselected', (
    tester,
  ) async {
    await _open(tester);
    expect(find.text('صورت جلسه عمومی'), findsOneWidget);
    expect(find.text('گزارش مشاوره'), findsOneWidget);

    // Confirming without touching anything keeps the builtin default.
    await tester.tap(find.text('تأیید'));
    await tester.pumpAndSettle();
  });

  testWidgets('picking another category asks its required fields', (
    tester,
  ) async {
    PendingMeetingType? result;
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          meetingTypesProvider.overrideWith((ref) async => _types),
        ],
        child: MaterialApp(
          home: Scaffold(
            body: Builder(
              builder: (context) => TextButton(
                onPressed: () async {
                  result = await showMeetingTypePicker(
                    context,
                    initial: (code: kBuiltinOutputType, values: const {}),
                  );
                },
                child: const Text('open'),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('گزارش مشاوره'));
    await tester.pump();
    expect(find.text('نام مشتری *'), findsOneWidget);

    // The required field is empty: the sheet explains instead of confirming.
    await tester.tap(find.text('تأیید'));
    await tester.pump();
    expect(find.textContaining('فیلدهای اجباری'), findsOneWidget);
    expect(result, isNull);

    await tester.enterText(
      find.widgetWithText(TextFormField, 'نام مشتری *'),
      'شرکت نمونه',
    );
    await tester.tap(find.text('تأیید'));
    await tester.pumpAndSettle();

    expect(result, isNotNull);
    expect(result!.code, 'counseling');
    expect(result!.values, {'client': 'شرکت نمونه'});
  });
}
