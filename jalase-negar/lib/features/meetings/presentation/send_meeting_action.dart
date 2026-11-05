import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/widgets/ss_toast.dart';
import '../application/meeting_providers.dart';

/// Queues a meeting's text and audio for SedaSanj now. Shared by the list tile
/// and the detail header so both behave the same.
Future<void> sendMeetingToSedasanj(
  BuildContext context,
  WidgetRef ref,
  String meetingId,
) async {
  await ref.read(meetingActionsProvider(meetingId)).sendText();
  if (!context.mounted) return;
  SsToastHost.show(context, 'ارسال به صداسنج شروع شد');
}
