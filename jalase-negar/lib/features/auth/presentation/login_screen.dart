import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/platform/api_client.dart';
import '../../../core/platform/distribution.dart';
import '../../settings/application/connection_controller.dart';

enum _Step { mobile, code, name }

/// Phone-number sign-in: mobile → SMS code → (first time only) display name.
class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key, this.serverUrl = kDefaultServerUrl});

  final String serverUrl;

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _mobile = TextEditingController();
  final _code = TextEditingController();
  final _name = TextEditingController();
  late final ApiClient _api = ApiClient(serverUrl: widget.serverUrl);
  _Step _step = _Step.mobile;
  bool _busy = false;
  String? _error;
  String? _otpId;
  String? _verified;
  int _resendIn = 0;
  Timer? _timer;

  @override
  void dispose() {
    _timer?.cancel();
    _mobile.dispose();
    _code.dispose();
    _name.dispose();
    super.dispose();
  }

  Future<void> _run(Future<void> Function() action) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } on Object {
      if (mounted) {
        setState(
          () => _error =
              'خطای پیش‌بینی‌نشده؛ اینترنت را بررسی کنید و دوباره تلاش کنید.',
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _startCountdown(Duration wait) {
    _timer?.cancel();
    _resendIn = wait.inSeconds;
    _timer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted || _resendIn <= 1) {
        t.cancel();
        if (mounted) setState(() => _resendIn = 0);
        return;
      }
      setState(() => _resendIn -= 1);
    });
  }

  Future<void> _sendCode() => _run(() async {
    final result = await _api.requestOtp(_mobile.text.trim());
    _otpId = result.otpId;
    _code.clear();
    _startCountdown(result.resendAfter);
    if (mounted) setState(() => _step = _Step.code);
  });

  Future<void> _verify() => _run(() async {
    final result = await _api.verifyOtp(
      otpId: _otpId!,
      code: _code.text.trim(),
    );
    _verified = result.token;
    if (result.hasAccount) {
      await _complete();
    } else if (mounted) {
      // First time on this number: ask for a name before creating the account.
      setState(() => _step = _Step.name);
    }
  });

  Future<void> _complete({String? displayName}) async {
    final controller = ref.read(connectionControllerProvider.notifier);
    final version = await ref.read(appVersionProvider.future);
    final login = await _api.completeLogin(
      verifiedToken: _verified!,
      displayName: displayName,
      deviceName: controller.deviceLabel(),
      platform: controller.loginPlatform(),
      appVersion: version,
    );
    await controller.savePersonal(serverUrl: widget.serverUrl, login: login);
    if (!mounted) return;
    context.go('/settings');
  }

  Future<void> _saveName() => _run(() => _complete(displayName: _name.text));

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('ورود با شماره موبایل')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text(switch (_step) {
              _Step.mobile =>
                'شمارهٔ موبایل خود را وارد کنید؛ کد تأیید پیامک می‌شود.',
              _Step.code => 'کد ۶رقمی پیامک‌شده را وارد کنید.',
              _Step.name => 'نام خود را وارد کنید.',
            }, style: theme.textTheme.bodyLarge),
            const SizedBox(height: 16),
            if (_step == _Step.mobile)
              TextField(
                controller: _mobile,
                enabled: !_busy,
                keyboardType: TextInputType.phone,
                textDirection: TextDirection.ltr,
                autofillHints: const [AutofillHints.telephoneNumber],
                inputFormatters: [
                  FilteringTextInputFormatter.allow(RegExp(r'[0-9+]')),
                ],
                decoration: const InputDecoration(
                  labelText: 'شمارهٔ موبایل',
                  hintText: '09123456789',
                ),
                onSubmitted: (_) => _sendCode(),
              ),
            if (_step == _Step.code) ...[
              TextField(
                controller: _code,
                enabled: !_busy,
                keyboardType: TextInputType.number,
                textDirection: TextDirection.ltr,
                maxLength: 6,
                autofillHints: const [AutofillHints.oneTimeCode],
                inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                decoration: const InputDecoration(labelText: 'کد تأیید'),
                onSubmitted: (_) => _verify(),
              ),
              Align(
                alignment: AlignmentDirectional.centerStart,
                child: TextButton(
                  onPressed: _busy || _resendIn > 0 ? null : _sendCode,
                  child: Text(
                    _resendIn > 0
                        ? 'ارسال دوباره ($_resendIn ثانیه)'
                        : 'ارسال دوبارهٔ کد',
                  ),
                ),
              ),
            ],
            if (_step == _Step.name)
              TextField(
                controller: _name,
                enabled: !_busy,
                maxLength: 80,
                decoration: const InputDecoration(labelText: 'نام'),
                onSubmitted: (_) => _saveName(),
              ),
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(_error!, style: TextStyle(color: theme.colorScheme.error)),
            ],
            const SizedBox(height: 16),
            FilledButton(
              onPressed: _busy
                  ? null
                  : switch (_step) {
                      _Step.mobile => _sendCode,
                      _Step.code => _verify,
                      _Step.name => _saveName,
                    },
              child: Text(switch (_step) {
                _Step.mobile => 'ارسال کد',
                _Step.code => 'تأیید و ورود',
                _Step.name => 'ادامه',
              }),
            ),
          ],
        ),
      ),
    );
  }
}
