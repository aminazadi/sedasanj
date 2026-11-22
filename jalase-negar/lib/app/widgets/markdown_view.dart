import 'package:flutter/material.dart';

/// Renders the Markdown subset the document engine writes: headings, bullet and
/// numbered lists, quotes, rules, paragraphs, and **bold** / `code` inline.
/// Text is selectable and follows the surrounding text direction.
class MarkdownView extends StatelessWidget {
  const MarkdownView({super.key, required this.markdown});

  final String markdown;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context).textTheme;
    final body = theme.bodyLarge ?? const TextStyle(fontSize: 16);
    final blocks = <Widget>[];
    final paragraph = <String>[];

    void flush() {
      if (paragraph.isEmpty) return;
      blocks.add(
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: Text.rich(
            inlineSpans(paragraph.join(' '), body),
            style: body.copyWith(height: 1.8),
          ),
        ),
      );
      paragraph.clear();
    }

    for (final raw in markdown.replaceAll('\r\n', '\n').split('\n')) {
      final line = raw.trimRight();
      final text = line.trim();
      if (text.isEmpty) {
        flush();
        continue;
      }
      final heading = RegExp(r'^(#{1,6})\s+(.*)$').firstMatch(text);
      if (heading != null) {
        flush();
        final level = heading.group(1)!.length;
        final size = const [22.0, 19.0, 17.0, 16.0, 15.0, 14.0][level - 1];
        blocks.add(
          Padding(
            padding: const EdgeInsets.only(top: 8, bottom: 6),
            child: Text.rich(
              inlineSpans(
                heading.group(2)!,
                body.copyWith(fontSize: size, fontWeight: FontWeight.w700),
              ),
              style: body.copyWith(fontSize: size, fontWeight: FontWeight.w700),
            ),
          ),
        );
        continue;
      }
      if (RegExp(r'^(-{3,}|\*{3,}|_{3,})$').hasMatch(text)) {
        flush();
        blocks.add(const Divider(height: 20));
        continue;
      }
      final bullet = RegExp(r'^[-*•]\s+(.*)$').firstMatch(text);
      final numbered = RegExp(r'^(\d+)[.)]\s+(.*)$').firstMatch(text);
      if (bullet != null || numbered != null) {
        flush();
        final marker = bullet != null ? '•' : '${numbered!.group(1)}.';
        final content = bullet != null ? bullet.group(1)! : numbered!.group(2)!;
        blocks.add(
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(width: 26, child: Text(marker, style: body)),
                Expanded(
                  child: Text.rich(
                    inlineSpans(content, body),
                    style: body.copyWith(height: 1.7),
                  ),
                ),
              ],
            ),
          ),
        );
        continue;
      }
      if (text.startsWith('>')) {
        flush();
        blocks.add(
          Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsetsDirectional.only(start: 10),
            decoration: BoxDecoration(
              border: BorderDirectional(
                start: BorderSide(color: Colors.grey.shade400, width: 3),
              ),
            ),
            child: Text.rich(
              inlineSpans(text.replaceFirst(RegExp(r'^>\s?'), ''), body),
              style: body.copyWith(color: Colors.black54, height: 1.7),
            ),
          ),
        );
        continue;
      }
      paragraph.add(text);
    }
    flush();
    return SelectionArea(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: blocks,
      ),
    );
  }
}

/// Splits `**bold**` and `` `code` `` out of a line; everything else stays text.
@visibleForTesting
TextSpan inlineSpans(String text, TextStyle base) {
  final spans = <InlineSpan>[];
  final pattern = RegExp(r'\*\*(.+?)\*\*|`([^`]+)`');
  var index = 0;
  for (final m in pattern.allMatches(text)) {
    if (m.start > index) {
      spans.add(TextSpan(text: text.substring(index, m.start)));
    }
    if (m.group(1) != null) {
      spans.add(
        TextSpan(
          text: m.group(1),
          style: const TextStyle(fontWeight: FontWeight.w700),
        ),
      );
    } else {
      spans.add(
        TextSpan(
          text: m.group(2),
          style: const TextStyle(fontFamily: 'monospace', fontSize: 14),
        ),
      );
    }
    index = m.end;
  }
  if (index < text.length) spans.add(TextSpan(text: text.substring(index)));
  return TextSpan(children: spans, style: base);
}
