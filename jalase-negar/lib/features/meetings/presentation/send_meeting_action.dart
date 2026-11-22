import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/widgets/ss_toast.dart';
import '../../../core/providers.dart';
import '../../settings/application/connection_controller.dart';
import '../application/meeting_providers.dart';
import '../data/meeting.dart';

/// Queues a meeting's text and audio for SedaSanj now. Shared by the list tile
/// and the detail header so both behave the same. With a linked organization,
/// a meeting that was not sent yet first asks where it goes.
Future<void> sendMeetingToSedasanj(
  BuildContext context,
  WidgetRef ref,
  String meetingId,
) async {
  final link = await ref.read(orgLinkProvider.future);
  final meeting = (await ref.read(
    meetingsProvider.future,
  )).where((m) => m.id == meetingId).firstOrNull;
  if (link.link != null && meeting != null && meeting.remoteMeetingId == null) {
    if (!context.mounted) return;
    final chosen = await showDialog<String>(
      context: context,
      builder: (context) => SimpleDialog(
        title: const Text('این جلسه کجا ارسال شود؟'),
        children: [
          SimpleDialogOption(
            onPressed: () => Navigator.pop(context, kWorkspacePrimary),
            child: const Text('حساب شخصی'),
          ),
          SimpleDialogOption(
            onPressed: () => Navigator.pop(context, kWorkspaceOrg),
            child: Text('سازمان ${link.link!.organization}'),
          ),
        ],
      ),
    );
    if (chosen == null) return;
    final repo = await ref.read(meetingRepositoryProvider.future);
    await repo.setWorkspace(meetingId, chosen);
  }
  await ref.read(meetingActionsProvider(meetingId)).sendText();
  if (!context.mounted) return;
  SsToastHost.show(context, 'ارسال به صداسنج شروع شد');
}
