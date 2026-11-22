import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/platform/api_client.dart';
import '../../settings/application/connection_controller.dart';

/// The minutes the server built, shown as selectable text with copy and refresh.
class MinutesTab extends ConsumerWidget {
  const MinutesTab({super.key, required this.remoteMeetingId});

  final String remoteMeetingId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final minutes = ref.watch(meetingMinutesProvider(remoteMeetingId));
    return minutes.when(
      loading: () => const Center(child: SsProcessingMark(size: 30)),
      error: (error, _) => _MinutesMessage(
        message: error is ApiException
            ? error.message
            : 'دریافت صورت‌جلسه ناموفق بود؛ اینترنت را بررسی کنید و دوباره تلاش کنید.',
        onRefresh: () =>
            ref.invalidate(meetingMinutesProvider(remoteMeetingId)),
      ),
      data: (result) {
        final markdown = result.markdown;
        if (markdown == null || markdown.trim().isEmpty) {
          return _MinutesMessage(
            message:
                'صورت‌جلسه هنوز آماده نیست؛ پس از ارسال کامل جلسه کمی صبر کنید و دوباره بررسی کنید.',
            onRefresh: () =>
                ref.invalidate(meetingMinutesProvider(remoteMeetingId)),
          );
        }
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Row(
              children: [
                TextButton.icon(
                  icon: const Icon(Icons.copy),
                  label: const Text('کپی'),
                  onPressed: () async {
                    await Clipboard.setData(ClipboardData(text: markdown));
                    if (context.mounted) {
                      SsToastHost.show(context, 'صورت‌جلسه کپی شد.');
                    }
                  },
                ),
                TextButton.icon(
                  icon: const Icon(Icons.refresh),
                  label: const Text('به‌روزرسانی'),
                  onPressed: () =>
                      ref.invalidate(meetingMinutesProvider(remoteMeetingId)),
                ),
              ],
            ),
            SelectableText(markdown),
          ],
        );
      },
    );
  }
}

class _MinutesMessage extends StatelessWidget {
  const _MinutesMessage({required this.message, required this.onRefresh});

  final String message;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(message, textAlign: TextAlign.center),
          const SizedBox(height: 12),
          OutlinedButton(
            onPressed: onRefresh,
            child: const Text('بررسی دوباره'),
          ),
        ],
      ),
    ),
  );
}
