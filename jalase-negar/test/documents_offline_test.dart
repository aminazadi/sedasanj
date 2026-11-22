import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/app/widgets/markdown_view.dart';
import 'package:jalase_negar/core/db/app_database.dart';
import 'package:jalase_negar/core/platform/api_client.dart';
import 'package:jalase_negar/core/providers.dart';
import 'package:jalase_negar/features/settings/application/connection_controller.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

class _Client extends ApiClient {
  _Client() : super(serverUrl: 'https://example.test');
  bool offline = false;

  @override
  Future<DocumentDetail> getDocument(String documentId) async {
    if (offline) {
      throw const ApiException(message: 'ارتباط با سرور برقرار نشد');
    }
    return const DocumentDetail(
      info: DocumentInfo(
        id: 'd1',
        outputType: 'counseling',
        status: 'done',
        progressPct: 100,
        selectedVersion: 2,
      ),
      markdown: '# عنوان\n\n- یک',
    );
  }

  @override
  Future<List<DocumentInfo>> listDocuments(String remoteMeetingId) async {
    if (offline) {
      throw const ApiException(message: 'ارتباط با سرور برقرار نشد');
    }
    return const [
      DocumentInfo(
        id: 'd1',
        outputType: 'counseling',
        status: 'done',
        progressPct: 100,
        selectedVersion: 2,
      ),
    ];
  }
}

void main() {
  test('inline bold and code are split out and the rest stays text', () {
    final span = inlineSpans('الف **ب** پ `ج`', const TextStyle());
    final texts = [for (final c in span.children!) (c as TextSpan).text];
    expect(texts, ['الف ', 'ب', ' پ ', 'ج']);
    expect((span.children![1] as TextSpan).style!.fontWeight, FontWeight.w700);
  });

  testWidgets('headings, bullets and numbers render without Markdown marks', (
    tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: MarkdownView(
            markdown: '# تیتر\n\nمتن **مهم**\n\n- اول\n- دوم\n\n1. الف\n2. ب',
          ),
        ),
      ),
    );
    final all = tester
        .widgetList<Text>(find.byType(Text))
        .map((t) => t.textSpan?.toPlainText() ?? t.data ?? '')
        .join('|');
    expect(all, contains('تیتر'));
    expect(all, contains('متن مهم'));
    expect(all, isNot(contains('#')));
    expect(all, isNot(contains('**')));
    expect(all, contains('•'));
    expect(all, contains('2.'));
  });

  test(
    'a document opened once is shown again when the network is gone',
    () async {
      sqfliteFfiInit();
      final dir = Directory.systemTemp.createTempSync('doccache');
      addTearDown(() => dir.deleteSync(recursive: true));
      final db = await AppDatabase.open(
        '${dir.path}/a.db',
        factory: databaseFactoryFfi,
      );
      addTearDown(db.db.close);
      final client = _Client();
      final container = ProviderContainer(
        overrides: [
          appDatabaseProvider.overrideWith((ref) async => db),
          personalClientProvider.overrideWith((ref) async => client),
        ],
      );
      addTearDown(container.dispose);

      final online = await container.read(documentDetailProvider('d1').future);
      expect(online.markdown, '# عنوان\n\n- یک');
      final docs = await container.read(meetingDocumentsProvider('r1').future);
      expect(docs.single.id, 'd1');

      client.offline = true;
      container.invalidate(documentDetailProvider('d1'));
      container.invalidate(meetingDocumentsProvider('r1'));
      final cached = await container.read(documentDetailProvider('d1').future);
      expect(cached.markdown, '# عنوان\n\n- یک');
      expect(cached.info.selectedVersion, 2);
      final cachedList = await container.read(
        meetingDocumentsProvider('r1').future,
      );
      expect(cachedList.single.outputType, 'counseling');
      // A document never opened has no copy, so the error is still shown.
      await expectLater(
        container.read(documentDetailProvider('other').future),
        throwsA(isA<ApiException>()),
      );
    },
  );
}
