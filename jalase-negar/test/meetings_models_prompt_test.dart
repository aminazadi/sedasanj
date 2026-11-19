import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:jalase_negar/app/theme.dart';
import 'package:jalase_negar/core/models/model_catalog.dart';
import 'package:jalase_negar/features/meetings/application/meeting_providers.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';
import 'package:jalase_negar/features/meetings/presentation/meetings_screen.dart';
import 'package:jalase_negar/features/models/application/models_controller.dart';
import 'package:jalase_negar/features/upload/upload_controller.dart';

Meeting _meeting() => Meeting(
  id: 'm',
  title: 'جلسهٔ تیم',
  createdAt: DateTime(2026, 11, 4),
  duration: const Duration(seconds: 30),
  audioPath: '/m.wav',
  sampleRate: 16000,
  channels: 1,
  status: MeetingStatus.complete,
);

class _NotReadyModels extends ModelsController {
  @override
  ModelsState build() => const ModelsState(loading: false);
}

class _ReadyModels extends ModelsController {
  @override
  ModelsState build() => ModelsState(
    loading: false,
    items: [
      for (final spec in ModelCatalog.all)
        ModelItemState(spec: spec, installed: true, selected: true),
    ],
  );
}

class _Idle extends UploadController {
  @override
  UploadState build() => const UploadState();
}

Future<void> _pump(
  WidgetTester tester,
  ModelsController Function() models,
) async {
  final meeting = _meeting();
  tester.view.physicalSize = const Size(390, 844);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final router = GoRouter(
    routes: [
      GoRoute(
        path: '/',
        builder: (context, state) => const Scaffold(body: MeetingsScreen()),
      ),
      GoRoute(
        path: '/models',
        builder: (context, state) => const Text('Models page'),
      ),
    ],
  );
  addTearDown(router.dispose);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        meetingsProvider.overrideWith((ref) async => [meeting]),
        meetingPreviewProvider(meeting.id).overrideWith((ref) async => ''),
        uploadQueueProvider.overrideWith(_Idle.new),
        modelsControllerProvider.overrideWith(models),
      ],
      child: MaterialApp.router(
        theme: buildAppTheme(),
        builder: (context, child) =>
            Directionality(textDirection: TextDirection.rtl, child: child!),
        routerConfig: router,
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
    'shows the download prompt above the list until models are ready, and '
    'it opens the models page',
    (tester) async {
      await _pump(tester, _NotReadyModels.new);
      expect(find.text('نصب مدل‌های رونویسی'), findsOneWidget);

      await tester.tap(find.text('نصب مدل‌های رونویسی'));
      await tester.pumpAndSettle();
      expect(find.text('Models page'), findsOneWidget);
    },
  );

  testWidgets('hides the prompt once models are installed and active', (
    tester,
  ) async {
    await _pump(tester, _ReadyModels.new);
    expect(find.text('نصب مدل‌های رونویسی'), findsNothing);
  });
}
