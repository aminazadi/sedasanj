import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/app/theme.dart';
import 'package:jalase_negar/features/onboarding/intro/intro_art.dart';
import 'package:jalase_negar/features/onboarding/intro/intro_screen.dart';

void main() {
  testWidgets('every intro scene paints at several moments of its loop', (
    tester,
  ) async {
    final controller = AnimationController(
      vsync: const TestVSync(),
      duration: kIntroArtLoop,
    );
    addTearDown(controller.dispose);
    for (final scene in IntroScene.values) {
      for (final v in [0.0, 0.1, 0.3, 0.6, 0.8, 0.99]) {
        controller.value = v;
        await tester.pumpWidget(
          MaterialApp(
            theme: buildAppTheme(),
            home: Center(
              child: IntroArt(scene: scene, animation: controller),
            ),
          ),
        );
        expect(tester.takeException(), isNull, reason: '$scene @ $v');
      }
    }
  });

  testWidgets('slides page forward and show the final action', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: const Directionality(
          textDirection: TextDirection.rtl,
          child: IntroScreen(replay: true),
        ),
      ),
    );
    expect(find.text(kIntroSlides.first.title), findsOneWidget);
    expect(find.text('بعدی'), findsNothing);
    expect(find.text('شروع کنیم'), findsNothing);
    for (var i = 1; i < kIntroSlides.length; i++) {
      await tester.fling(find.byType(PageView), const Offset(300, 0), 3000);
      await tester.pump(const Duration(milliseconds: 600));
      await tester.pump(const Duration(milliseconds: 600));
    }
    expect(
      kIntroSlides.where((s) => s.scene == IntroScene.mic).single.body,
      contains('Holyland'),
    );
    expect(find.text(kIntroSlides.last.title), findsOneWidget);
    expect(find.text('شروع کنیم'), findsOneWidget);
  });
}
