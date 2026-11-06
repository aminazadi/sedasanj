import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/utils/format.dart';
import '../../onboarding/tour_overlay.dart';
import '../../onboarding/tour_step.dart';
import '../application/models_controller.dart';
import '../../../app/widgets/ss_widgets.dart';

class ModelsScreen extends ConsumerWidget {
  const ModelsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(modelsControllerProvider);
    return Scaffold(
      appBar: SsAppBar(
        title: Padding(
          padding: Navigator.canPop(context)
              ? EdgeInsets.zero
              : const EdgeInsetsDirectional.only(start: 12),
          child: const TourTarget(
            step: TourStep.models,
            child: Text('مدل‌های هوش مصنوعی'),
          ),
        ),
      ),
      body: state.loading
          ? const Center(child: CircularProgressIndicator())
          : const _InstallAllCard(),
    );
  }
}

/// The only thing on this screen: one card that downloads, installs and
/// activates everything in a single tap.
class _InstallAllCard extends ConsumerWidget {
  const _InstallAllCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(modelsControllerProvider);
    final controller = ref.read(modelsControllerProvider.notifier);
    final theme = Theme.of(context);
    final percent = toPersianDigits('${(state.progress * 100).floor()}');
    final failed = state.hasFailure && !state.installingAll;

    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 432),
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Icon(
                    state.ready
                        ? Icons.check_circle_outline
                        : Icons.download_for_offline_outlined,
                    size: 48,
                    color: theme.colorScheme.primary,
                  ),
                  const SizedBox(height: 12),
                  Text(
                    state.ready ? 'نصب و فعال است' : 'دانلود، نصب و فعال‌سازی',
                    textAlign: TextAlign.center,
                    style: theme.textTheme.titleLarge,
                  ),
                  const SizedBox(height: 16),
                  if (state.installingAll) ...[
                    LinearProgressIndicator(value: state.progress),
                    const SizedBox(height: 8),
                    Text(
                      '$percent٪',
                      textAlign: TextAlign.center,
                      style: theme.textTheme.labelLarge,
                    ),
                    const SizedBox(height: 8),
                    TextButton(
                      onPressed: controller.cancelAll,
                      child: const Text('توقف'),
                    ),
                  ] else if (!state.ready) ...[
                    if (failed) ...[
                      Text(
                        'دانلود کامل نشد. اینترنت را بررسی و دوباره بزنید.',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: theme.colorScheme.error),
                      ),
                      const SizedBox(height: 12),
                    ],
                    FilledButton.icon(
                      icon: const Icon(Icons.download),
                      label: Text(failed ? 'ادامه دانلود' : 'شروع'),
                      onPressed: controller.installAll,
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
