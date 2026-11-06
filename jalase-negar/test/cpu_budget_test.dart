import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/app/theme.dart';
import 'package:jalase_negar/core/platform/cpu_budget.dart';
import 'package:jalase_negar/features/settings/presentation/cpu_limit_card.dart';

class _Fixed extends CpuBudgetNotifier {
  _Fixed(this.initial);
  final int initial;
  int? chosen;

  @override
  Future<CpuBudget> build() async => CpuBudget.of(initial, 8);

  @override
  Future<void> setCores(int cores) async {
    chosen = clampCpuCores(cores, 8);
    state = AsyncData(CpuBudget(chosen!));
  }
}

void main() {
  test('the limit is half the cores and never below one', () {
    expect(maxCpuCores(8), 4);
    expect(maxCpuCores(6), 3);
    expect(maxCpuCores(2), 1);
    expect(maxCpuCores(1), 1);
  });

  test('the default keeps the earlier thread counts', () {
    expect(defaultCpuCores(8), 2);
    expect(defaultCpuCores(2), 1);
    final budget = CpuBudget.of(null, 8);
    expect(budget.recognitionThreads, 2);
    expect(budget.liveSpeakerThreads, 1);
  });

  test('a stored value is kept inside 1..max', () {
    expect(clampCpuCores(99, 8), 4);
    expect(clampCpuCores(0, 8), 1);
    expect(clampCpuCores(-3, 8), 1);
    expect(clampCpuCores(3, 8), 3);
  });

  test('each kind of work follows the budget', () {
    const b = CpuBudget(4);
    expect(b.recognitionThreads, 4);
    expect(b.liveSpeakerThreads, 2);
    expect(b.analysisThreads, 4);
    expect(const CpuBudget(1).liveSpeakerThreads, 1);
  });

  testWidgets('the slider stops at half of the cores', (tester) async {
    final notifier = _Fixed(2);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [cpuBudgetProvider.overrideWith(() => notifier)],
        child: MaterialApp(
          theme: buildAppTheme(),
          home: const Directionality(
            textDirection: TextDirection.rtl,
            child: Scaffold(body: CpuLimitCard(processors: 8)),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final slider = tester.widget<Slider>(find.byType(Slider));
    expect(slider.min, 1);
    expect(slider.max, 4);
    expect(slider.value, 2);
    slider.onChanged!(9);
    await tester.pump();
    expect(notifier.chosen, 4);
  });
}
