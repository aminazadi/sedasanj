import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_widgets.dart';
import '../../../core/utils/format.dart';
import 'intro_art.dart';
import 'intro_progress.dart';

class IntroSlide {
  const IntroSlide(this.scene, this.title, this.body);

  final IntroScene scene;
  final String title;
  final String body;
}

const kIntroSlides = <IntroSlide>[
  IntroSlide(
    IntroScene.welcome,
    'به جلسه‌نگار خوش آمدید',
    'جلسه را ضبط کنید، متن فارسی آن را همان لحظه روی گوشی ببینید و در صورت '
        'تمایل برای ساخت صورت‌جلسه به صداسنج بفرستید.',
  ),
  IntroSlide(
    IntroScene.models,
    'یک بار مدل‌ها را نصب کنید',
    'در «دانلود مدل‌ها» مدل تشخیص گفتار و یک مدل شنوا را دانلود کنید. بعد از '
        'آن رونویسی فارسی روی خود گوشی و بدون اینترنت انجام می‌شود.',
  ),
  IntroSlide(
    IntroScene.record,
    'ضبط با یک لمس',
    'دکمهٔ ضبط پایین صفحه را بزنید و دسترسی میکروفون را بدهید. بعد از شمارش '
        'معکوس و بوق پایانی صحبت کنید؛ هر زمان خواستید ضبط را متوقف کنید و '
        'با «پایان و ذخیره» تمام کنید.',
  ),
  IntroSlide(
    IntroScene.liveText,
    'متن زنده هنگام ضبط',
    'پیش از شروع، «متن زنده» را از آیکون زیرنویس روشن کنید. متن کمی بعد از '
        'هر مکث در صفحهٔ ضبط ظاهر می‌شود و همراه جلسه ذخیره خواهد شد.',
  ),
  IntroSlide(
    IntroScene.send,
    'ارسال و ساخت صورت‌جلسه',
    'با اتصال به پنل صداسنج (اسکن QR در تنظیمات)، متن و صدای جلسه ارسال '
        'می‌شود و صورت‌جلسه را در پنل می‌بینید. اتصال اختیاری است و ضبط '
        'بدون آن هم کار می‌کند.',
  ),
  IntroSlide(
    IntroScene.ready,
    'برای شروع آماده‌اید',
    'جلسه‌های ذخیره‌شده را از تب «جلسات» پیدا کنید، صدا را پخش کنید و متن را '
        'بخوانید یا کپی کنید. این معرفی را هر زمان از تنظیمات دوباره ببینید.',
  ),
];

/// First-run slides. [replay] reopens them from settings without touching the
/// "already seen" flag.
class IntroScreen extends ConsumerStatefulWidget {
  const IntroScreen({super.key, this.replay = false});

  final bool replay;

  @override
  ConsumerState<IntroScreen> createState() => _IntroScreenState();
}

class _IntroScreenState extends ConsumerState<IntroScreen>
    with SingleTickerProviderStateMixin {
  final _pages = PageController();
  late final AnimationController _loop;
  int _index = 0;
  bool _leaving = false;

  @override
  void initState() {
    super.initState();
    _loop = AnimationController(vsync: this, duration: kIntroArtLoop);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (MediaQuery.disableAnimationsOf(context)) {
      _loop.stop();
    } else if (!_loop.isAnimating) {
      _loop.repeat();
    }
  }

  @override
  void dispose() {
    _pages.dispose();
    _loop.dispose();
    super.dispose();
  }

  bool get _last => _index == kIntroSlides.length - 1;

  void _go(int page) => _pages.animateToPage(
    page,
    duration: const Duration(milliseconds: 380),
    curve: Curves.easeOutCubic,
  );

  Future<void> _finish() async {
    if (_leaving) return;
    setState(() => _leaving = true);
    if (!widget.replay) {
      try {
        await ref.read(introProgressProvider.notifier).markSeen();
      } catch (e) {
        // Never trap the user on the slides; they simply appear once more.
        debugPrint('JN-INTRO-0001: intro flag not saved ($e).');
      }
    }
    if (mounted) context.go(widget.replay ? '/settings' : '/');
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final still = MediaQuery.disableAnimationsOf(context);

    return PopScope(
      canPop: _index == 0,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _go(_index - 1);
      },
      child: Scaffold(
        body: SsDots(
          fadeToEnd: false,
          child: SafeArea(
            child: Column(
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(8, 4, 16, 0),
                  child: Row(
                    children: [
                      TextButton(
                        onPressed: _leaving ? null : _finish,
                        child: Text(widget.replay ? 'بستن' : 'رد کردن'),
                      ),
                      const Spacer(),
                      Text(
                        '${toPersianDigits('${_index + 1}')} از '
                        '${toPersianDigits('${kIntroSlides.length}')}',
                        style: theme.textTheme.bodySmall,
                      ),
                    ],
                  ),
                ),
                Expanded(
                  child: PageView.builder(
                    controller: _pages,
                    itemCount: kIntroSlides.length,
                    onPageChanged: (i) => setState(() => _index = i),
                    itemBuilder: (context, i) => _SlidePage(
                      slide: kIntroSlides[i],
                      animation: _loop,
                      still: still,
                    ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(24, 8, 24, 20),
                  child: Column(
                    children: [
                      _Segments(count: kIntroSlides.length, index: _index),
                      // Pages are swiped; only the last one needs an action.
                      AnimatedSize(
                        duration: const Duration(milliseconds: 260),
                        curve: Curves.easeOutCubic,
                        alignment: Alignment.topCenter,
                        child: _last
                            ? Padding(
                                padding: const EdgeInsets.only(top: 18),
                                child: SizedBox(
                                  width: double.infinity,
                                  child: FilledButton(
                                    onPressed: _leaving ? null : _finish,
                                    child: const Text('شروع کنیم'),
                                  ),
                                ),
                              )
                            : const SizedBox(width: double.infinity),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _SlidePage extends StatelessWidget {
  const _SlidePage({
    required this.slide,
    required this.animation,
    required this.still,
  });

  final IntroSlide slide;
  final Animation<double> animation;
  final bool still;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 24),
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: constraints.maxHeight),
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 440),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  IntroArt(
                    scene: slide.scene,
                    animation: animation,
                    still: still,
                  ),
                  const SizedBox(height: 20),
                  Semantics(
                    header: true,
                    child: Text(
                      slide.title,
                      textAlign: TextAlign.center,
                      style: theme.textTheme.headlineSmall,
                    ),
                  ),
                  const SizedBox(height: 12),
                  Text(
                    slide.body,
                    textAlign: TextAlign.center,
                    style: theme.textTheme.bodyLarge,
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Square progress segments; the current one is wider, like the panel's
/// stepper.
class _Segments extends StatelessWidget {
  const _Segments({required this.count, required this.index});

  final int count;
  final int index;

  @override
  Widget build(BuildContext context) {
    return ExcludeSemantics(
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          for (var i = 0; i < count; i++)
            AnimatedContainer(
              duration: const Duration(milliseconds: 260),
              curve: Curves.easeOutCubic,
              margin: const EdgeInsets.symmetric(horizontal: 3),
              width: i == index ? 28 : 10,
              height: 4,
              color: i == index
                  ? SsColors.primary
                  : i < index
                  ? SsColors.accent
                  : SsColors.line,
            ),
        ],
      ),
    );
  }
}
