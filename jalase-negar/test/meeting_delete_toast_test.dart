import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/app/theme.dart';
import 'package:jalase_negar/app/widgets/ss_toast.dart';
import 'package:jalase_negar/app/widgets/ss_widgets.dart';
import 'package:jalase_negar/features/meetings/application/meeting_providers.dart';
import 'package:jalase_negar/features/meetings/data/meeting.dart';
import 'package:jalase_negar/features/meetings/presentation/meetings_screen.dart';
import 'package:jalase_negar/features/upload/upload_controller.dart';

void main() {
  for (final undo in [true, false]) {
    testWidgets('top delete toast ${undo ? 'restores' : 'expires'}', (
      tester,
    ) async {
      final meeting = Meeting(
        id: 'meeting',
        title: 'جلسهٔ تیم',
        createdAt: DateTime(2026, 11, 4),
        duration: const Duration(seconds: 30),
        audioPath: '/meeting.wav',
        sampleRate: 16000,
        channels: 1,
        status: MeetingStatus.complete,
      );
      var deleted = false;
      tester.view.physicalSize = const Size(360, 640);
      tester.view.devicePixelRatio = 1;
      tester.view.padding = const FakeViewPadding(top: 24);
      addTearDown(tester.view.reset);
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            meetingsProvider.overrideWith(
              (ref) async => deleted ? [] : [meeting],
            ),
            meetingPreviewProvider(meeting.id).overrideWith((ref) async => ''),
            meetingActionsProvider(meeting.id).overrideWith(
              (ref) => _MeetingActions(ref, meeting.id, () => deleted = true),
            ),
            uploadQueueProvider.overrideWith(_IdleUploadController.new),
          ],
          child: MaterialApp(
            theme: buildAppTheme(),
            builder: (context, child) => Directionality(
              textDirection: TextDirection.rtl,
              child: SsToastHost(child: child!),
            ),
            home: Scaffold(
              appBar: SsAppBar(title: const Text('جلسات')),
              body: const MeetingsScreen(),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      final card = find.byKey(ValueKey('dismiss-${meeting.id}'));
      final message = find.text('جلسه حذف شد');
      final action = find.text('بازگردانی');
      await tester.fling(card, const Offset(330, 0), 1200);
      await tester.pumpAndSettle();

      expect(card, findsNothing);
      expect(deleted, isFalse);
      expect(tester.getTopLeft(message).dy, inInclusiveRange(80, 160));
      expect(
        tester.getCenter(action).dx,
        lessThan(tester.getCenter(message).dx),
      );

      if (undo) await tester.tap(action);
      await tester.pump(const Duration(seconds: 5));
      await tester.pumpAndSettle();
      expect(message, findsNothing);
      expect(deleted, !undo);
      expect(card, undo ? findsOneWidget : findsNothing);
    });
  }
}

class _MeetingActions extends MeetingActions {
  _MeetingActions(super.ref, super.meetingId, this.onDelete);

  final VoidCallback onDelete;

  @override
  Future<void> deleteMeeting() async {
    onDelete();
    ref.invalidate(meetingsProvider);
    await ref.read(meetingsProvider.future);
  }
}

class _IdleUploadController extends UploadController {
  @override
  UploadState build() => const UploadState();
}
