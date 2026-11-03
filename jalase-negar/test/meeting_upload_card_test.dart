import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/app/theme.dart';
import 'package:jalase_negar/app/widgets/ss_widgets.dart';
import 'package:jalase_negar/features/settings/presentation/meeting_upload_card.dart';

void main() {
  testWidgets('shows a square upload toggle in the RTL section header', (
    tester,
  ) async {
    var enabled = true;
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(
          body: Directionality(
            textDirection: TextDirection.rtl,
            child: StatefulBuilder(
              builder: (context, setState) => MeetingUploadCard(
                enabled: enabled,
                onChanged: (value) => setState(() => enabled = value),
              ),
            ),
          ),
        ),
      ),
    );

    final header = find.byType(SsSectionTitle);
    final title = find.text('ارسال جلسه');
    final toggle = find.descendant(of: header, matching: find.byType(InkWell));
    final track = find.descendant(of: toggle, matching: find.byType(Ink));
    final thumb = find.descendant(of: track, matching: find.byType(ColoredBox));
    final description = find.textContaining('صدا برای پخش و متن');
    expect(tester.getCenter(toggle).dx, lessThan(tester.getCenter(title).dx));
    expect(tester.getCenter(toggle).dy, tester.getCenter(title).dy);
    expect(
      tester.getTopLeft(description).dy,
      greaterThan(tester.getBottomLeft(header).dy),
    );
    expect(tester.widget<Text>(description).style?.fontSize, 12);
    expect(
      (tester.widget<Ink>(track).decoration as BoxDecoration).borderRadius,
      isNull,
    );
    expect(tester.getSize(thumb), const Size.square(14));
    expect(tester.getCenter(thumb).dx, lessThan(tester.getCenter(track).dx));

    await tester.tap(toggle);
    await tester.pump();
    expect(enabled, isFalse);
    expect(tester.getCenter(thumb).dx, greaterThan(tester.getCenter(track).dx));
    await tester.tap(toggle);
    await tester.pump();
    expect(enabled, isTrue);
  });
}
