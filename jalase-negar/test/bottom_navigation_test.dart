import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:jalase_negar/app/shell_screen.dart';
import 'package:jalase_negar/app/theme.dart';
import 'package:jalase_negar/app/widgets/app_menu_drawer.dart';
import 'package:jalase_negar/app/widgets/brand_logo.dart';
import 'package:jalase_negar/app/widgets/ss_widgets.dart';
import 'package:jalase_negar/features/meetings/application/meeting_providers.dart';
import 'package:jalase_negar/features/meetings/presentation/meetings_header.dart';
import 'package:jalase_negar/features/people/application/people_providers.dart';
import 'package:jalase_negar/features/upload/upload_controller.dart';

void main() {
  for (final width in [320.0, 390.0]) {
    testWidgets('all bottom tabs navigate on a $width pixel RTL screen', (
      tester,
    ) async {
      tester.view.physicalSize = Size(width, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final router = GoRouter(
        routes: [
          ShellRoute(
            builder: (context, state, child) => ShellScreen(child: child),
            routes: [
              for (final path in ['/', '/people', '/settings', '/guide'])
                GoRoute(
                  path: path,
                  builder: (context, state) =>
                      Center(child: Text('Page $path')),
                ),
            ],
          ),
          GoRoute(
            path: '/people/new',
            builder: (context, state) => const Text('Action /people/new'),
          ),
          GoRoute(
            path: '/record',
            builder: (context, state) => const Text('Recording page'),
          ),
        ],
      );
      addTearDown(router.dispose);
      await tester.pumpWidget(
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
      await tester.pump();
      // The hamburger keeps the app's standard (default) icon-button size,
      // pulled in from the edge by the same standard 16px gap the actions
      // side gets (SsAppBar's own leading wrapper, not titleSpacing — that
      // only trims the dead space between the button and the title, which
      // stays 0).
      final menuButtonRect = tester.getRect(find.byType(DrawerButton));
      expect(menuButtonRect.right, width - 16);
      // The meetings tab no longer carries the models shortcut; its header
      // now has a search and a filter icon button instead (no label, so no
      // SsAppBarAction).
      expect(find.byType(SsAppBarAction), findsNothing);
      expect(find.byType(MeetingsSearchButton), findsOneWidget);
      expect(find.byType(MeetingsFilterButton), findsOneWidget);
      expect(
        tester.getRect(find.byType(SsBrandLogo)).right,
        menuButtonRect.left,
      );
      // Opening search turns the whole header into the search field, then
      // closing it returns the header to normal.
      await tester.tap(find.byTooltip('جست‌وجو'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.byType(DrawerButton), findsNothing);
      expect(find.byType(SsBrandLogo), findsNothing);
      expect(find.byType(TextField), findsOneWidget);
      await tester.tap(find.byTooltip('بستن جست‌وجو'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.byType(TextField), findsNothing);
      expect(
        tester.getRect(find.byType(DrawerButton)).right,
        menuButtonRect.right,
      );
      for (final entry in {
        'افراد': '/people',
        'راهنما': '/guide',
        'تنظیمات': '/settings',
        'جلسات': '/',
      }.entries) {
        expect(find.text(entry.key), findsOneWidget);
        await tester.tap(find.text(entry.key));
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 500));
        expect(router.routeInformationProvider.value.uri.path, entry.value);
        expect(find.text('Page ${entry.value}'), findsOneWidget);
        expect(tester.takeException(), isNull);
        if (entry.value != '/') {
          final title = switch (entry.value) {
            '/people' => 'افراد و صدا',
            '/settings' => 'تنظیمات',
            _ => 'راهنما',
          };
          expect(
            tester
                .getRect(
                  find.descendant(
                    of: find.byType(SsAppBar),
                    matching: find.text(title),
                  ),
                )
                .right,
            menuButtonRect.left,
          );
        }
        if (entry.value == '/people') {
          expect(find.byType(SsAppBarAction), findsOneWidget);
          final actionRect = tester.getRect(
            find.byWidgetPredicate((widget) => widget is TextButton),
          );
          expect(actionRect.left, 16);
          // Same tap height as the standard (icon-only) AppBar button, not
          // a bespoke smaller one.
          expect(actionRect.height, menuButtonRect.height);
          // Plain icon+label, no outline border or filled background.
          final buttonStyle = tester
              .widget<TextButton>(
                find.descendant(
                  of: find.byType(SsAppBarAction),
                  matching: find.byWidgetPredicate((w) => w is TextButton),
                ),
              )
              .style!;
          expect(buttonStyle.side?.resolve(const {}), isNull);
          expect(buttonStyle.backgroundColor?.resolve(const {}), isNull);
          await tester.tap(find.text('افزودن فرد'));
          await tester.pump();
          await tester.pump(const Duration(milliseconds: 500));
          expect(find.text('Action /people/new'), findsOneWidget);
          router.pop();
          await tester.pump();
          await tester.pump(const Duration(milliseconds: 500));
        }
      }
      await tester.tap(find.bySemanticsLabel('ضبط جلسه'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.text('Recording page'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    });
  }

  testWidgets('the side menu opens from the hamburger button or an edge '
      'swipe, and offers to share the app', (tester) async {
    const width = 390.0;
    tester.view.physicalSize = const Size(width, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final router = GoRouter(
      routes: [
        ShellRoute(
          builder: (context, state, child) => ShellScreen(child: child),
          routes: [
            GoRoute(
              path: '/',
              builder: (context, state) => const Center(child: Text('Page /')),
            ),
          ],
        ),
      ],
    );
    addTearDown(router.dispose);
    await tester.pumpWidget(
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
    await tester.pump();

    // Not pumpAndSettle: the record button's pulse animation repeats
    // forever, so it never settles while ShellScreen is mounted.
    expect(find.byType(AppMenuDrawer), findsNothing);
    await tester.tap(find.byType(DrawerButton));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.byType(AppMenuDrawer), findsOneWidget);
    expect(find.text('اشتراک‌گذاری اپ'), findsOneWidget);
    await tester.tapAt(const Offset(20, 400));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.byType(AppMenuDrawer), findsNothing);

    // The drawer's start edge is the screen's right edge in this RTL app, so
    // dragging leftward from near the right edge should also open it.
    await tester.dragFrom(const Offset(width - 2, 400), const Offset(-250, 0));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.byType(AppMenuDrawer), findsOneWidget);
  });
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
