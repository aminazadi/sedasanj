import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/db/app_database.dart';
import 'package:jalase_negar/core/platform/api_client.dart';
import 'package:jalase_negar/core/platform/connection_store.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';
import 'package:jalase_negar/features/meetings/data/meeting_repository.dart';
import 'package:jalase_negar/features/upload/upload_queue.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'upload_queue_test.dart' show FakeApi, FakeStore;

class _Adapter implements HttpClientAdapter {
  _Adapter(this.handler);
  final ResponseBody Function(RequestOptions) handler;
  @override
  void close({bool force = false}) {}
  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<List<int>>? requestStream,
    Future<void>? cancelFuture,
  ) async => handler(options);
}

Meeting _meeting(String id, String workspace) => Meeting(
  id: id,
  title: 'جلسه',
  createdAt: DateTime(2026),
  duration: const Duration(seconds: 3),
  audioPath: '/a.wav',
  sampleRate: 16000,
  channels: 1,
  status: MeetingStatus.transcribed,
  asrIdentity: 'live-model',
  workspace: workspace,
);

void main() {
  test('each queue sends only the meetings of its own workspace', () async {
    final meetings = [_meeting('m1', 'primary'), _meeting('m2', 'org')];
    final store = FakeStore(
      meetings,
      {
        'm1': const [Segment(channel: 0, startMs: 0, endMs: 1000, text: 'الف')],
        'm2': const [Segment(channel: 0, startMs: 0, endMs: 1000, text: 'ب')],
      },
      {'m1': [], 'm2': []},
    );
    final orgApi = FakeApi();
    await UploadQueue(
      store: store,
      api: orgApi,
      workspace: kWorkspaceOrg,
      random: Random(1),
    ).processOnce();
    expect(orgApi.sentSegments!.map((s) => s.text), ['ب']);
    expect(
      store.meetings.firstWhere((m) => m.id == 'm1').status,
      MeetingStatus.transcribed,
      reason: 'the personal meeting must wait for the personal key',
    );
    expect(
      store.meetings.firstWhere((m) => m.id == 'm2').status,
      MeetingStatus.processing,
    );
  });

  test('linking posts the pairing code and keeps the key once', () async {
    final seen = <RequestOptions>[];
    final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
    dio.httpClientAdapter = _Adapter((o) {
      seen.add(o);
      if (o.method == 'DELETE') {
        return ResponseBody.fromString('', 204);
      }
      if (o.path.endsWith('/import')) {
        return ResponseBody.fromString(
          jsonEncode({
            'imported': [],
            'already_imported': ['r1'],
          }),
          200,
          headers: {
            Headers.contentTypeHeader: ['application/json'],
          },
        );
      }
      return ResponseBody.fromString(
        jsonEncode({
          'link_id': 'l1',
          'token': 'jn_org_token',
          'token_prefix': 'jn_org',
          'organization': 'سازمان نمونه',
          'user': 'علی',
        }),
        201,
        headers: {
          Headers.contentTypeHeader: ['application/json'],
        },
      );
    });
    final api = ApiClient(serverUrl: 'https://example.test', dio: dio);
    final result = await api.linkOrganization(
      pairingCode: 'ABCD1234',
      deviceLabel: 'Jalase-Negar',
      appVersion: '2.0.0',
      platform: 'android',
    );
    expect(result.linkId, 'l1');
    expect(result.organization, 'سازمان نمونه');
    expect(seen.single.path, '/v1/jalase-negar/link');
    expect(seen.single.data['pairing_code'], 'ABCD1234');
    final copied = await api.importToOrganization('l1', ['r1']);
    expect(seen.last.path, '/v1/jalase-negar/link/l1/import');
    expect(seen.last.data, {
      'meeting_ids': ['r1'],
    });
    expect(copied.imported, 0);
    expect(copied.existing, 1);
    await api.unlinkOrganization('l1');
    expect(seen.last.path, '/v1/jalase-negar/link/l1');
  });

  test(
    'the meetings table has a workspace column, defaulting to primary',
    () async {
      sqfliteFfiInit();
      final dir = Directory.systemTemp.createTempSync('v11');
      addTearDown(() => dir.deleteSync(recursive: true));
      final path = '${dir.path}/old.db';
      final fresh = await AppDatabase.open(path, factory: databaseFactoryFfi);
      await fresh.db.insert('meetings', {
        'id': 'm1',
        'title': 'جلسه',
        'created_at': 1,
        'duration_ms': 5000,
        'audio_path': '/a.wav',
        'sample_rate': 16000,
        'channels': 1,
        'status': 'recorded',
      });
      addTearDown(fresh.db.close);
      final repo = MeetingRepository(fresh);
      expect((await repo.meeting('m1'))!.workspace, kWorkspacePrimary);
      // Unlinking moves unsent meetings back to the own account.
      await fresh.db.update('meetings', {'workspace': 'org'});
      await repo.moveUnsentToWorkspace(kWorkspacePrimary);
      expect((await repo.meeting('m1'))!.workspace, kWorkspacePrimary);
    },
  );

  test('the default workspace is org only while a link exists', () async {
    sqfliteFfiInit();
    final dir = Directory.systemTemp.createTempSync('ws');
    addTearDown(() => dir.deleteSync(recursive: true));
    final db = await AppDatabase.open(
      '${dir.path}/a.db',
      factory: databaseFactoryFfi,
    );
    addTearDown(db.db.close);
    await db.setSetting('workspace_default', 'org');
    final store = ConnectionStore(db);
    expect(await store.defaultWorkspace(), kWorkspacePrimary);
    await db.setSetting('org_link_id', 'l1');
    expect(await store.defaultWorkspace(), kWorkspaceOrg);
  });
}
