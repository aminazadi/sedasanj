import 'dart:io';

import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';

import '../../../core/utils/format.dart';
import '../data/meeting.dart';

/// Opens the system share sheet with the meeting's recording attached.
Future<void> shareMeetingAudio(BuildContext context, Meeting meeting) async {
  final messenger = ScaffoldMessenger.of(context);
  if (!await File(meeting.audioPath).exists()) {
    messenger.showSnackBar(
      const SnackBar(
        content: Text(
          'فایل صوتی این جلسه روی دستگاه پیدا نشد؛ ممکن است حذف شده باشد.',
        ),
      ),
    );
    return;
  }
  final title = displayMeetingTitle(meeting.title);
  await SharePlus.instance.share(
    ShareParams(
      files: [XFile(meeting.audioPath, mimeType: 'audio/wav')],
      title: title,
      subject: title,
    ),
  );
}
