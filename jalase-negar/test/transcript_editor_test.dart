import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/app/widgets/ss_toast.dart';
import 'package:jalase_negar/features/meetings/application/meeting_providers.dart';
import 'package:jalase_negar/features/meetings/presentation/transcript_editor.dart';

const _ok = TranscriptSave(TranscriptSaveResult.saved);
const _failed = TranscriptSave(TranscriptSaveResult.failed);

Widget _host({
  required String text,
  required Future<TranscriptSave> Function(String, {required bool settle})
  onSave,
  bool readOnly = false,
  String? notice,
  String? noticeActionLabel,
  VoidCallback? onNoticeAction,
  VoidCallback? onOpenEditor,
}) {
  return MaterialApp(
    builder: (context, child) => Directionality(
      textDirection: TextDirection.rtl,
      child: SsToastHost(child: child!),
    ),
    home: Builder(
      builder: (context) => Scaffold(
        body: onOpenEditor == null
            ? ListView(
                children: [
                  TranscriptEditor(
                    savedText: text,
                    onSave: onSave,
                    readOnly: readOnly,
                    notice: notice,
                    noticeActionLabel: noticeActionLabel,
                    onNoticeAction: onNoticeAction,
                  ),
                ],
              )
            : Center(
                child: TextButton(
                  onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => Scaffold(
                        body: ListView(
                          children: [
                            TranscriptEditor(savedText: text, onSave: onSave),
                          ],
                        ),
                      ),
                    ),
                  ),
                  child: const Text('open'),
                ),
              ),
      ),
    ),
  );
}

// The find bar's fields come before the main one while it is open.
Finder get _field => find.byType(TextField).last;
String get _value =>
    (find.byType(TextField).evaluate().last.widget as TextField)
        .controller!
        .text;

Future<void> _type(WidgetTester tester, String text) async {
  await tester.enterText(_field, text);
  await tester.pump();
}

Future<void> _tap(WidgetTester tester, String tooltip) async {
  await tester.tap(find.byTooltip(tooltip));
  await tester.pump();
}

bool _enabled(String tooltip) {
  final button = find
      .ancestor(of: find.byTooltip(tooltip), matching: find.byType(IconButton))
      .evaluate()
      .map((e) => e.widget as IconButton)
      .followedBy(
        find
            .byWidgetPredicate((w) => w is IconButton && w.tooltip == tooltip)
            .evaluate()
            .map((e) => e.widget as IconButton),
      )
      .first;
  return button.onPressed != null;
}

void main() {
  testWidgets('shows the saved text and starts clean', (tester) async {
    await tester.pumpWidget(
      _host(text: 'یک\nدو', onSave: (_, {required settle}) async => _ok),
    );
    expect(_value, 'یک\nدو');
    expect(find.text('ذخیره شد'), findsOneWidget);
    expect(find.text('ذخیره ویرایش'), findsNothing);
  });

  testWidgets('typing is saved by itself with the cleaned text', (
    tester,
  ) async {
    final saves = <(String, bool)>[];
    await tester.pumpWidget(
      _host(
        text: 'یک\nدو',
        onSave: (text, {required settle}) async {
          saves.add((text, settle));
          return _ok;
        },
      ),
    );
    await _type(tester, '  یک  \n\n\nدوم \n');
    expect(find.text('در حال ذخیره…'), findsOneWidget);
    await tester.pump(const Duration(milliseconds: 1000));
    expect(saves, isEmpty);

    await tester.pump(const Duration(milliseconds: 400));
    expect(saves, [('یک\nدوم', false)]);
    expect(find.text('ذخیره شد'), findsOneWidget);
    // The field keeps what was typed, e.g. the new line after the last one.
    expect(_value, '  یک  \n\n\nدوم \n');
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('every pause in typing restarts the wait', (tester) async {
    var saves = 0;
    await tester.pumpWidget(
      _host(
        text: 'یک',
        onSave: (_, {required settle}) async {
          saves++;
          return _ok;
        },
      ),
    );
    await _type(tester, 'یک ا');
    await tester.pump(const Duration(milliseconds: 1000));
    await _type(tester, 'یک اب');
    await tester.pump(const Duration(milliseconds: 1000));
    expect(saves, 0);
    await tester.pump(const Duration(milliseconds: 300));
    expect(saves, 1);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('a long pause also settles the edit with the server', (
    tester,
  ) async {
    final settles = <bool>[];
    await tester.pumpWidget(
      _host(
        text: 'یک',
        onSave: (_, {required settle}) async {
          settles.add(settle);
          return settle
              ? const TranscriptSave(TranscriptSaveResult.synced)
              : _ok;
        },
      ),
    );
    await _type(tester, 'یکی');
    await tester.pump(const Duration(seconds: 2));
    expect(settles, [false]);
    await tester.pump(const Duration(seconds: 60));
    await tester.pump();
    expect(settles, [false, true]);
    expect(find.text('ویرایش برای صداسنج ارسال شد'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('going to the background settles pending edits', (tester) async {
    final settles = <bool>[];
    await tester.pumpWidget(
      _host(
        text: 'یک',
        onSave: (_, {required settle}) async {
          settles.add(settle);
          return _ok;
        },
      ),
    );
    await _type(tester, 'یکی');
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    await tester.pump();
    expect(settles, [true]);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('typing during a save is kept and saved next', (tester) async {
    final first = Completer<TranscriptSave>();
    final texts = <String>[];
    await tester.pumpWidget(
      _host(
        text: 'یک',
        onSave: (text, {required settle}) {
          texts.add(text);
          return texts.length == 1 ? first.future : Future.value(_ok);
        },
      ),
    );
    await _type(tester, 'یکی');
    await tester.pump(const Duration(milliseconds: 1300));
    expect(texts, ['یکی']);

    await _type(tester, 'یکیم');
    first.complete(_ok);
    await tester.pump();
    expect(_value, 'یکیم');
    expect(find.text('در حال ذخیره…'), findsOneWidget);
    await tester.pump(const Duration(milliseconds: 1300));
    expect(texts, ['یکی', 'یکیم']);
    expect(find.text('ذخیره شد'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  for (final (result, message) in [
    (TranscriptSaveResult.synced, 'ویرایش برای صداسنج ارسال شد'),
    (
      TranscriptSaveResult.savedOnDevice,
      'ویرایش روی گوشی ذخیره شد؛ ارسال به صداسنج انجام نشد',
    ),
  ]) {
    testWidgets('tells what happened to the server copy: ${result.name}', (
      tester,
    ) async {
      await tester.pumpWidget(
        _host(
          text: 'یک',
          onSave: (_, {required settle}) async =>
              settle ? TranscriptSave(result) : _ok,
        ),
      );
      await _type(tester, 'یکی');
      await tester.pump(const Duration(seconds: 62));
      await tester.pump();

      expect(find.text(message), findsOneWidget);
      expect(_value, 'یکی');
      expect(find.text('ذخیره شد'), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
    });
  }

  testWidgets('the notice offers its action', (tester) async {
    var taps = 0;
    await tester.pumpWidget(
      _host(
        text: 'یک',
        notice: 'هنوز نرسیده',
        noticeActionLabel: 'ارسال دوباره',
        onNoticeAction: () => taps++,
        onSave: (_, {required settle}) async => _ok,
      ),
    );
    await tester.tap(find.text('ارسال دوباره'));
    expect(taps, 1);
  });

  testWidgets('a failed save keeps the edits and offers a retry', (
    tester,
  ) async {
    var fail = true;
    final settles = <bool>[];
    await tester.pumpWidget(
      _host(
        text: 'یک',
        onSave: (_, {required settle}) async {
          settles.add(settle);
          return fail ? _failed : _ok;
        },
      ),
    );
    await _type(tester, 'یکی');
    await tester.pump(const Duration(milliseconds: 1300));

    expect(_value, 'یکی');
    expect(find.text('ذخیره نشد؛ دوباره امتحان کنید'), findsOneWidget);
    expect(find.text('ذخیره نشد؛ تلاش دوباره'), findsOneWidget);
    await tester.pump(const Duration(seconds: 10));
    expect(settles, [false], reason: 'a failure is not retried in a loop');

    fail = false;
    await tester.tap(find.text('ذخیره نشد؛ تلاش دوباره'));
    await tester.pump();
    expect(settles, [false, true]);
    expect(find.text('ذخیره شد'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('undo and redo follow edits', (tester) async {
    await tester.pumpWidget(
      _host(text: 'یک', onSave: (_, {required settle}) async => _ok),
    );
    expect(_enabled('واگرد'), isFalse);
    await _type(tester, 'یکی');
    await tester.pump(const Duration(seconds: 1));
    expect(_enabled('واگرد'), isTrue);

    await _tap(tester, 'واگرد');
    expect(_value, 'یک');
    expect(_enabled('بازگرد'), isTrue);
    await _tap(tester, 'بازگرد');
    expect(_value, 'یکی');
  });

  testWidgets('find counts matches and replace all rewrites them', (
    tester,
  ) async {
    await tester.pumpWidget(
      _host(
        text: 'سلام دنیا\nسلام جلسه\nخداحافظ',
        onSave: (_, {required settle}) async => _ok,
      ),
    );
    await _tap(tester, 'جستجو و جایگزینی');
    await tester.enterText(find.byType(TextField).at(0), 'سلام');
    await tester.pump();
    expect(find.text('۱ از ۲'), findsOneWidget);

    await _tap(tester, 'مورد بعدی');
    expect(find.text('۲ از ۲'), findsOneWidget);
    await _tap(tester, 'مورد بعدی');
    expect(find.text('۱ از ۲'), findsOneWidget);

    await tester.enterText(find.byType(TextField).at(1), 'درود');
    await tester.pump();
    await tester.tap(find.text('همه'));
    await tester.pumpAndSettle();

    expect(_value, 'درود دنیا\nدرود جلسه\nخداحافظ');
    expect(find.text('۲ مورد جایگزین شد'), findsOneWidget);
    expect(find.text('در حال ذخیره…'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('find without matches disables replacing', (tester) async {
    await tester.pumpWidget(
      _host(text: 'یک', onSave: (_, {required settle}) async => _ok),
    );
    await _tap(tester, 'جستجو و جایگزینی');
    await tester.enterText(find.byType(TextField).at(0), 'نیست');
    await tester.pump();

    expect(find.text('موردی نیست'), findsOneWidget);
    expect(
      tester
          .widget<OutlinedButton>(
            find.ancestor(
              of: find.text('همه'),
              matching: find.byType(OutlinedButton),
            ),
          )
          .onPressed,
      isNull,
    );
  });

  testWidgets('tidy unifies Arabic letters and spaces and drops blank lines', (
    tester,
  ) async {
    await tester.pumpWidget(
      _host(text: 'يك', onSave: (_, {required settle}) async => _ok),
    );
    await _type(tester, '  كتاب   جلسه \n\n  يك  ');
    await _tap(tester, 'یکدست‌سازی نویسه‌ها و فاصله‌ها');
    expect(_value, 'کتاب جلسه\nیک');
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('delete line and join lines work on the cursor line', (
    tester,
  ) async {
    await tester.pumpWidget(
      _host(text: 'یک\nدو\nسه', onSave: (_, {required settle}) async => _ok),
    );
    final field = tester.widget<TextField>(_field);

    field.controller!.selection = const TextSelection.collapsed(offset: 5);
    await tester.pump();
    await _tap(tester, 'حذف خط');
    expect(_value, 'یک\nسه');

    field.controller!.selection = const TextSelection.collapsed(offset: 1);
    await tester.pump();
    await _tap(tester, 'ادغام با خط بعد');
    expect(_value, 'یک سه');

    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('deleting the last line removes its line break', (tester) async {
    await tester.pumpWidget(
      _host(text: 'یک\nدو', onSave: (_, {required settle}) async => _ok),
    );
    final field = tester.widget<TextField>(_field);
    field.controller!.selection = const TextSelection.collapsed(offset: 5);
    await tester.pump();
    await _tap(tester, 'حذف خط');
    expect(_value, 'یک');
  });

  testWidgets('read-only mode shows the text and blocks every edit', (
    tester,
  ) async {
    await tester.pumpWidget(
      _host(
        text: 'یک\nدو',
        readOnly: true,
        notice: 'در حال ارسال',
        onSave: (_, {required settle}) async => _ok,
      ),
    );
    expect(find.text('در حال ارسال'), findsOneWidget);
    expect(tester.widget<TextField>(_field).readOnly, isTrue);
    for (final tooltip in [
      'حذف خط',
      'ادغام با خط بعد',
      'یکدست‌سازی نویسه‌ها و فاصله‌ها',
    ]) {
      expect(_enabled(tooltip), isFalse);
    }
    expect(_enabled('کپی'), isTrue);
  });

  Future<NavigatorState> openEditor(
    WidgetTester tester,
    Future<TranscriptSave> Function(String, {required bool settle}) onSave,
  ) async {
    await tester.pumpWidget(
      _host(text: 'یک', onOpenEditor: () {}, onSave: onSave),
    );
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    return tester.state<NavigatorState>(find.byType(Navigator));
  }

  testWidgets('leaving with pending edits saves and sends them first', (
    tester,
  ) async {
    final saves = <(String, bool)>[];
    final navigator = await openEditor(tester, (text, {required settle}) async {
      saves.add((text, settle));
      return _ok;
    });
    await _type(tester, 'یکی');

    await navigator.maybePop();
    await tester.pumpAndSettle();

    expect(saves, [('یکی', true)]);
    expect(find.text('open'), findsOneWidget);
  });

  testWidgets('leaving stays on the page when the save fails', (tester) async {
    final navigator = await openEditor(
      tester,
      (_, {required settle}) async => _failed,
    );
    await _type(tester, 'یکی');

    await navigator.maybePop();
    await tester.pumpAndSettle();

    expect(find.text('open'), findsNothing);
    expect(_value, 'یکی');
    expect(find.text('ذخیره نشد؛ تلاش دوباره'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('a clean editor leaves at once without saving', (tester) async {
    var saves = 0;
    final navigator = await openEditor(tester, (_, {required settle}) async {
      saves++;
      return _ok;
    });
    await navigator.maybePop();
    await tester.pumpAndSettle();
    expect(saves, 0);
    expect(find.text('open'), findsOneWidget);
  });

  testWidgets('an edit saved without a settle is settled when leaving', (
    tester,
  ) async {
    final settles = <bool>[];
    final navigator = await openEditor(tester, (_, {required settle}) async {
      settles.add(settle);
      return _ok;
    });
    await _type(tester, 'یکی');
    await tester.pump(const Duration(milliseconds: 1300));
    expect(settles, [false]);

    await navigator.maybePop();
    await tester.pumpAndSettle();
    expect(settles, [false, true]);
    expect(find.text('open'), findsOneWidget);
  });

  testWidgets('a new stored text replaces a clean editor but not an edit', (
    tester,
  ) async {
    final stored = ValueNotifier('یک');
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ValueListenableBuilder<String>(
            valueListenable: stored,
            builder: (context, text, _) => ListView(
              children: [
                TranscriptEditor(
                  savedText: text,
                  onSave: (_, {required settle}) async => _ok,
                ),
              ],
            ),
          ),
        ),
      ),
    );

    stored.value = 'یک\nدو';
    await tester.pump();
    expect(_value, 'یک\nدو');

    await _type(tester, 'نوشتهٔ من');
    stored.value = 'یک\nدو\nسه';
    await tester.pump();
    expect(_value, 'نوشتهٔ من');
    expect(find.text('در حال ذخیره…'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
