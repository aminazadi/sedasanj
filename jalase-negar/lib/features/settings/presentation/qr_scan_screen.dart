import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_widgets.dart';

/// Full-screen camera that scans the pairing QR from the panel and pops with
/// its raw text. A square frame in the centre guides where to place the code.
class QrScanScreen extends StatefulWidget {
  const QrScanScreen({super.key});

  @override
  State<QrScanScreen> createState() => _QrScanScreenState();
}

class _QrScanScreenState extends State<QrScanScreen>
    with SingleTickerProviderStateMixin {
  final _controller = MobileScannerController(
    formats: const [BarcodeFormat.qrCode],
  );
  late final AnimationController _line = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 2200),
  )..repeat(reverse: true);
  bool _done = false;

  @override
  void initState() {
    super.initState();
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
  }

  @override
  void dispose() {
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
    _line.dispose();
    _controller.dispose();
    super.dispose();
  }

  void _onDetect(BarcodeCapture capture) {
    if (_done) return;
    for (final code in capture.barcodes) {
      final value = code.rawValue;
      if (value != null && value.isNotEmpty) {
        _done = true;
        HapticFeedback.mediumImpact();
        Navigator.of(context).pop(value);
        return;
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    final side = (size.shortestSide * 0.7).clamp(200.0, 320.0);
    final window = Rect.fromCenter(
      center: Offset(size.width / 2, size.height * 0.42),
      width: side,
      height: side,
    );

    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.light,
      child: Scaffold(
        backgroundColor: Colors.black,
        body: Stack(
          fit: StackFit.expand,
          children: [
            MobileScanner(
              controller: _controller,
              fit: BoxFit.cover,
              scanWindow: window,
              onDetect: _onDetect,
              errorBuilder: (context, error) => const _CameraError(),
            ),
            CustomPaint(painter: _ScrimPainter(window)),
            AnimatedBuilder(
              animation: _line,
              builder: (context, _) => CustomPaint(
                painter: _FramePainter(
                  window,
                  _line.value,
                  SsColors.of(context).accent,
                ),
              ),
            ),
            Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              child: SafeArea(
                top: false,
                minimum: const EdgeInsets.only(bottom: 20),
                child: Center(
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Tooltip(
                        message: 'بستن',
                        child: SsDiamondButton(
                          half: 38,
                          icon: Icons.close,
                          danger: true,
                          onTap: () => Navigator.of(context).maybePop(),
                        ),
                      ),
                      ValueListenableBuilder<MobileScannerState>(
                        valueListenable: _controller,
                        builder: (context, state, _) {
                          if (state.torchState == TorchState.unavailable) {
                            return const SizedBox.shrink();
                          }
                          final on = state.torchState == TorchState.on;
                          return Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              const SizedBox(width: 28),
                              Tooltip(
                                message: on
                                    ? 'خاموش کردن چراغ'
                                    : 'روشن کردن چراغ',
                                child: SsDiamondButton(
                                  half: 38,
                                  icon: on ? Icons.flash_on : Icons.flash_off,
                                  outlined: !on,
                                  onTap: _controller.toggleTorch,
                                ),
                              ),
                            ],
                          );
                        },
                      ),
                    ],
                  ),
                ),
              ),
            ),
            Positioned(
              left: 24,
              right: 24,
              top: window.bottom + 28,
              child: const Column(
                children: [
                  Text(
                    'اسکن QR اتصال',
                    style: TextStyle(
                      fontFamily: 'Vazirmatn',
                      color: Colors.white,
                      fontSize: 18,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  SizedBox(height: 8),
                  Text(
                    'کد QR نمایش‌داده‌شده در پنل صداسنج را داخل کادر قرار دهید.',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontFamily: 'Vazirmatn',
                      color: Color(0xCCFFFFFF),
                      fontSize: 13,
                      height: 1.7,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _CameraError extends StatelessWidget {
  const _CameraError();

  @override
  Widget build(BuildContext context) {
    return const ColoredBox(
      color: Colors.black,
      child: Center(
        child: Padding(
          padding: EdgeInsets.all(32),
          child: Text(
            'دسترسی به دوربین ممکن نیست؛ مجوز دوربین را در تنظیمات گوشی بدهید '
            'یا به‌جای آن فایل کانفیگ را انتخاب کنید.',
            textAlign: TextAlign.center,
            style: TextStyle(
              fontFamily: 'Vazirmatn',
              color: Colors.white,
              height: 1.8,
            ),
          ),
        ),
      ),
    );
  }
}

/// Dims everything except the rounded scan window.
class _ScrimPainter extends CustomPainter {
  _ScrimPainter(this.window);

  final Rect window;

  @override
  void paint(Canvas canvas, Size size) {
    final path = Path()
      ..fillType = PathFillType.evenOdd
      ..addRect(Offset.zero & size)
      ..addRRect(RRect.fromRectAndRadius(window, const Radius.circular(24)));
    canvas.drawPath(path, Paint()..color = const Color(0xAA000000));
  }

  @override
  bool shouldRepaint(_ScrimPainter old) => old.window != window;
}

/// Corner brackets plus a sweeping scan line inside the window.
class _FramePainter extends CustomPainter {
  _FramePainter(this.window, this.t, this.accentColor);

  final Rect window;
  final double t;
  final Color accentColor;

  @override
  void paint(Canvas canvas, Size size) {
    const radius = 24.0;
    const arm = 36.0;
    final corner = Paint()
      ..color = accentColor
      ..style = PaintingStyle.stroke
      ..strokeWidth = 5
      ..strokeCap = StrokeCap.round;

    final l = window.left, r = window.right, tp = window.top, b = window.bottom;
    final path = Path()
      // top-left
      ..moveTo(l, tp + arm)
      ..lineTo(l, tp + radius)
      ..arcToPoint(
        Offset(l + radius, tp),
        radius: const Radius.circular(radius),
      )
      ..lineTo(l + arm, tp)
      // top-right
      ..moveTo(r - arm, tp)
      ..lineTo(r - radius, tp)
      ..arcToPoint(
        Offset(r, tp + radius),
        radius: const Radius.circular(radius),
      )
      ..lineTo(r, tp + arm)
      // bottom-right
      ..moveTo(r, b - arm)
      ..lineTo(r, b - radius)
      ..arcToPoint(Offset(r - radius, b), radius: const Radius.circular(radius))
      ..lineTo(r - arm, b)
      // bottom-left
      ..moveTo(l + arm, b)
      ..lineTo(l + radius, b)
      ..arcToPoint(Offset(l, b - radius), radius: const Radius.circular(radius))
      ..lineTo(l, b - arm);
    canvas.drawPath(path, corner);

    final y = tp + 16 + (window.height - 32) * Curves.easeInOut.transform(t);
    final rect = Rect.fromLTRB(l + 20, y - 1.5, r - 20, y + 1.5);
    canvas.drawRRect(
      RRect.fromRectAndRadius(rect, const Radius.circular(2)),
      Paint()
        ..shader = LinearGradient(
          colors: [
            accentColor.withValues(alpha: 0),
            accentColor,
            accentColor.withValues(alpha: 0),
          ],
        ).createShader(rect)
        ..maskFilter = const MaskFilter.blur(BlurStyle.solid, 2),
    );
  }

  @override
  bool shouldRepaint(_FramePainter old) =>
      old.t != t || old.window != window || old.accentColor != accentColor;
}
