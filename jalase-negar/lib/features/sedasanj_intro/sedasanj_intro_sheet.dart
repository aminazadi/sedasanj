import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:video_player/video_player.dart';

import '../../app/theme.dart';
import 'sedasanj_intro.dart';

/// Opens the drawer. Resolves with true when the user ticked "I know SedaSanj,
/// don't show again", whichever way the drawer was closed.
Future<bool> showSedasanjIntroSheet(
  BuildContext context,
  SedasanjIntroContent content,
) async {
  final result = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    backgroundColor: Colors.white,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.zero),
    builder: (_) => SedasanjIntroSheet(content: content),
  );
  return result ?? false;
}

class SedasanjIntroSheet extends StatefulWidget {
  const SedasanjIntroSheet({super.key, required this.content});

  final SedasanjIntroContent content;

  @override
  State<SedasanjIntroSheet> createState() => _SedasanjIntroSheetState();
}

class _SedasanjIntroSheetState extends State<SedasanjIntroSheet> {
  bool _known = false;
  VideoPlayerController? _video;
  bool _videoFailed = false;

  @override
  void initState() {
    super.initState();
    final url = widget.content.videoUrl;
    if (url != null) _startVideo(url);
  }

  Future<void> _startVideo(Uri url) async {
    final controller = VideoPlayerController.networkUrl(url);
    _video = controller;
    try {
      await controller.initialize();
      await controller.setLooping(false);
      if (mounted) setState(() {});
    } catch (_) {
      // No player on this platform or the link is unreachable: offer the link.
      if (mounted) setState(() => _videoFailed = true);
    }
  }

  @override
  void dispose() {
    _video?.dispose();
    super.dispose();
  }

  Future<void> _open(Uri uri) async {
    try {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        SnackBar(
          content: Text(
            'باز کردن لینک ممکن نشد؛ نشانی ${uri.host} را در مرورگر باز کنید.',
          ),
        ),
      );
    }
  }

  Widget _videoBox() {
    final controller = _video;
    final url = widget.content.videoUrl;
    if (url == null) return const SizedBox.shrink();
    if (_videoFailed) {
      return Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: OutlinedButton.icon(
          onPressed: () => _open(url),
          icon: const Icon(Icons.play_circle_outline),
          label: const Text('پخش ویدئوی معرفی'),
        ),
      );
    }
    if (controller == null || !controller.value.isInitialized) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 24),
        child: Center(child: CircularProgressIndicator()),
      );
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: AspectRatio(
        aspectRatio: controller.value.aspectRatio,
        child: Stack(
          alignment: Alignment.center,
          children: [
            VideoPlayer(controller),
            ValueListenableBuilder<VideoPlayerValue>(
              valueListenable: controller,
              builder: (_, value, _) => IconButton.filled(
                tooltip: value.isPlaying ? 'توقف' : 'پخش',
                onPressed: () =>
                    value.isPlaying ? controller.pause() : controller.play(),
                icon: Icon(value.isPlaying ? Icons.pause : Icons.play_arrow),
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.content;
    final theme = Theme.of(context);
    return Directionality(
      textDirection: TextDirection.rtl,
      child: PopScope(
        canPop: false,
        onPopInvokedWithResult: (didPop, _) {
          if (!didPop) Navigator.of(context).pop(_known);
        },
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            mainAxisSize: MainAxisSize.min,
            children: [
              Center(
                child: Container(width: 40, height: 4, color: SsColors.line),
              ),
              const SizedBox(height: 16),
              Text(c.title, style: theme.textTheme.titleLarge),
              const SizedBox(height: 12),
              _videoBox(),
              Text(
                c.body,
                style: theme.textTheme.bodyMedium?.copyWith(height: 1.9),
              ),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: () => _open(c.buttonUrl),
                child: Text(c.buttonLabel),
              ),
              const SizedBox(height: 8),
              CheckboxListTile(
                value: _known,
                onChanged: (v) => setState(() => _known = v ?? false),
                controlAffinity: ListTileControlAffinity.leading,
                contentPadding: EdgeInsets.zero,
                title: const Text('با صداسنج آشنا هستم و دیگر نمایش نده'),
              ),
              TextButton(
                onPressed: () => Navigator.of(context).pop(_known),
                child: const Text('بستن'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
