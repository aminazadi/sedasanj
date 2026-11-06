import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_toast.dart';
import '../../../core/asr/asr_common.dart';
import '../../../core/utils/format.dart';
import '../application/meeting_providers.dart';
import '../data/transcript_edit.dart';

/// Editable meeting text.
///
/// Edits are saved automatically. The text is plain: one line per transcript segment, exactly what the
/// SedaSanj panel shows, so every tool here (find and replace, line delete and
/// join, character clean-up, undo) produces text the panel can display. Rich
/// formatting would be lost on the way to the panel, so there is none.
class TranscriptEditor extends StatefulWidget {
  const TranscriptEditor({
    super.key,
    required this.savedText,
    required this.onSave,
    this.readOnly = false,
    this.notice,
    this.noticeActionLabel,
    this.onNoticeAction,
    this.statusDestination,
  });

  /// The text as stored; the editor is dirty when it differs from it.
  final String savedText;

  /// Stores [text] (already in saved form) and reports what happened.
  /// [settle] is set once typing has paused for long, or the editor is being
  /// left: only then does an edit go on to SedaSanj, which rebuilds the
  /// minutes from it each time.
  final Future<TranscriptSave> Function(String text, {required bool settle})
  onSave;

  /// Shows the text without allowing edits (e.g. while it is being uploaded).
  final bool readOnly;

  /// Explains a limit or consequence of editing, above the toolbar.
  final String? notice;

  /// A button under the notice (e.g. to send an edit again).
  final String? noticeActionLabel;
  final VoidCallback? onNoticeAction;
  final ValueNotifier<Widget?>? statusDestination;

  @override
  State<TranscriptEditor> createState() => TranscriptEditorState();
}

class TranscriptEditorState extends State<TranscriptEditor>
    with WidgetsBindingObserver {
  late final _TranscriptController _text;
  final _focus = FocusNode();
  final _fieldKey = GlobalKey();
  final _find = TextEditingController();
  final _replace = TextEditingController();
  final _findFocus = FocusNode();

  // Own undo history: the framework's only records while the field has focus,
  // but the find bar and the toolbar change the text from outside it.
  static const _maxHistory = 100;
  static const _typingGroup = Duration(milliseconds: 600);
  late final List<TextEditingValue> _history;
  int _at = 0;
  bool _replaying = false;
  bool _grouping = false;
  Timer? _typingPause;

  static const _autosaveAfter = Duration(milliseconds: 1200);
  static const _settleAfter = Duration(seconds: 60);
  Timer? _autosaveTimer;
  Timer? _settleTimer;
  Future<void>? _inFlight;

  /// The editor text as last stored (raw, before cleaning).
  late String _baseline;
  bool _dirty = false;
  bool _saving = false;
  bool _saveFailed = false;

  /// Stored on the phone but not yet offered to SedaSanj.
  bool _unsettled = false;
  bool _findOpen = false;

  @override
  void initState() {
    super.initState();
    _text = _TranscriptController(text: widget.savedText);
    _baseline = widget.savedText;
    _history = [_text.value];
    _lastSeen = _text.text;
    _text.addListener(_onControllerChanged);
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didUpdateWidget(TranscriptEditor oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.savedText == oldWidget.savedText) return;
    // A new stored text replaces the editor's only when nothing is in progress;
    // otherwise the user's edits stay and are compared with the new baseline.
    if (canonicalTranscriptText(_text.text) == widget.savedText) {
      // This is our own save coming back; keep the text as typed.
      _baseline = _text.text;
    } else {
      final wasClean = _text.text == _baseline;
      _baseline = widget.savedText;
      if (wasClean) _setText(widget.savedText);
    }
    _onTextChanged();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _autosaveTimer?.cancel();
    _settleTimer?.cancel();
    _text.dispose();
    _focus.dispose();
    _typingPause?.cancel();
    _find.dispose();
    _replace.dispose();
    _findFocus.dispose();
    super.dispose();
  }

  bool get _locked => widget.readOnly;

  void _record() {
    if (_replaying || _text.text == _history[_at].text) return;
    _history.removeRange(_at + 1, _history.length);
    if (_grouping) {
      _history[_at] = _text.value;
    } else {
      _history.add(_text.value);
      if (_history.length > _maxHistory) _history.removeAt(0);
      _at = _history.length - 1;
    }
    _grouping = true;
    _typingPause?.cancel();
    _typingPause = Timer(_typingGroup, () => _grouping = false);
  }

  void _travel(int delta) {
    final target = _at + delta;
    if (_locked || target < 0 || target >= _history.length) return;
    _typingPause?.cancel();
    _grouping = false;
    _at = target;
    _replaying = true;
    final saved = _history[target];
    _text.value = saved.copyWith(
      selection: TextSelection.collapsed(
        offset: saved.selection.baseOffset.clamp(0, saved.text.length),
      ),
      composing: TextRange.empty,
    );
    _replaying = false;
  }

  String _lastSeen = '';

  void _onControllerChanged() {
    // New typing ends a failed state; the next autosave tries again.
    if (_text.text != _lastSeen) {
      _lastSeen = _text.text;
      if (!_replaying) _saveFailed = false;
    }
    _onTextChanged();
  }

  void _onTextChanged() {
    _record();
    final matches = _findOpen ? _computeMatches() : const <int>[];
    _text.matches = matches;
    _text.matchLength = _find.text.length;
    if (_text.current >= matches.length) _text.current = matches.length - 1;
    if (_text.current < 0 && matches.isNotEmpty) _text.current = 0;
    _dirty = _text.text != _baseline;
    if (_dirty && !_locked && !_replaying && !_saveFailed) _scheduleSave();
    // Typing also updates the counters below the field, so always rebuild.
    if (mounted) setState(() {});
  }

  List<int> _computeMatches() => findTranscriptMatches(_text.text, _find.text);

  void _setText(String text, {int? caret}) {
    _grouping = false;
    final offset = (caret ?? _text.selection.baseOffset).clamp(0, text.length);
    _text.value = TextEditingValue(
      text: text,
      selection: TextSelection.collapsed(offset: offset),
    );
  }

  void _toast(String message) {
    if (!mounted) return;
    SsToastHost.show(context, message, queue: SsToastQueue.dismissCurrent);
  }

  // ---- saving --------------------------------------------------------------

  void _scheduleSave() {
    _autosaveTimer?.cancel();
    _autosaveTimer = Timer(_autosaveAfter, _save);
    _settleTimer?.cancel();
    _settleTimer = Timer(_settleAfter, () => _save(settle: true));
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) return;
    if (_dirty || _unsettled) _save(settle: true);
  }

  /// Stores the text (and, when [settle], offers it to SedaSanj). Saves never
  /// overlap, and typing goes on while one runs.
  Future<bool> _save({bool settle = false}) async {
    while (_inFlight != null) {
      await _inFlight;
    }
    if (!mounted) return false;
    _autosaveTimer?.cancel();
    if (settle) _settleTimer?.cancel();
    if (!_dirty && !(settle && _unsettled)) return true;

    final raw = _text.text;
    final canonical = canonicalTranscriptText(raw);
    final done = Completer<void>();
    _inFlight = done.future;
    setState(() => _saving = true);
    var save = const TranscriptSave(TranscriptSaveResult.failed);
    try {
      save = await widget.onSave(canonical, settle: settle);
    } catch (_) {
      // Reported below as a failed save.
    }
    _inFlight = null;
    done.complete();
    if (!mounted) return save.stored;
    _saving = false;
    _saveFailed = !save.stored;
    if (save.stored) {
      _baseline = raw;
      _unsettled = !settle;
    }
    _onTextChanged();
    switch (save.result) {
      case TranscriptSaveResult.synced:
        _toast('ویرایش برای صداسنج ارسال شد');
      case TranscriptSaveResult.savedOnDevice:
        _toast('ویرایش روی گوشی ذخیره شد؛ ارسال به صداسنج انجام نشد');
      case TranscriptSaveResult.failed:
        _toast('ذخیره نشد؛ دوباره امتحان کنید');
      case TranscriptSaveResult.saved:
        break;
    }
    return save.stored;
  }

  /// Back gesture with edits still pending: store and send them, then leave.
  Future<void> _flushAndLeave() async {
    if (await _save(settle: true) && mounted) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) Navigator.of(context).maybePop();
      });
    }
  }

  // ---- line tools ----------------------------------------------------------

  ({int start, int end}) _currentLine() {
    final text = _text.text;
    final at = _text.selection.isValid
        ? _text.selection.start.clamp(0, text.length)
        : text.length;
    final start = at == 0 ? 0 : text.lastIndexOf('\n', at - 1) + 1;
    final next = text.indexOf('\n', at);
    return (start: start, end: next < 0 ? text.length : next);
  }

  void _deleteLine() {
    if (_locked) return;
    final text = _text.text;
    final line = _currentLine();
    var from = line.start;
    var to = line.end;
    if (to < text.length) {
      to += 1;
    } else if (from > 0) {
      from -= 1;
    }
    _setText(
      text.replaceRange(from, to, ''),
      caret: math.min(from, line.start),
    );
    _focus.requestFocus();
  }

  void _joinWithNext() {
    if (_locked) return;
    final text = _text.text;
    final line = _currentLine();
    if (line.end >= text.length) {
      _toast('خط بعدی وجود ندارد');
      return;
    }
    final before = text.substring(0, line.end).trimRight();
    final after = text.substring(line.end + 1).trimLeft();
    _setText('$before $after', caret: before.length + 1);
    _focus.requestFocus();
  }

  void _tidy() {
    if (_locked) return;
    final tidy = canonicalTranscriptLines(
      _text.text,
    ).map((l) => normalizePersianAsrText(l).replaceAll('\n', ' ').trim());
    final next = tidy.where((l) => l.isNotEmpty).join('\n');
    if (next == _text.text) {
      _toast('متن از پیش یکدست است');
      return;
    }
    _setText(next);
    _toast('نویسه‌ها و فاصله‌ها یکدست شدند');
  }

  // ---- find and replace ----------------------------------------------------

  void _toggleFind() {
    setState(() => _findOpen = !_findOpen);
    if (_findOpen) {
      _findFocus.requestFocus();
      _onTextChanged();
    } else {
      _text.matches = const [];
      _text.current = -1;
      _focus.requestFocus();
    }
  }

  void _onQueryChanged() {
    _text.current = 0;
    _onTextChanged();
    if (_text.matches.isNotEmpty) _goTo(_nearestMatch());
  }

  int _nearestMatch() {
    final from = _text.selection.isValid ? _text.selection.start : 0;
    final index = _text.matches.indexWhere((m) => m >= from);
    return index < 0 ? 0 : index;
  }

  void _step(int delta) {
    final count = _text.matches.length;
    if (count == 0) return;
    _goTo((_text.current + delta) % count);
  }

  void _goTo(int index) {
    final at = _text.matches[index];
    _text.current = index;
    _text.selection = TextSelection.collapsed(offset: at);
    setState(() {});
    _reveal(at);
  }

  void _replaceCurrent() {
    if (_locked || _text.matches.isEmpty) return;
    final index = _text.current.clamp(0, _text.matches.length - 1);
    final at = _text.matches[index];
    final length = _find.text.length;
    final replacement = _replace.text;
    _setText(
      _text.text.replaceRange(at, at + length, replacement),
      caret: at + replacement.length,
    );
    if (_text.matches.isNotEmpty) _goTo(_nearestMatch());
  }

  void _replaceAll() {
    if (_locked || _text.matches.isEmpty) return;
    final count = _text.matches.length;
    _setText(
      replaceTranscriptMatches(
        _text.text,
        _text.matches,
        _find.text.length,
        _replace.text,
      ),
      caret: 0,
    );
    _toast('${toPersianDigits('$count')} مورد جایگزین شد');
  }

  /// Scrolls the page so the character at [offset] is visible.
  void _reveal(int offset) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final root = _fieldKey.currentContext?.findRenderObject();
      if (root == null || !mounted) return;
      RenderEditable? editable;
      void visit(RenderObject object) {
        if (editable != null) return;
        if (object is RenderEditable) {
          editable = object;
          return;
        }
        object.visitChildren(visit);
      }

      visit(root);
      final target = editable;
      if (target == null || offset > _text.text.length) return;
      target.showOnScreen(
        rect: target.getLocalRectForCaret(TextPosition(offset: offset)),
        duration: const Duration(milliseconds: 180),
        curve: Curves.easeOut,
      );
    });
  }

  // ---- build ---------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final text = _text.text;
    final lineCount = canonicalTranscriptLines(text).length;
    final wordCount = text
        .split(RegExp(r'\s+'))
        .where((w) => w.isNotEmpty)
        .length;

    if (widget.statusDestination != null) {
      final destination = widget.statusDestination!;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && widget.statusDestination == destination) {
          destination.value = Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
            child: _statusRow(Theme.of(context), wordCount, lineCount),
          );
        }
      });
    }

    return PopScope(
      canPop: !(_dirty || _unsettled || _saving),
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _flushAndLeave();
      },
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (widget.notice != null) ...[
            _Notice(
              message: widget.notice!,
              actionLabel: widget.noticeActionLabel,
              onAction: widget.onNoticeAction,
            ),
            const SizedBox(height: 10),
          ],
          if (_findOpen) ...[_findBar(theme), const SizedBox(height: 8)],
          TextField(
            key: _fieldKey,
            controller: _text,
            focusNode: _focus,
            readOnly: _locked,
            minLines: 8,
            maxLines: null,
            keyboardType: TextInputType.multiline,
            textInputAction: TextInputAction.newline,
            style: theme.textTheme.bodyMedium?.copyWith(height: 1.9),
            decoration: const InputDecoration(
              hintText: 'متن را اینجا بنویسید',
              border: InputBorder.none,
              enabledBorder: InputBorder.none,
              focusedBorder: InputBorder.none,
              filled: false,
              contentPadding: EdgeInsets.zero,
            ),
          ),
          if (widget.statusDestination == null) ...[
            const SizedBox(height: 8),
            _statusRow(theme, wordCount, lineCount),
          ],
        ],
      ),
    );
  }

  Widget _statusRow(ThemeData theme, int wordCount, int lineCount) => Row(
    children: [
      Expanded(
        child: Text(
          '${toPersianDigits('$wordCount')} کلمه · '
          '${toPersianDigits('$lineCount')} بخش',
          style: theme.textTheme.bodySmall,
        ),
      ),
      _saveStatus(theme),
    ],
  );

  Widget _saveStatus(ThemeData theme) {
    if (_saveFailed) {
      return TextButton.icon(
        onPressed: () => _save(settle: true),
        icon: const Icon(Icons.refresh, size: 16),
        label: const Text('ذخیره نشد؛ تلاش دوباره'),
        style: TextButton.styleFrom(foregroundColor: SsColors.danger),
      );
    }
    final (icon, label) = _saving || _dirty
        ? (Icons.sync, 'در حال ذخیره…')
        : (Icons.check, 'ذخیره شد');
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 14, color: SsColors.neutral),
        const SizedBox(width: 4),
        Text(label, style: theme.textTheme.bodySmall),
      ],
    );
  }

  Future<void> _copy() async {
    await Clipboard.setData(ClipboardData(text: _text.text));
    _toast('متن کپی شد');
  }

  void _share() => SharePlus.instance.share(ShareParams(text: _text.text));

  List<PopupMenuEntry<VoidCallback>> actionItems() {
    PopupMenuItem<VoidCallback> item(
      String label,
      IconData icon,
      VoidCallback? action,
    ) => PopupMenuItem<VoidCallback>(
      value: action,
      enabled: action != null,
      child: Row(
        children: [
          Icon(icon, size: 18),
          const SizedBox(width: 10),
          Flexible(child: Text(label)),
        ],
      ),
    );
    final editable = !_locked;
    final hasText = _text.text.trim().isNotEmpty;
    return [
      item('کپی', Icons.copy, hasText ? _copy : null),
      item('اشتراک‌گذاری متن', Icons.ios_share, hasText ? _share : null),
      item('واگرد', Icons.undo, editable && _at > 0 ? () => _travel(-1) : null),
      item(
        'بازگرد',
        Icons.redo,
        editable && _at < _history.length - 1 ? () => _travel(1) : null,
      ),
      item('جستجو و جایگزینی', Icons.find_replace, _toggleFind),
      item(
        'حذف خط',
        Icons.playlist_remove,
        editable && hasText ? _deleteLine : null,
      ),
      item(
        'ادغام با خط بعد',
        Icons.vertical_align_center,
        editable ? _joinWithNext : null,
      ),
      item(
        'یکدست‌سازی نویسه‌ها و فاصله‌ها',
        Icons.auto_fix_high,
        editable ? _tidy : null,
      ),
    ];
  }

  Widget _tool(
    String tooltip,
    IconData icon,
    VoidCallback? onPressed, {
    bool active = false,
  }) => IconButton(
    tooltip: tooltip,
    visualDensity: VisualDensity.compact,
    style: active
        ? IconButton.styleFrom(backgroundColor: SsColors.selected)
        : null,
    onPressed: onPressed,
    icon: Icon(icon, size: 20),
  );

  Widget _findBar(ThemeData theme) {
    final count = _text.matches.length;
    final hasQuery = _find.text.isNotEmpty;
    final status = !hasQuery
        ? ''
        : count == 0
        ? 'موردی نیست'
        : '${toPersianDigits('${_text.current + 1}')} از ${toPersianDigits('$count')}';
    return Container(
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: SsColors.selected.withValues(alpha: 0.5),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _find,
                  focusNode: _findFocus,
                  textInputAction: TextInputAction.search,
                  onChanged: (_) => _onQueryChanged(),
                  onSubmitted: (_) {
                    _step(1);
                    _findFocus.requestFocus();
                  },
                  decoration: const InputDecoration(hintText: 'جستجو'),
                ),
              ),
              const SizedBox(width: 6),
              SizedBox(
                width: 64,
                child: Text(
                  status,
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodySmall,
                ),
              ),
              _tool(
                'مورد قبلی',
                Icons.keyboard_arrow_up,
                count > 0 ? () => _step(-1) : null,
              ),
              _tool(
                'مورد بعدی',
                Icons.keyboard_arrow_down,
                count > 0 ? () => _step(1) : null,
              ),
            ],
          ),
          const SizedBox(height: 6),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _replace,
                  textInputAction: TextInputAction.done,
                  decoration: const InputDecoration(hintText: 'جایگزین'),
                ),
              ),
              const SizedBox(width: 6),
              OutlinedButton(
                onPressed: !_locked && count > 0 ? _replaceCurrent : null,
                child: const Text('جایگزین'),
              ),
              const SizedBox(width: 6),
              OutlinedButton(
                onPressed: !_locked && count > 0 ? _replaceAll : null,
                child: const Text('همه'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _Notice extends StatelessWidget {
  const _Notice({required this.message, this.actionLabel, this.onAction});

  final String message;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(color: SsColors.selected),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.info_outline, size: 18, color: SsColors.primary),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(message, style: Theme.of(context).textTheme.bodySmall),
                if (actionLabel != null)
                  TextButton(onPressed: onAction, child: Text(actionLabel!)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Text controller that paints find matches behind the text.
class _TranscriptController extends TextEditingController {
  _TranscriptController({super.text});

  List<int> matches = const [];
  int matchLength = 0;
  int current = -1;

  @override
  TextSpan buildTextSpan({
    required BuildContext context,
    TextStyle? style,
    required bool withComposing,
  }) {
    if (matches.isEmpty ||
        matchLength == 0 ||
        (withComposing && value.isComposingRangeValid)) {
      return super.buildTextSpan(
        context: context,
        style: style,
        withComposing: withComposing,
      );
    }
    final spans = <InlineSpan>[];
    var cursor = 0;
    for (var i = 0; i < matches.length; i++) {
      final at = matches[i];
      if (at < cursor || at + matchLength > text.length) continue;
      if (at > cursor) spans.add(TextSpan(text: text.substring(cursor, at)));
      spans.add(
        TextSpan(
          text: text.substring(at, at + matchLength),
          style: TextStyle(
            backgroundColor: i == current
                ? SsColors.accent
                : SsColors.accent.withValues(alpha: 0.3),
          ),
        ),
      );
      cursor = at + matchLength;
    }
    if (cursor < text.length) spans.add(TextSpan(text: text.substring(cursor)));
    return TextSpan(style: style, children: spans);
  }
}

class TranscriptActionsButton extends StatelessWidget {
  const TranscriptActionsButton({super.key, required this.editorKey});

  final GlobalKey<TranscriptEditorState> editorKey;

  @override
  Widget build(BuildContext context) => PopupMenuButton<VoidCallback>(
    tooltip: 'ابزار متن جلسه',
    icon: const Icon(Icons.edit_note),
    position: PopupMenuPosition.under,
    onSelected: (action) => action(),
    itemBuilder: (_) => editorKey.currentState?.actionItems() ?? [],
  );
}
