import 'package:flutter/material.dart';
import 'package:package_info_plus/package_info_plus.dart';

import 'theme.dart';
import 'widgets/brand_logo.dart';
import 'widgets/ss_widgets.dart';

/// Start-up screen: the animated SedaSanj wordmark on the dotted canvas, like
/// the web panel's route loader (dots fade out towards the centre).
class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key, this.onComplete});

  final VoidCallback? onComplete;

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  late final Future<PackageInfo> _packageInfo = PackageInfo.fromPlatform();

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    return Scaffold(
      backgroundColor: SsColors.canvas,
      body: Stack(
        children: [
          Positioned.fill(
            child: ShaderMask(
              blendMode: BlendMode.dstIn,
              shaderCallback: (rect) => RadialGradient(
                radius: 0.75,
                colors: const [
                  Colors.transparent,
                  Color(0x14000000),
                  Colors.black,
                ],
                stops: const [0.2, 0.45, 1],
              ).createShader(rect),
              child: const SsDots(color: Color(0x334B6E48)),
            ),
          ),
          Center(
            child: SsBrandLogo(
              width: (width * 0.76).clamp(0, 320),
              onComplete: widget.onComplete,
            ),
          ),
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: SafeArea(
              minimum: const EdgeInsets.only(bottom: 24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const SsProcessingMark(size: 22),
                  const SizedBox(height: 14),
                  FutureBuilder<PackageInfo>(
                    future: _packageInfo,
                    builder: (context, snapshot) {
                      final version = snapshot.data?.version;
                      return Text(
                        version == null
                            ? 'جلسه‌نگار'
                            : 'جلسه‌نگار نسخه \u2066$version\u2069',
                        textDirection: TextDirection.rtl,
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: SsColors.primary,
                        ),
                      );
                    },
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
