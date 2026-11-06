import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../app/widgets/ss_widgets.dart';
import '../../core/platform/app_permissions.dart';

class PermissionInfo {
  const PermissionInfo(this.title, this.why);

  final String title;
  final String why;
}

const kPermissionInfo = <AppPermission, PermissionInfo>{
  AppPermission.microphone: PermissionInfo(
    'میکروفون',
    'برای ضبط صدای جلسه. بدون آن ضبط شروع نمی‌شود.',
  ),
  AppPermission.notifications: PermissionInfo(
    'اعلان',
    'اعلان «در حال ضبط» نشان می‌دهد ضبط ادامه دارد و اندروید آن را نمی‌بندد.',
  ),
  AppPermission.background: PermissionInfo(
    'ادامه در پس‌زمینه',
    'با این اجازه، ضبط و متن زنده با خاموش شدن صفحه یا رفتن به برنامهٔ '
        'دیگر ادامه می‌یابد و گوشی برنامه را برای صرفه‌جویی در باتری نمی‌بندد.',
  ),
};

/// Shown once after the intro slides: asks for everything the recording
/// needs in one place. Every item can be skipped; recording asks again for
/// what is still missing.
class PermissionsScreen extends StatefulWidget {
  const PermissionsScreen({
    super.key,
    this.gateway = const SystemPermissionGateway(),
    this.onDone,
  });

  final PermissionGateway gateway;

  /// Called instead of navigating home (tests).
  final VoidCallback? onDone;

  @override
  State<PermissionsScreen> createState() => _PermissionsScreenState();
}

class _PermissionsScreenState extends State<PermissionsScreen> {
  final Map<AppPermission, bool> _granted = {};
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    for (final p in widget.gateway.supported) {
      bool ok;
      try {
        ok = await widget.gateway.isGranted(p);
      } catch (e) {
        debugPrint('JN-PERM-0001: could not read $p ($e).');
        ok = false;
      }
      if (!mounted) return;
      setState(() => _granted[p] = ok);
    }
  }

  Future<void> _askAll() async {
    if (_busy) return;
    setState(() => _busy = true);
    for (final p in widget.gateway.supported) {
      if (_granted[p] == true) continue;
      bool ok;
      try {
        ok = await widget.gateway.request(p);
      } catch (e) {
        debugPrint('JN-PERM-0002: request for $p failed ($e).');
        ok = false;
      }
      if (!mounted) return;
      setState(() => _granted[p] = ok);
    }
    if (mounted) setState(() => _busy = false);
  }

  void _done() {
    if (widget.onDone != null) {
      widget.onDone!();
    } else {
      context.go('/');
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final items = widget.gateway.supported;
    final allGranted = items.every((p) => _granted[p] == true);
    return Directionality(
      textDirection: TextDirection.rtl,
      child: Scaffold(
        body: SsDots(
          fadeToEnd: false,
          child: SafeArea(
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 440),
                child: ListView(
                  padding: const EdgeInsets.all(24),
                  children: [
                    Semantics(
                      header: true,
                      child: Text(
                        'اجازه‌های لازم برای ضبط',
                        style: theme.textTheme.headlineSmall,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'یک بار همه را بدهید تا هنگام ضبط چیزی متوقف نشود. '
                      'هر کدام را می‌توانید بعداً از تنظیمات گوشی تغییر دهید.',
                      style: theme.textTheme.bodyLarge,
                    ),
                    const SizedBox(height: 16),
                    for (final p in items)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: SsCard(
                          child: Row(
                            children: [
                              Icon(
                                _granted[p] == true
                                    ? Icons.check_circle
                                    : Icons.radio_button_unchecked,
                                color: _granted[p] == true
                                    ? theme.colorScheme.primary
                                    : theme.colorScheme.outline,
                              ),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      kPermissionInfo[p]!.title,
                                      style: theme.textTheme.titleMedium,
                                    ),
                                    Text(
                                      kPermissionInfo[p]!.why,
                                      style: theme.textTheme.bodyMedium,
                                    ),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    const SizedBox(height: 12),
                    if (!allGranted)
                      FilledButton(
                        onPressed: _busy ? null : _askAll,
                        child: const Text('اجازه دادن'),
                      ),
                    const SizedBox(height: 8),
                    allGranted
                        ? FilledButton(
                            onPressed: _done,
                            child: const Text('ادامه'),
                          )
                        : TextButton(
                            onPressed: _busy ? null : _done,
                            child: const Text('فعلاً رد می‌کنم'),
                          ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
