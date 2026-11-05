import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:jalase_negar/app/shell_screen.dart';
import 'package:jalase_negar/app/theme.dart';
import 'package:jalase_negar/app/widgets/brand_logo.dart';
import 'package:jalase_negar/app/widgets/ss_widgets.dart';
import 'package:jalase_negar/features/meetings/application/meeting_providers.dart';
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
          for (final path in ['/models', '/people/new'])
            GoRoute(
              path: path,
              builder: (context, state) => Text('Action $path'),
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
      expect(find.byType(SsAppBarAction), findsOneWidget);
      expect(tester.getRect(find.byType(SsBrandLogo)).right, width - 16);
      expect(
        tester
            .getRect(find.byWidgetPredicate((widget) => widget is TextButton))
            .left,
        16,
      );
      await tester.tap(find.text('دانلود مدل‌ها'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.text('Action /models'), findsOneWidget);
      router.pop();
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
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
            width - 16,
          );
        }
        if (entry.value == '/people') {
          expect(find.byType(SsAppBarAction), findsOneWidget);
          expect(
            tester
                .getRect(
                  find.byWidgetPredicate((widget) => widget is TextButton),
                )
                .left,
            16,
          );
          await tester.tap(find.text('افزودن فرد'));
          await tester.pump();
          await tester.pump(const Duration(milliseconds: 500));
          expect(find.text('Action /people/new'), findsOneWidget);
          router.pop();
          await tester.pump();
          await tester.pump(const Duration(milliseconds: 500));
        }
      }
      await tester.tap(find.text('ضبط جلسه'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.text('Recording page'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    });
  }
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
