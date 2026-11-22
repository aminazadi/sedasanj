import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:jalase_negar/app/shell_screen.dart';
import 'package:jalase_negar/app/theme.dart';
import 'package:jalase_negar/features/meetings/application/meeting_providers.dart';
import 'package:jalase_negar/features/people/application/people_providers.dart';
import 'package:jalase_negar/features/upload/upload_controller.dart';

void main() {
  Future<void> pump(WidgetTester tester, GoRouter router) {
    return tester.pumpWidget(
      ProviderScope(
        overrides: [
          uploadQueueProvider.overrideWith(_IdleUpload.new),
          speakerSyncProvider.overrideWith(_IdleSpeakerSync.new),
          speakerAnalysisProvider.overrideWith(_IdleAnalysis.new),
        ],
        child: MaterialApp.router(
          routerConfig: router,
          theme: buildAppTheme(),
          locale: const Locale('fa'),
          supportedLocales: const [Locale('fa')],
          localizationsDelegates: GlobalMaterialLocalizations.delegates,
        ),
      ),
    );
  }

  testWidgets('a short scroll down hides the header and lets content use the '
      'freed space; scrolling back up restores it, and the record button '
      'keeps working throughout', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final router = GoRouter(
      routes: [
        ShellRoute(
          builder: (context, state, child) => ShellScreen(child: child),
          routes: [
            GoRoute(
              path: '/',
              builder: (context, state) => ListView.builder(
                itemCount: 60,
                itemBuilder: (context, i) =>
                    SizedBox(height: 48, child: Text('Row $i')),
              ),
            ),
          ],
        ),
        GoRoute(
          path: '/record',
          builder: (context, state) => const Text('Recording page'),
        ),
      ],
    );
    addTearDown(router.dispose);
    await pump(tester, router);
    await tester.pump();

    // At rest, the drawer button sits at the header's usual spot.
    final restY = tester.getCenter(find.byType(DrawerButton)).dy;

    // A short, deliberate drag downward (content moving up) — well under
    // the old 120px full-track distance — should already commit to fully
    // hiding the bars, eased in smoothly rather than jumping.
    await tester.drag(find.byType(ListView), const Offset(0, -20));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 130));
    // Mid-flight: the header is partway through collapsing, not an
    // instant jump — the drawer button has moved but the animation has
    // not yet finished settling.
    final midY = tester.getCenter(find.byType(DrawerButton)).dy;
    expect(midY, isNot(equals(restY)));
    await tester.pump(const Duration(milliseconds: 200));

    // Fully hidden: the header's own controls are no longer hit-testable
    // (clipped away), confirming the collapse actually completed rather
    // than stalling partway.
    expect(
      tester.getRect(find.byType(DrawerButton)).bottom,
      lessThanOrEqualTo(0.5),
    );

    // The record button keeps working while the bars are hidden.
    await tester.tap(find.bySemanticsLabel('ضبط جلسه'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.text('Recording page'), findsOneWidget);
    router.pop();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));

    // A short scroll back up restores the header to its resting spot.
    await tester.drag(find.byType(ListView), const Offset(0, 20));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(tester.getCenter(find.byType(DrawerButton)).dy, restY);

    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('a normal flick-and-release scroll — most of how real scrolling '
      'happens, not a slow sustained drag — still hides and shows the '
      'header (regression: a version that ignored every update without '
      "dragDetails barely reacted to scrolling at all, since most of a "
      "fling's distance plays out as driver-less momentum after the finger "
      'lifts)', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final router = GoRouter(
      routes: [
        ShellRoute(
          builder: (context, state, child) => ShellScreen(child: child),
          routes: [
            GoRoute(
              path: '/',
              builder: (context, state) => ListView.builder(
                itemCount: 60,
                itemBuilder: (context, i) =>
                    SizedBox(height: 48, child: Text('Row $i')),
              ),
            ),
          ],
        ),
      ],
    );
    addTearDown(router.dispose);
    await pump(tester, router);
    await tester.pump();

    final restY = tester.getCenter(find.byType(DrawerButton)).dy;

    await tester.fling(find.byType(ListView), const Offset(0, -300), 1000);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(
      tester.getRect(find.byType(DrawerButton)).bottom,
      lessThanOrEqualTo(0.5),
    );

    await tester.fling(find.byType(ListView), const Offset(0, 300), 1000);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(tester.getCenter(find.byType(DrawerButton)).dy, restY);

    await tester.pumpWidget(const SizedBox());
  });

  testWidgets(
    'on a page too short to really scroll, dragging still hides and then '
    'shows the header again (regression: excluding all out-of-range '
    'scrolling once left such a page stuck hidden for good)',
    (tester) async {
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final router = GoRouter(
        routes: [
          ShellRoute(
            builder: (context, state, child) => ShellScreen(child: child),
            routes: [
              GoRoute(
                path: '/',
                // Three short rows: nowhere near enough to fill the
                // viewport, so every drag is immediately "out of range"
                // overscroll rather than real, in-range scrolling. Bouncing
                // physics matches the app's real iOS behaviour (the test
                // environment otherwise defaults to Android's clamping
                // physics, which never moves `pixels` on a drag like this).
                builder: (context, state) => ListView.builder(
                  physics: const AlwaysScrollableScrollPhysics(
                    parent: BouncingScrollPhysics(),
                  ),
                  itemCount: 3,
                  itemBuilder: (context, i) =>
                      SizedBox(height: 40, child: Text('Row $i')),
                ),
              ),
            ],
          ),
        ],
      );
      addTearDown(router.dispose);
      await pump(tester, router);
      await tester.pump();

      final restY = tester.getCenter(find.byType(DrawerButton)).dy;

      // A bigger drag than the overflowing-list test's: bouncing physics
      // damps an overscroll, so clearing the commit threshold here takes
      // more raw finger movement than it would on a list with real range.
      await tester.drag(find.byType(ListView), const Offset(0, -80));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      expect(
        tester.getRect(find.byType(DrawerButton)).bottom,
        lessThanOrEqualTo(0.5),
      );

      await tester.drag(find.byType(ListView), const Offset(0, 80));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      expect(tester.getCenter(find.byType(DrawerButton)).dy, restY);

      await tester.pumpWidget(const SizedBox());
    },
  );
}

class _IdleAnalysis extends SpeakerAnalysisController {
  @override
  SpeakerAnalysisState build() => const SpeakerAnalysisState();
}

class _IdleUpload extends UploadController {
  @override
  UploadState build() => const UploadState();
}

class _IdleSpeakerSync extends SpeakerSyncController {
  @override
  SpeakerSyncState build() => const SpeakerSyncState();
}
