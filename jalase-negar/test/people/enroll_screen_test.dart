import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/features/people/application/people_providers.dart';
import 'package:jalase_negar/features/people/data/enrollment_session.dart';
import 'package:jalase_negar/features/people/data/person.dart';
import 'package:jalase_negar/features/people/presentation/enroll_screen.dart';

import 'enrollment_session_test.dart' show FakeEmbedder, FakeRecorder;
import 'people_test_support.dart';

void main() {
  testWidgets('keeps recording while the people list refreshes', (
    tester,
  ) async {
    final setup = await tester.runAsync(() async {
      final (db, dir) = await openTestDb();
      final repo = repoFor(db);
      final person = await repo.create(name: 'Test');
      return (db, dir, repo, person);
    });
    final (db, dir, repo, person) = setup!;
    final refresh = Completer<List<Person>>();
    var calls = 0;
    final recorder = FakeRecorder();
    final container = ProviderContainer(
      overrides: [
        peopleProvider.overrideWith((ref) {
          calls++;
          return calls == 1 ? Future.value([person]) : refresh.future;
        }),
        peopleRepositoryProvider.overrideWith((ref) async => repo),
        speakerPromptsProvider.overrideWith(
          (ref) async => const SpeakerPrompts(
            version: '1',
            prompts: [
              SpeakerPrompt(id: '1', text: 'Read', required: true, near: true),
            ],
          ),
        ),
        voiceEmbeddingServiceProvider.overrideWith(
          (ref) async => FakeEmbedder(),
        ),
        enrollmentRecorderFactoryProvider.overrideWithValue(() => recorder),
      ],
    );
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: MaterialApp(home: EnrollScreen(personId: person.clientId)),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('شروع خواندن'));
    await tester.pump();
    expect(find.text('پایان خواندن'), findsOneWidget);

    container.invalidate(peopleProvider);
    await tester.pump();
    expect(find.text('پایان خواندن'), findsOneWidget);
    expect(recorder.controller.isClosed, isFalse);
    refresh.complete([person]);
    await tester.pumpAndSettle();
    expect(find.text('پایان خواندن'), findsOneWidget);
    expect(recorder.controller.isClosed, isFalse);

    await tester.pumpWidget(const SizedBox());
    container.dispose();
    await tester.runAsync(() async {
      await db.db.close();
      dir.deleteSync(recursive: true);
    });
  });
}
