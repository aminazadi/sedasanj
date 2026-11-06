import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_svg/flutter_svg.dart';

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

    return Align(
      alignment: Alignment.topCenter,
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 432),
          child: Padding(
            padding: const EdgeInsets.all(4),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                ExcludeSemantics(
                  child: AspectRatio(
                    aspectRatio: 480 / 230,
                    child: SvgPicture.asset(
                      state.ready
                          ? 'assets/images/brand/model-ready.svg'
                          : state.installingAll
                          ? 'assets/images/brand/model-progress.svg'
                          : 'assets/images/brand/model-download.svg',
                      fit: BoxFit.contain,
                    ),
                  ),
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
    );
  }
}
