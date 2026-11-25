import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'package:go_router/go_router.dart';

import '../../../app/widgets/ss_widgets.dart';
import '../../../core/platform/api_client.dart';
import '../../documents/presentation/documents_tab.dart';
import '../../catalog/application/catalog_providers.dart';
import '../../settings/application/connection_controller.dart';
import 'minutes_tab.dart';

/// «خروجی جلسه»: the server-built minutes and documents, shown only to a
/// signed-in account with usable plan hours; otherwise a locked state asking
/// to sign in or buy/upgrade a plan. If the plan check itself fails the output
/// is still shown, with the reason and a retry in a banner.
class MeetingOutputTab extends ConsumerWidget {
  const MeetingOutputTab({super.key, this.remoteMeetingId});

  /// Null while the meeting has not reached the server yet; the categories still show.
  final String? remoteMeetingId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final connection = ref
        .watch(connectionControllerProvider)
        .value
        ?.connection;
    final loggedIn = connection != null && connection.personal;
    final remote = remoteMeetingId;
    if (!loggedIn || remote == null) {
      // Categories are public and always listed. Only the account (sign-in, active plan)
      // and the meeting's place on the server decide what else is asked for.
      final noPlan =
          loggedIn && (ref.watch(usageProvider).value?.exhausted ?? false);
      const pending = 'این جلسه هنوز پردازش نشده است.';
      final prompt = !loggedIn
          ? _OutputPrompt(
              image: 'assets/images/brand/login-required.svg',
              pending: remote == null ? pending : null,
              hint: 'برای ساخت خروجی وارد شوید.',
              actionLabel: 'ورود',
              onAction: () => context.push('/login'),
            )
          : noPlan
          ? _OutputPrompt(
              image: 'assets/images/brand/plan-upgrade.svg',
              pending: remote == null ? pending : null,
              hint: 'پلن فعال ندارید.',
              actionLabel: 'خرید پلن',
              onAction: () => context.push('/plans'),
            )
          : null;
      // Same placement as the speakers empty state: the prompt sits in the middle of the tab,
      // and the category list follows it when there is one.
      return LayoutBuilder(
        builder: (context, constraints) => SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: ConstrainedBox(
            constraints: BoxConstraints(minHeight: constraints.maxHeight - 32),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                if (prompt != null)
                  prompt
                else if (remote == null)
                  const Text(pending, textAlign: TextAlign.center),
                const SizedBox(height: 16),
                const _CategoryPreview(),
              ],
            ),
          ),
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
          remoteMeetingId: remote,
          banner: _PlanCheckBanner(
            message: _usageErrorMessage(error),
            onAction: retry,
          ),
        );
      },
      data: (info) {
        // Used-up hours never hide what already exists; they only block new
        // documents, so the tab stays and offers the plan page.
        final entitled = info.unlimited || !info.exhausted;
        return _OutputTabs(
          remoteMeetingId: remote,
          banner: entitled
              ? null
              : _PlanCheckBanner(
                  message:
                      'ساعت پلن تمام شده است؛ برای ساخت خروجی جدید پلن تهیه کنید.',
                  actionLabel: 'پلن و مصرف',
                  onAction: () => context.push('/plans'),
                ),
        );
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
  const _PlanCheckBanner({
    required this.message,
    required this.onAction,
    this.actionLabel = 'بررسی دوباره',
  });

  final String message;
  final VoidCallback onAction;
  final String actionLabel;

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
          TextButton(onPressed: onAction, child: Text(actionLabel)),
        ],
      ),
    );
  }
}

/// Locked empty state for the output tab: an illustration of its own
/// (instead of [SsEmptyState]'s fixed one), a message and an action button.
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

/// Categories the admin published, shown to everyone; no account or plan needed.
class _CategoryPreview extends ConsumerWidget {
  const _CategoryPreview();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final types = ref.watch(outputTypesProvider);
    return types.when(
      loading: () => const SizedBox.shrink(),
      error: (_, _) => const SizedBox.shrink(),
      data: (items) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (final type in items)
            Card(
              child: ListTile(
                title: Text(type.title),
                subtitle: type.description.isEmpty
                    ? null
                    : Text(type.description),
              ),
            ),
        ],
      ),
    );
  }
}

/// The same layout as the speakers empty state: an illustration, a status title, one hint and
/// one action. Shown when the account cannot create output yet.
class _OutputPrompt extends StatelessWidget {
  const _OutputPrompt({
    required this.image,
    required this.hint,
    required this.actionLabel,
    required this.onAction,
    this.pending,
  });

  final String image;

  /// The meeting's status, shown as the title when there is one.
  final String? pending;
  final String hint;
  final String actionLabel;
  final VoidCallback onAction;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          SvgPicture.asset(image, width: 180),
          const SizedBox(height: 16),
          Text(
            pending ?? hint,
            textAlign: TextAlign.center,
            style: theme.textTheme.titleMedium,
          ),
          if (pending != null) ...[
            const SizedBox(height: 4),
            Text(
              hint,
              textAlign: TextAlign.center,
              style: theme.textTheme.bodySmall,
            ),
          ],
          const SizedBox(height: 16),
          FilledButton.icon(
            icon: const Icon(Icons.phone_android, size: 18),
            label: Text(actionLabel),
            onPressed: onAction,
          ),
        ],
      ),
    );
  }
}
