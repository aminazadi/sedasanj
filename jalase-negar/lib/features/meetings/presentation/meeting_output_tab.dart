import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'package:go_router/go_router.dart';

import '../../../app/widgets/ss_widgets.dart';
import '../../../core/platform/api_client.dart';
import '../../documents/presentation/documents_tab.dart';
import '../../settings/application/connection_controller.dart';
import 'minutes_tab.dart';

/// «خروجی جلسه»: the server-built minutes and documents, shown only to a
/// signed-in account with usable plan hours; otherwise a locked state asking
/// to sign in or buy/upgrade a plan. If the plan check itself fails the output
/// is still shown, with the reason and a retry in a banner.
class MeetingOutputTab extends ConsumerWidget {
  const MeetingOutputTab({super.key, required this.remoteMeetingId});

  final String remoteMeetingId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final connection = ref
        .watch(connectionControllerProvider)
        .value
        ?.connection;
    final loggedIn = connection != null && connection.personal;
    if (!loggedIn) {
      return _OutputLockedState(
        image: 'assets/images/brand/login-required.svg',
        title: 'برای دیدن خروجی جلسه وارد حساب شوید',
        hint:
            'با ورود به حساب شخصی، صورت‌جلسه و اسناد این جلسه نمایش داده می‌شود.',
        action: FilledButton.icon(
          icon: const Icon(Icons.phone_android, size: 18),
          label: const Text('ورود با شماره موبایل'),
          onPressed: () => context.push('/login'),
        ),
      );
    }

    final usage = ref.watch(usageProvider);
    return usage.when(
      loading: () => const Center(child: SsProcessingMark(size: 30)),
      // A failed plan check must not hide the minutes and documents: the
      // server has them regardless, so show them with the real reason and a
      // retry above. A revoked device is the exception: nothing can load.
      error: (error, _) {
        void retry() {
          ref
            ..invalidate(personalClientProvider)
            ..invalidate(usageProvider);
        }

        if (error is ApiException && error.requiresReconnect) {
          return _OutputErrorState(
            message: _usageErrorMessage(error),
            onRefresh: retry,
          );
        }
        return _OutputTabs(
          remoteMeetingId: remoteMeetingId,
          banner: _PlanCheckBanner(
            message: _usageErrorMessage(error),
            onRetry: retry,
          ),
        );
      },
      data: (info) {
        final entitled = info.unlimited || !info.exhausted;
        if (!entitled) {
          return _OutputLockedState(
            image: 'assets/images/brand/plan-upgrade.svg',
            title: 'برای دریافت خروجی جلسه، به پلن فعال نیاز دارید',
            hint:
                'ساعت پلن این حساب تمام شده است؛ با تهیهٔ پلن یا شارژ ساعت، خروجی این جلسه در دسترس می‌شود.',
            action: FilledButton.icon(
              icon: const Icon(Icons.workspace_premium_outlined, size: 18),
              label: const Text('پلن و مصرف'),
              onPressed: () => context.push('/plans'),
            ),
          );
        }
        return _OutputTabs(remoteMeetingId: remoteMeetingId);
      },
    );
  }
}

/// The minutes and documents sub-tabs, with an optional banner above them.
class _OutputTabs extends StatelessWidget {
  const _OutputTabs({required this.remoteMeetingId, this.banner});

  final String remoteMeetingId;
  final Widget? banner;

  @override
  Widget build(BuildContext context) => DefaultTabController(
    length: 2,
    child: Column(
      children: [
        ?banner,
        const TabBar(
          tabs: [
            Tab(text: 'صورت‌جلسه'),
            Tab(text: 'اسناد'),
          ],
        ),
        Expanded(
          child: TabBarView(
            children: [
              MinutesTab(remoteMeetingId: remoteMeetingId),
              DocumentsTab(remoteMeetingId: remoteMeetingId),
            ],
          ),
        ),
      ],
    ),
  );
}

/// Shown above the tabs when the plan check failed but the output is still
/// listed, with the real reason and a retry.
class _PlanCheckBanner extends StatelessWidget {
  const _PlanCheckBanner({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      color: theme.colorScheme.errorContainer,
      child: Row(
        children: [
          Expanded(
            child: Text(
              message,
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onErrorContainer,
              ),
            ),
          ),
          TextButton(onPressed: onRetry, child: const Text('بررسی دوباره')),
        ],
      ),
    );
  }
}

/// Locked empty state for the output tab: an illustration of its own
/// (instead of [SsEmptyState]'s fixed one), a message and an action button.
class _OutputLockedState extends StatelessWidget {
  const _OutputLockedState({
    required this.image,
    required this.title,
    this.hint,
    this.action,
  });

  final String image;
  final String title;
  final String? hint;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            SvgPicture.asset(image, width: 180),
            const SizedBox(height: 16),
            Text(
              title,
              textAlign: TextAlign.center,
              style: theme.textTheme.titleMedium,
            ),
            if (hint != null) ...[
              const SizedBox(height: 4),
              Text(
                hint!,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodySmall,
              ),
            ],
            if (action != null) ...[const SizedBox(height: 16), action!],
          ],
        ),
      ),
    );
  }
}

/// Turns a usage-load failure into a message that names the real cause, so the
/// user knows whether to reconnect, retry, or wait.
String _usageErrorMessage(Object error) {
  if (error is ApiException) {
    if (error.requiresReconnect) {
      return 'نشست این دستگاه معتبر نیست؛ از تنظیمات دوباره وارد حساب شوید. (${error.code ?? 'token_revoked'})';
    }
    final status = error.statusCode == null
        ? ''
        : ' (HTTP ${error.statusCode})';
    return 'بررسی پلن ناموفق بود$status: ${error.message}';
  }
  return 'بررسی پلن ناموفق بود؛ پاسخ سرور خوانده نشد. دوباره تلاش کنید. (usage_unknown_error)';
}

class _OutputErrorState extends StatelessWidget {
  const _OutputErrorState({required this.message, required this.onRefresh});

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
