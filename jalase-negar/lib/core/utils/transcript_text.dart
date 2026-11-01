/// Joins ASR segments into plain transcript text ordered by start time.
///
/// Audio channels are microphone channels, not speaker identities, so no
/// speaker labels are invented here; speaker attribution happens server-side.
String buildTranscriptText(
  List<({int channel, int startMs, String text})> segments, {
  required int channelCount,
}) {
  final sorted = [...segments]..sort((a, b) => a.startMs.compareTo(b.startMs));
  final buffer = StringBuffer();
  for (final s in sorted) {
    final text = s.text.trim();
    if (text.isNotEmpty) buffer.writeln(text);
  }
  return buffer.toString().trim();
}
