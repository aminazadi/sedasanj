import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_toast.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/platform/api_client.dart';
import '../../settings/application/connection_controller.dart';

/// Deletes the personal account after an SMS check of its own number.
class DeleteAccountScreen extends ConsumerStatefulWidget {
  const DeleteAccountScreen({super.key});

  @override
  ConsumerState<DeleteAccountScreen> createState() =>
      _DeleteAccountScreenState();
}

class _DeleteAccountScreenState extends ConsumerState<DeleteAccountScreen> {
  final _mobile = TextEditingController();
  final _code = TextEditingController();
  String? _otpId;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _mobile.dispose();
    _code.dispose();
    super.dispose();
  }

  String _message(Object e) => e is ApiException
      ? e.message
      : 'ارتباط با سرور برقرار نشد؛ اینترنت را بررسی کنید و دوباره تلاش کنید.';

  Future<void> _sendCode() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final client = await ref.read(personalClientProvider.future);
      final result = await client.requestOtp(_mobile.text.trim());
      if (mounted) setState(() => _otpId = result.otpId);
    } on Object catch (e) {
      if (mounted) setState(() => _error = _message(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _delete() async {
    final sure = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('حذف همیشگی حساب؟'),
        content: const Text(
          'همهٔ جلسه‌ها، متن‌ها و اسناد شخصی شما پاک می‌شود و اشتراک فعال لغو '
          'می‌شود (بازپرداخت ندارد). این کار برگشت‌پذیر نیست.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('انصراف'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('حذف حساب'),
          ),
        ],
      ),
    );
    if (sure != true) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final client = await ref.read(personalClientProvider.future);
      final verified = await client.verifyOtp(
        otpId: _otpId!,
        code: _code.text.trim(),
      );
      await client.deleteAccount(verified.token);
      await ref
          .read(connectionControllerProvider.notifier)
          .forgetAfterDeletion();
      if (!mounted) return;
      Navigator.of(context).popUntil((route) => route.isFirst);
      await SsToastHost.show(context, 'حساب شما حذف شد.');
    } on Object catch (e) {
      if (mounted) setState(() => _error = _message(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: SsAppBar(title: const Text('حذف حساب')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text(
            'برای حذف حساب، شمارهٔ موبایل خودتان را وارد کنید و کد پیامکی را '
            'تأیید کنید.',
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _mobile,
            enabled: _otpId == null,
            keyboardType: TextInputType.phone,
            textDirection: TextDirection.ltr,
            decoration: const InputDecoration(labelText: 'شمارهٔ موبایل'),
          ),
          if (_otpId != null) ...[
            const SizedBox(height: 12),
            TextField(
              controller: _code,
              keyboardType: TextInputType.number,
              textDirection: TextDirection.ltr,
              decoration: const InputDecoration(labelText: 'کد پیامکی'),
            ),
          ],
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                _error!,
                style: const TextStyle(color: SsColors.danger),
              ),
            ),
          const SizedBox(height: 16),
          if (_otpId == null)
            FilledButton(
              onPressed: _busy ? null : _sendCode,
              child: const Text('ارسال کد'),
            )
          else
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: SsColors.danger),
              onPressed: _busy ? null : _delete,
              child: const Text('حذف همیشگی حساب'),
            ),
        ],
      ),
    );
  }
}
