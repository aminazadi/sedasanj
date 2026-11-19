import 'package:flutter/material.dart';
import 'package:shamsi_date/shamsi_date.dart';

import '../../../app/theme.dart';
import '../../../core/utils/format.dart';

const _weekdayLetters = ['ش', 'ی', 'د', 'س', 'چ', 'پ', 'ج'];

/// Telegram-style "jump to date" calendar, in the Jalali calendar. Returns
/// the chosen day, or null if dismissed without a choice.
Future<Jalali?> showJalaliDatePicker(BuildContext context, {Jalali? initial}) {
  return showDialog<Jalali>(
    context: context,
    builder: (_) => _JalaliDatePickerDialog(initial: initial ?? Jalali.now()),
  );
}

class _JalaliDatePickerDialog extends StatefulWidget {
  const _JalaliDatePickerDialog({required this.initial});

  final Jalali initial;

  @override
  State<_JalaliDatePickerDialog> createState() =>
      _JalaliDatePickerDialogState();
}

class _JalaliDatePickerDialogState extends State<_JalaliDatePickerDialog> {
  late var _month = Jalali(widget.initial.year, widget.initial.month);
  late var _selected = Jalali(
    widget.initial.year,
    widget.initial.month,
    widget.initial.day,
  );

  void _changeMonth(int delta) =>
      setState(() => _month = _month.addMonths(delta));

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final now = Jalali.now();
    final today = Jalali(now.year, now.month, now.day);
    final daysInMonth = _month.monthLength;
    final leading = _month.weekDay - 1;

    return Dialog(
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 16, 12, 8),
        child: SizedBox(
          width: 312,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  IconButton(
                    icon: const Icon(Icons.chevron_left),
                    tooltip: 'ماه قبل',
                    onPressed: () => _changeMonth(-1),
                  ),
                  Expanded(
                    child: Center(
                      child: Text(
                        toPersianDigits(
                          '${_month.formatter.mN} ${_month.formatter.yyyy}',
                        ),
                        style: theme.textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.chevron_right),
                    tooltip: 'ماه بعد',
                    onPressed: () => _changeMonth(1),
                  ),
                ],
              ),
              Row(
                children: [
                  for (final l in _weekdayLetters)
                    Expanded(
                      child: Center(
                        child: Text(
                          l,
                          style: theme.textTheme.labelSmall?.copyWith(
                            color: SsColors.neutral,
                          ),
                        ),
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 4),
              GridView.builder(
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                padding: EdgeInsets.zero,
                gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                  crossAxisCount: 7,
                ),
                itemCount: leading + daysInMonth,
                itemBuilder: (context, i) {
                  if (i < leading) return const SizedBox.shrink();
                  final day = i - leading + 1;
                  final date = Jalali(_month.year, _month.month, day);
                  final isToday = date == today;
                  final isSelected = date == _selected;
                  return Padding(
                    padding: const EdgeInsets.all(2),
                    child: Material(
                      color: isSelected
                          ? SsColors.primary
                          : Colors.transparent,
                      shape: const CircleBorder(),
                      child: InkWell(
                        customBorder: const CircleBorder(),
                        onTap: () => setState(() => _selected = date),
                        child: Center(
                          child: Text(
                            toPersianDigits('$day'),
                            style: theme.textTheme.bodyMedium?.copyWith(
                              color: isSelected
                                  ? Colors.white
                                  : isToday
                                  ? SsColors.primary
                                  : SsColors.ink,
                              fontWeight: isToday || isSelected
                                  ? FontWeight.w700
                                  : FontWeight.w400,
                            ),
                          ),
                        ),
                      ),
                    ),
                  );
                },
              ),
              const SizedBox(height: 4),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('انصراف'),
                  ),
                  FilledButton(
                    onPressed: () => Navigator.pop(context, _selected),
                    child: const Text('برو به این روز'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
