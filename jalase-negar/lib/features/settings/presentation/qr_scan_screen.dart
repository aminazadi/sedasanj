import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../../../app/widgets/ss_widgets.dart';

/// Scans the pairing QR from the panel and pops with its raw text.
class QrScanScreen extends StatefulWidget {
  const QrScanScreen({super.key});

  @override
  State<QrScanScreen> createState() => _QrScanScreenState();
}

class _QrScanScreenState extends State<QrScanScreen> {
  bool _done = false;

  void _onDetect(BarcodeCapture capture) {
    if (_done) return;
    for (final code in capture.barcodes) {
      final value = code.rawValue;
      if (value != null && value.isNotEmpty) {
        _done = true;
        Navigator.of(context).pop(value);
        return;
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: SsAppBar(title: const Text('اسکن QR اتصال')),
      body: MobileScanner(
        onDetect: _onDetect,
        errorBuilder: (context, error) => const Center(
          child: Padding(
            padding: EdgeInsets.all(24),
            child: Text(
              'دسترسی به دوربین ممکن نیست؛ مجوز دوربین را در تنظیمات گوشی بدهید '
              'یا به‌جای آن فایل کانفیگ را انتخاب کنید.',
              textAlign: TextAlign.center,
            ),
          ),
        ),
      ),
    );
  }
}
