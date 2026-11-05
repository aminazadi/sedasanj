import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:jalase_negar/app/shell_screen.dart';
import 'package:jalase_negar/app/theme.dart';
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
                  builder: (context, state) => Center(child: Text('Page $path')),
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
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            uploadQueueProvider.overrideWith(_IdleUpload.new),
            speakerSyncProvider.overrideWith(_IdleSpeakerSync.new),
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
      for (final entry in {
        'افراد': '/people',
        'راهنما': '/guide',
        'تنظیمات': '/settings',
        'جلسات': '/',
      }.entries) {
        expect(find.text(entry.key), findsOneWidget);
        await tester.tap(find.text(entry.key));
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 300));
        expect(router.routeInformationProvider.value.uri.path, entry.value);
        expect(find.text('Page ${entry.value}'), findsOneWidget);
        expect(tester.takeException(), isNull);
      }
      await tester.tap(find.text('ضبط جلسه'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text('Recording page'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    });
  }
}

class _IdleUpload extends UploadController {
  @override
  UploadState build() => const UploadState();
}

class _IdleSpeakerSync extends SpeakerSyncController {
  @override
  SpeakerSyncState build() => const SpeakerSyncState();
}
