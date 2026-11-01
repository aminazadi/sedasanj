import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/utils/format.dart';
import '../application/recorder_controller.dart';

class RecordingScreen extends ConsumerWidget {
  const RecordingScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(recorderControllerProvider);
    final controller = ref.read(recorderControllerProvider.notifier);

    ref.listen(recorderControllerProvider, (previous, next) {
      if (next.savedMeetingId != null) {
        context.pushReplacement('/meeting/${next.savedMeetingId}');
      }
      if (next.error != null && next.error != previous?.error) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(next.error!)));
      }
    });

    final isRecording = state.status == RecorderStatus.recording;
    final isPaused = state.status == RecorderStatus.paused;
    final isSaving = state.status == RecorderStatus.saving;

    final isActive = isRecording || isPaused || isSaving;

    return PopScope(
      canPop: !isActive,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop || isSaving) return;
        final leave = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('توقف ضبط؟'),
            content: const Text(
              'ضبط در جریان است. با خروج، ضبط متوقف و جلسه ذخیره می‌شود.',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('ادامه ضبط'),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('توقف و ذخیره'),
              ),
            ],
          ),
        );
        if (leave == true) await controller.stop();
      },
      child: Scaffold(
        appBar: SsAppBar(title: const Text('ضبط جلسه')),
        body: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              if (state.status == RecorderStatus.idle) ...[
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  child: SsCard(
                    title: 'انتخاب ورودی صوتی',
                    trailing: IconButton(
                      onPressed: state.discoveringInputDevices
                          ? null
                          : controller.refreshInputDevices,
                      tooltip: 'به‌روزرسانی لیست',
                      visualDensity: VisualDensity.compact,
                      icon: state.discoveringInputDevices
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.refresh, size: 20),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        DropdownButton<String>(
                          isExpanded: true,
                          value: state.selectedInputDeviceId,
                          items: [
                            const DropdownMenuItem(
                              value: '',
                              child: Text('میکروفون پیش‌فرض'),
                            ),
                            for (final device in state.inputDevices)
                              DropdownMenuItem(
                                value: device.id,
                                child: Text(
                                  device.label.isEmpty
                                      ? 'میکروفون ${device.id}'
                                      : device.label,
                                ),
                              ),
                          ],
                          onChanged: (value) =>
                              controller.setInputDevice(value ?? ''),
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),
              ],
              AnimatedContainer(
                duration: const Duration(milliseconds: 300),
                width: 160,
                height: 160,
                decoration: BoxDecoration(
                  color: isRecording
                      ? const Color(0xFFF3DDE0)
                      : SsColors.selected,
                  border: Border.all(
                    color: isRecording ? SsColors.danger : SsColors.primary,
                  ),
                ),
                child: Stack(
                  alignment: Alignment.center,
                  children: [
                    const Positioned.fill(child: SsDots()),
                    Icon(
                      isRecording ? Icons.graphic_eq : Icons.mic,
                      size: 64,
                      color: isRecording ? SsColors.danger : SsColors.primary,
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 32),
              Text(
                formatDuration(state.elapsed),
                style: Theme.of(
                  context,
                ).textTheme.displaySmall?.copyWith(fontFeatures: const []),
              ),
              const SizedBox(height: 8),
              Text(switch (state.status) {
                RecorderStatus.idle => 'برای شروع ضبط، دکمه را بزنید',
                RecorderStatus.recording =>
                  state.interrupted
                      ? 'ضبط توسط سیستم متوقف شد (تماس یا برنامه‌ی دیگر)؛ پس از پایان خودکار ادامه می‌یابد'
                      : 'در حال ضبط',
                RecorderStatus.paused => 'ضبط متوقف شده است',
                RecorderStatus.saving => 'در حال ذخیره…',
              }, style: Theme.of(context).textTheme.bodyMedium),
              const SizedBox(height: 48),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  if (state.status == RecorderStatus.idle)
                    FilledButton.icon(
                      onPressed: controller.start,
                      icon: const Icon(Icons.fiber_manual_record),
                      label: const Text('شروع ضبط'),
                    ),
                  if (isRecording || isPaused) ...[
                    IconButton.outlined(
                      iconSize: 32,
                      onPressed: isRecording
                          ? controller.pause
                          : controller.resume,
                      icon: Icon(isRecording ? Icons.pause : Icons.play_arrow),
                    ),
                    const SizedBox(width: 24),
                    IconButton.filled(
                      iconSize: 40,
                      onPressed: isSaving ? null : controller.stop,
                      icon: const Icon(Icons.stop),
                    ),
                  ],
                  if (isSaving) const CircularProgressIndicator(),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
