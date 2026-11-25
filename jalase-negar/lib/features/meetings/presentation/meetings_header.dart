import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/theme.dart';
import '../application/meetings_search_controller.dart';

/// The shell header's search icon action; switches the whole header (the
/// app shell, not this screen) into the search field.
class MeetingsSearchButton extends ConsumerWidget {
  const MeetingsSearchButton({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return IconButton(
      icon: const Icon(Icons.search),
      tooltip: 'جست‌وجو',
      onPressed: () => ref.read(meetingsSearchProvider.notifier).open(),
    );
  }
}

/// The shell header's filter icon action; a status filter, independent of
/// the search box.
class MeetingsFilterButton extends ConsumerWidget {
  const MeetingsFilterButton({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final filter = ref.watch(meetingsSearchProvider.select((s) => s.filter));
    final active = filter != MeetingFilter.all;
    return PopupMenuButton<MeetingFilter>(
      tooltip: active ? 'فیلتر: ${filter.label}' : 'فیلتر جلسه‌ها',
      position: PopupMenuPosition.under,
      shape: RoundedRectangleBorder(
        side: BorderSide(color: SsColors.of(context).line),
      ),
      initialValue: filter,
      onSelected: (f) => ref.read(meetingsSearchProvider.notifier).setFilter(f),
      itemBuilder: (context) => [
        for (final f in MeetingFilter.values)
          PopupMenuItem(
            value: f,
            height: 40,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  f == filter ? Icons.check : null,
                  size: 18,
                  color: SsColors.of(context).primary,
                ),
                const SizedBox(width: 10),
                Text(f.label, style: Theme.of(context).textTheme.labelMedium),
              ],
            ),
          ),
      ],
      icon: Icon(
        Icons.filter_alt_outlined,
        color: active ? SsColors.of(context).primary : null,
      ),
    );
  }
}

/// Closes the header's search field, back to the shell's normal header.
class MeetingsSearchCloseButton extends ConsumerWidget {
  const MeetingsSearchCloseButton({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return IconButton(
      icon: const Icon(Icons.close),
      tooltip: 'بستن جست‌وجو',
      onPressed: () => ref.read(meetingsSearchProvider.notifier).close(),
    );
  }
}

/// The shell header's title once search is active: a plain text field that
/// fills the header, wired straight to [meetingsSearchProvider].
class MeetingsSearchField extends ConsumerStatefulWidget {
  const MeetingsSearchField({super.key});

  @override
  ConsumerState<MeetingsSearchField> createState() =>
      _MeetingsSearchFieldState();
}

class _MeetingsSearchFieldState extends ConsumerState<MeetingsSearchField> {
  late final _controller = TextEditingController(
    text: ref.read(meetingsSearchProvider).query,
  );
  final _focus = FocusNode();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _focus.requestFocus();
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    _focus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // The query can also change from outside this field (closing search, or
    // "پاک کردن فیلترها" in the no-results view); keep the text in sync.
    ref.listen(meetingsSearchProvider.select((s) => s.query), (prev, next) {
      if (next != _controller.text) {
        _controller.value = TextEditingValue(text: next);
      }
    });
    return TextField(
      controller: _controller,
      focusNode: _focus,
      textInputAction: TextInputAction.search,
      style: Theme.of(context).textTheme.titleMedium,
      decoration: InputDecoration(
        isDense: true,
        isCollapsed: true,
        filled: false,
        // The theme's InputDecorationTheme draws every field as a bordered,
        // filled box; override each border (not just `border`, which the
        // theme's own enabledBorder/focusedBorder would still shadow) so
        // this field reads as the header itself, not a box inside it.
        border: InputBorder.none,
        enabledBorder: InputBorder.none,
        focusedBorder: InputBorder.none,
        disabledBorder: InputBorder.none,
        errorBorder: InputBorder.none,
        focusedErrorBorder: InputBorder.none,
        hintText: 'جست‌وجو در عنوان، تاریخ و متن جلسه',
        hintStyle: TextStyle(color: SsColors.of(context).neutral),
      ),
      onChanged: (v) => ref.read(meetingsSearchProvider.notifier).setQuery(v),
    );
  }
}
