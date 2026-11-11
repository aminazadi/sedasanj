import '../speaker/speaker_matcher.dart';

/// Which microphone channels carried a voice, block by block, on the
/// recording's own timeline (samples of the mixed 16 kHz stream, so paused
/// time is not counted and the numbers line up with the live transcript).
class ChannelActivityLog {
  ChannelActivityLog({this.sampleRate = 16000});

  final int sampleRate;

  // Parallel, in time order. `_masks` has bit c set when channel c owned the
  // block (it carried the voice; quiet bleed does not count).
  final List<int> _starts = [];
  final List<int> _lengths = [];
  final List<int> _masks = [];

  /// Records that [owners] (a bit mask of channels) carried the block that
  /// starts at [startSample] and is [length] samples long.
  void add(int startSample, int length, int owners) {
    if (length <= 0) return;
    _starts.add(startSample);
    _lengths.add(length);
    _masks.add(owners);
  }

  /// Milliseconds each channel owned inside `[startMs, endMs)`; channels that
  /// never owned anything are absent.
  Map<int, int> ownedMs(int startMs, int endMs) {
    final from = startMs * sampleRate ~/ 1000;
    final to = endMs * sampleRate ~/ 1000;
    final samples = <int, int>{};
    for (var i = _firstEndingAfter(from); i < _starts.length; i++) {
      final blockStart = _starts[i];
      if (blockStart >= to) break;
      final blockEnd = blockStart + _lengths[i];
      final overlap =
          (blockEnd < to ? blockEnd : to) -
          (blockStart > from ? blockStart : from);
      if (overlap <= 0) continue;
      final mask = _masks[i];
      for (var c = 0; mask >> c != 0; c++) {
        if ((mask >> c) & 1 == 1) {
          samples[c] = (samples[c] ?? 0) + overlap;
        }
      }
    }
    return {
      for (final e in samples.entries) e.key: e.value * 1000 ~/ sampleRate,
    };
  }

  /// Index of the first block that ends after [sample] (binary search).
  int _firstEndingAfter(int sample) {
    var lo = 0;
    var hi = _starts.length;
    while (lo < hi) {
      final mid = (lo + hi) >> 1;
      if (_starts[mid] + _lengths[mid] <= sample) {
        lo = mid + 1;
      } else {
        hi = mid;
      }
    }
    return lo;
  }
}

/// Who holds each microphone, and from when. A microphone can be handed to
/// someone else during the recording: the new owner counts from that moment
/// on and earlier lines keep the old one.
class ChannelAssignments {
  final Map<int, List<(int, SpeakerIdentity?)>> _changes = {};

  /// Gives [channel] to [who] (null: nobody, automatic detection again) from
  /// [atMs] on. A later call for the same time replaces the earlier one.
  void assign(int channel, SpeakerIdentity? who, {required int atMs}) {
    final list = _changes.putIfAbsent(channel, () => []);
    list.removeWhere((c) => c.$1 == atMs);
    list.add((atMs, who));
    list.sort((a, b) => a.$1.compareTo(b.$1));
  }

  /// The owner of [channel] at [ms]; null when nobody was assigned yet.
  SpeakerIdentity? ownerAt(int channel, int ms) {
    SpeakerIdentity? current;
    final list = _changes[channel];
    if (list == null) return null;
    for (final change in list) {
      if (change.$1 > ms) break;
      current = change.$2;
    }
    return current;
  }

  /// The owner now (after the last change).
  SpeakerIdentity? currentOwner(int channel) {
    final list = _changes[channel];
    return list == null || list.isEmpty ? null : list.last.$2;
  }

  /// True when no channel has an owner now.
  bool get isEmpty =>
      _changes.values.every((l) => l.isEmpty || l.last.$2 == null);
}

/// The people an utterance belongs to because of the microphones, not because
/// of their voices.
class ChannelOwners {
  const ChannelOwners(this.first, [this.second]);

  final SpeakerIdentity first;

  /// Set when a second assigned microphone was heard over the first.
  final SpeakerIdentity? second;
}

/// Names an utterance from the microphones' owners. When it answers, the
/// automatic voice recognition is not used for that line.
class ChannelOwnership {
  ChannelOwnership({required this.assignments, this.log});

  final ChannelAssignments assignments;

  /// Per-block activity of a multi-channel device; null for one microphone,
  /// which then owns every line.
  final ChannelActivityLog? log;

  /// A second microphone must be heard this long, and at least this share of
  /// the first one's time, to make the line an overlap.
  static const int minOverlapMs = 400;
  static const double minOverlapShare = 0.25;

  /// Owners of the utterance `[startMs, endMs]`, or null when the microphones
  /// say nothing (nobody assigned to the loudest channel, or silence): the
  /// automatic labels then stay.
  ///
  /// The owner is the one at the middle of the utterance, so a line spoken
  /// right after a handover belongs to the new holder.
  ChannelOwners? ownersOf(int startMs, int endMs) {
    final middle = startMs + (endMs - startMs) ~/ 2;
    final log = this.log;
    if (log == null) {
      final who = assignments.ownerAt(0, middle);
      return who == null ? null : ChannelOwners(_fixed(who));
    }
    final owned = log.ownedMs(startMs, endMs);
    if (owned.isEmpty) return null;
    final ranked = owned.entries.toList()
      ..sort((a, b) {
        final byTime = b.value.compareTo(a.value);
        return byTime != 0 ? byTime : a.key.compareTo(b.key);
      });
    final top = ranked.first;
    final first = assignments.ownerAt(top.key, middle);
    if (first == null) return null;
    SpeakerIdentity? second;
    for (final e in ranked.skip(1)) {
      if (e.value < minOverlapMs || e.value < top.value * minOverlapShare) {
        continue;
      }
      final who = assignments.ownerAt(e.key, middle);
      if (who != null && who.key != first.key) {
        second = who;
        break;
      }
    }
    return ChannelOwners(_fixed(first), second == null ? null : _fixed(second));
  }

  static SpeakerIdentity _fixed(SpeakerIdentity who) => who.withConfidence(100);
}

/// Bit mask of channel indexes.
int channelMask(Iterable<int> channels) {
  var mask = 0;
  for (final c in channels) {
    mask |= 1 << c;
  }
  return mask;
}
