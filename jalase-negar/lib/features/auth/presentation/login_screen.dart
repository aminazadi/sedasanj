import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/platform/api_client.dart';
import '../../../core/platform/distribution.dart';
import '../../../core/utils/format.dart';
import '../../settings/application/connection_controller.dart';

enum _Step { mobile, code, name }

const _otpLength = 6;

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
  final _fieldKey = GlobalKey();
  double? _fieldHeight;

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

  /// Keeps the primary button exactly as tall as the current step's field
  /// (or OTP row), measured after layout instead of guessed from theme
  /// constants, so it stays correct if the field's own styling changes.
  void _matchButtonToFieldHeight() {
    final height = (_fieldKey.currentContext?.findRenderObject() as RenderBox?)
        ?.size
        .height;
    if (height != null && height != _fieldHeight && mounted) {
      setState(() => _fieldHeight = height);
    }
  }

  Future<void> _openLink(Uri uri) async {
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

  /// Back to the mobile step to fix a mistyped number; cancels the resend
  /// countdown and the code already requested from the server.
  void _editMobile() {
    _timer?.cancel();
    setState(() {
      _error = null;
      _resendIn = 0;
      _otpId = null;
      _step = _Step.mobile;
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    WidgetsBinding.instance.addPostFrameCallback(
      (_) => _matchButtonToFieldHeight(),
    );
    return Scaffold(
      body: SsDots(
        child: SafeArea(
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsetsDirectional.only(start: 8, top: 4),
                child: Align(
                  alignment: AlignmentDirectional.centerStart,
                  child: BackButton(
                    onPressed: _busy ? null : () => context.pop(),
                  ),
                ),
              ),
              Expanded(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
                  child: Center(
                    child: ConstrainedBox(
                      constraints: const BoxConstraints(maxWidth: 420),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          ConstrainedBox(
                            constraints: const BoxConstraints(maxHeight: 180),
                            child: Image.asset(
                              switch (_step) {
                                _Step.mobile =>
                                  'assets/images/brand/phone-auth-dialog.webp',
                                _Step.code =>
                                  'assets/images/brand/phone-auth-otp.webp',
                                _Step.name =>
                                  'assets/images/brand/phone-auth-organization.webp',
                              },
                              fit: BoxFit.contain,
                            ),
                          ),
                          const SizedBox(height: 16),
                          Semantics(
                            header: true,
                            child: Text(
                              switch (_step) {
                                _Step.mobile => 'ورود یا ثبت‌نام',
                                _Step.code => 'تأیید شماره موبایل',
                                _Step.name => 'یک قدم تا پایان',
                              },
                              textAlign: TextAlign.center,
                              style: theme.textTheme.headlineSmall,
                            ),
                          ),
                          const SizedBox(height: 8),
                          Text(
                            switch (_step) {
                              _Step.mobile => 'شمارهٔ موبایل خود را وارد کنید.',
                              _Step.code =>
                                'کد ۶رقمی پیامک‌شده به '
                                    '${toPersianDigits(_mobile.text.trim())} '
                                    'را وارد کنید.',
                              _Step.name => 'نام خود را وارد کنید.',
                            },
                            textAlign: TextAlign.center,
                            style: theme.textTheme.bodyMedium,
                          ),
                          const SizedBox(height: 24),
                          // No outer SsCard here: the text field and the OTP
                          // boxes already draw their own border, and a card
                          // around them just nested a box inside a box.
                          _StepFields(
                            fieldKey: _fieldKey,
                            step: _step,
                            busy: _busy,
                            hasError: _error != null,
                            mobileController: _mobile,
                            codeController: _code,
                            nameController: _name,
                            resendIn: _resendIn,
                            onSendCode: _sendCode,
                            onVerify: _verify,
                            onSaveName: _saveName,
                            onEditMobile: _editMobile,
                          ),
                          if (_error != null) ...[
                            const SizedBox(height: 16),
                            _ErrorBanner(_error!),
                          ],
                          const SizedBox(height: 16),
                          SizedBox(
                            width: double.infinity,
                            child: FilledButton(
                              style: _fieldHeight == null
                                  ? null
                                  : FilledButton.styleFrom(
                                      minimumSize: Size.fromHeight(
                                        _fieldHeight!,
                                      ),
                                    ),
                              onPressed: _busy
                                  ? null
                                  : switch (_step) {
                                      _Step.mobile => _sendCode,
                                      _Step.code => _verify,
                                      _Step.name => _saveName,
                                    },
                              child: _busy
                                  ? SizedBox(
                                      height: 20,
                                      width: 20,
                                      child: CircularProgressIndicator(
                                        strokeWidth: 2.4,
                                        color: SsColors.of(context).canvas,
                                      ),
                                    )
                                  : Text(switch (_step) {
                                      _Step.mobile => 'ارسال کد',
                                      _Step.code => 'تأیید و ورود',
                                      _Step.name => 'ادامه',
                                    }),
                            ),
                          ),
                          const SizedBox(height: 24),
                          _LegalFooter(onOpen: _openLink),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// The fields for the current step, split out only so [LoginScreen] stays
/// readable.
class _StepFields extends StatelessWidget {
  const _StepFields({
    required this.fieldKey,
    required this.step,
    required this.busy,
    required this.hasError,
    required this.mobileController,
    required this.codeController,
    required this.nameController,
    required this.resendIn,
    required this.onSendCode,
    required this.onVerify,
    required this.onSaveName,
    required this.onEditMobile,
  });

  /// Marks the field (or OTP row) whose rendered height the primary button
  /// below should match.
  final Key fieldKey;
  final _Step step;
  final bool busy;
  final bool hasError;
  final TextEditingController mobileController;
  final TextEditingController codeController;
  final TextEditingController nameController;
  final int resendIn;
  final VoidCallback onSendCode;
  final VoidCallback onVerify;
  final VoidCallback onSaveName;
  final VoidCallback onEditMobile;

  @override
  Widget build(BuildContext context) {
    return switch (step) {
      _Step.mobile => KeyedSubtree(
        key: fieldKey,
        child: TextField(
          controller: mobileController,
          enabled: !busy,
          autofocus: true,
          keyboardType: TextInputType.phone,
          textDirection: TextDirection.ltr,
          textAlign: TextAlign.center,
          autofillHints: const [AutofillHints.telephoneNumber],
          inputFormatters: [
            FilteringTextInputFormatter.allow(RegExp(r'[0-9+]')),
          ],
          style: const TextStyle(fontSize: 18, letterSpacing: 1),
          decoration: const InputDecoration(hintText: '09123456789'),
          onSubmitted: (_) => onSendCode(),
        ),
      ),
      _Step.code => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          KeyedSubtree(
            key: fieldKey,
            child: _OtpBoxField(
              controller: codeController,
              enabled: !busy,
              error: hasError,
              onCompleted: () {
                if (!busy) onVerify();
              },
            ),
          ),
          const SizedBox(height: 16),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              TextButton(
                onPressed: busy ? null : onEditMobile,
                child: const Text('ویرایش شماره'),
              ),
              TextButton(
                onPressed: busy || resendIn > 0 ? null : onSendCode,
                child: Text(
                  resendIn > 0
                      ? 'ارسال دوباره (${toPersianDigits('$resendIn')})'
                      : 'ارسال دوبارهٔ کد',
                ),
              ),
            ],
          ),
        ],
      ),
      _Step.name => KeyedSubtree(
        key: fieldKey,
        child: TextField(
          controller: nameController,
          enabled: !busy,
          autofocus: true,
          maxLength: 80,
          textAlign: TextAlign.center,
          decoration: const InputDecoration(
            prefixIcon: Icon(Icons.person_outline),
            labelText: 'نام',
            counterText: '',
          ),
          onSubmitted: (_) => onSaveName(),
        ),
      ),
    };
  }
}

/// Bordered, alpha-tinted banner matching [SsBadge]'s visual language.
class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner(this.message);

  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: SsColors.of(context).danger.withValues(alpha: 0.06),
        border: Border.all(
          color: SsColors.of(context).danger.withValues(alpha: 0.4),
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            Icons.error_outline,
            color: SsColors.of(context).danger,
            size: 18,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: SsColors.of(context).danger,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// "شرایط استفاده · حریم خصوصی" links pinned under the primary button.
class _LegalFooter extends StatelessWidget {
  const _LegalFooter({required this.onOpen});

  final void Function(Uri uri) onOpen;

  @override
  Widget build(BuildContext context) {
    final style = Theme.of(
      context,
    ).textTheme.bodySmall?.copyWith(decoration: TextDecoration.underline);
    Widget link(String label, String path) => InkWell(
      onTap: () => onOpen(Uri.https('sedasanj.ir', path)),
      child: Text(label, style: style),
    );
    return Center(
      child: Wrap(
        alignment: WrapAlignment.center,
        crossAxisAlignment: WrapCrossAlignment.center,
        spacing: 8,
        children: [
          link('شرایط استفاده', '/terms'),
          Text('·', style: TextStyle(color: SsColors.of(context).neutral)),
          link('حریم خصوصی', '/privacy'),
        ],
      ),
    );
  }
}

/// Six boxes showing the OTP digits as they're typed, backed by a real,
/// invisible [TextField] so the keyboard, paste and the platform's SMS
/// autofill (`AutofillHints.oneTimeCode`) all keep working normally.
class _OtpBoxField extends StatefulWidget {
  const _OtpBoxField({
    required this.controller,
    required this.enabled,
    required this.error,
    required this.onCompleted,
  });

  final TextEditingController controller;
  final bool enabled;
  final bool error;
  final VoidCallback onCompleted;

  @override
  State<_OtpBoxField> createState() => _OtpBoxFieldState();
}

class _OtpBoxFieldState extends State<_OtpBoxField> {
  final _focusNode = FocusNode();

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_onChanged);
    if (widget.enabled) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _focusNode.requestFocus();
      });
    }
  }

  void _onChanged() {
    setState(() {});
    if (widget.controller.text.length == _otpLength) widget.onCompleted();
  }

  @override
  void dispose() {
    widget.controller.removeListener(_onChanged);
    _focusNode.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final text = widget.controller.text;
    return GestureDetector(
      onTap: widget.enabled ? () => _focusNode.requestFocus() : null,
      child: Stack(
        alignment: Alignment.center,
        children: [
          ExcludeSemantics(
            child: LayoutBuilder(
              builder: (context, constraints) {
                // Shrink the boxes on narrow phones instead of overflowing;
                // the gap shrinks a little too, box size matters more.
                const gap = 8.0;
                final boxWidth =
                    ((constraints.maxWidth - gap * (_otpLength - 1)) /
                            _otpLength)
                        .clamp(32.0, 44.0);
                return Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  textDirection: TextDirection.ltr,
                  children: [
                    for (var i = 0; i < _otpLength; i++) ...[
                      if (i > 0) const SizedBox(width: gap),
                      _OtpBox(
                        width: boxWidth,
                        char: i < text.length ? text[i] : '',
                        active: widget.enabled && i == text.length,
                        error: widget.error,
                      ),
                    ],
                  ],
                );
              },
            ),
          ),
          Positioned.fill(
            child: Opacity(
              opacity: 0,
              child: TextField(
                controller: widget.controller,
                focusNode: _focusNode,
                enabled: widget.enabled,
                showCursor: false,
                keyboardType: TextInputType.number,
                textDirection: TextDirection.ltr,
                maxLength: _otpLength,
                autofillHints: const [AutofillHints.oneTimeCode],
                inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                decoration: const InputDecoration(
                  counterText: '',
                  border: InputBorder.none,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _OtpBox extends StatelessWidget {
  const _OtpBox({
    required this.width,
    required this.char,
    required this.active,
    required this.error,
  });

  final double width;
  final String char;
  final bool active;
  final bool error;

  @override
  Widget build(BuildContext context) {
    final filled = char.isNotEmpty;
    final borderColor = error
        ? SsColors.of(context).danger
        : active || filled
        ? SsColors.of(context).primary
        : SsColors.of(context).line;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 150),
      width: width,
      height: 52,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: SsColors.of(context).canvas,
        border: Border.all(color: borderColor, width: active ? 2 : 1),
      ),
      child: Text(
        char,
        style: TextStyle(
          fontSize: 22,
          fontWeight: FontWeight.w600,
          color: SsColors.of(context).ink,
        ),
      ),
    );
  }
}
