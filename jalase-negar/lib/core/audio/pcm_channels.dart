import 'dart:math' as math;
import 'dart:typed_data';

import '../asr/channel_gate.dart';
import 'channel_ownership.dart';

/// Splits interleaved little-endian PCM16 (`L R L R ...` for two channels,
/// `c0 c1 c2 c3 c0 ...` for four) into one mono PCM16 byte buffer per channel.
///
/// Capture callbacks may end in the middle of a frame; the partial frame is
/// kept and completed by the next [split] call, so no sample is lost or
/// shifted between channels.
class PcmDeinterleaver {
  PcmDeinterleaver(this.channels) {
    if (channels < 1) {
      throw ArgumentError.value(channels, 'channels', 'must be at least 1');
    }
  }

  final int channels;
  final BytesBuilder _carry = BytesBuilder(copy: false);

  int get _frameBytes => channels * 2;

  /// Returns exactly [channels] buffers (possibly empty), each mono PCM16.
  List<Uint8List> split(Uint8List interleaved) {
    Uint8List data = interleaved;
    if (_carry.length > 0) {
      _carry.add(interleaved);
      data = _carry.takeBytes();
    }
    final frames = data.length ~/ _frameBytes;
    final usable = frames * _frameBytes;
    if (usable < data.length) {
      _carry.add(Uint8List.sublistView(data, usable));
    }
    if (channels == 1) {
      return [Uint8List.sublistView(data, 0, usable)];
    }
    final out = List.generate(channels, (_) => Uint8List(frames * 2));
    for (var f = 0; f < frames; f++) {
      final base = f * _frameBytes;
      for (var c = 0; c < channels; c++) {
        out[c][f * 2] = data[base + c * 2];
        out[c][f * 2 + 1] = data[base + c * 2 + 1];
      }
    }
    return out;
  }

  void reset() => _carry.clear();
}

/// Joins equal-length mono PCM16 buffers back into one interleaved buffer
/// (`c0 c1 c2 ... c0 c1 ...`), the inverse of [PcmDeinterleaver.split].
Uint8List interleavePcm(List<Uint8List> channels) {
  if (channels.isEmpty) return Uint8List(0);
  if (channels.length == 1) return channels.first;
  final frames = channels.first.length ~/ 2;
  final out = Uint8List(frames * channels.length * 2);
  for (var f = 0; f < frames; f++) {
    for (var c = 0; c < channels.length; c++) {
      final at = (f * channels.length + c) * 2;
      out[at] = channels[c][f * 2];
      out[at + 1] = channels[c][f * 2 + 1];
    }
  }
  return out;
}

/// Level above which [softLimit] starts bending the signal, in 16-bit units
/// (about -3 dBFS).
const double kLimiterKnee = 23000;

/// Keeps a summed sample inside 16 bits without the harsh distortion of a hard
/// clamp: unchanged up to [kLimiterKnee], then eased towards full scale with a
/// tanh curve, so two loud voices (or one voice present on two channels) sum
/// to a rounded peak instead of a flat-topped one.
int softLimit(double x) {
  final a = x.abs();
  if (a <= kLimiterKnee) return x.round();
  const room = 32767 - kLimiterKnee;
  final shaped = kLimiterKnee + room * _tanh((a - kLimiterKnee) / room);
  return (x < 0 ? -shaped : shaped).round();
}

double _tanh(double v) {
  if (v > 20) return 1; // exp would overflow; tanh is 1 to machine precision
  final e = math.exp(2 * v);
  return (e - 1) / (e + 1);
}

/// What the probe concluded about one channel.
enum ChannelHealth {
  /// Nothing wrong seen (or not enough evidence yet).
  ok,

  /// Digital silence for the whole window: the receiver sends nothing on this
  /// channel (transmitter off, or a mono receiver whose second channel is empty).
  dead,

  /// Carries the same signal as an earlier channel (a mono receiver copying
  /// one mix to both sides).
  duplicate,
}

/// Looks at the first seconds of every channel and flags channels that cannot
/// be a separate microphone: digital silence, or a copy of another channel.
/// Judged per window and re-judged continuously, so a transmitter that is
/// switched on later turns its channel back to [ChannelHealth.ok].
class ChannelProbe {
  ChannelProbe(
    this.channels, {
    this.sampleRate = 16000,
    this.windowSeconds = 2,
    this.activeRms = 0.003,
    this.duplicateCorrelation = 0.98,
  }) : _peak = List.filled(channels, 0),
       _sumSq = List.filled(channels, 0.0),
       _cross = List.generate(channels, (_) => List.filled(channels, 0.0)),
       health = List.filled(channels, ChannelHealth.ok);

  final int channels;
  final int sampleRate;
  final int windowSeconds;

  /// RMS (0..1) a channel needs in a window before it can be called a copy.
  final double activeRms;
  final double duplicateCorrelation;

  /// Current verdict per channel.
  List<ChannelHealth> health;

  final List<int> _peak;
  final List<double> _sumSq;
  final List<List<double>> _cross;
  int _frames = 0;

  /// Digital silence means every sample within this many LSB of zero; a real
  /// microphone always has more noise than that.
  static const int _deadPeak = 2;

  /// Feeds equal-length mono buffers (one per channel). Returns true when the
  /// verdict changed.
  bool add(List<Uint8List> pcm) {
    if (pcm.length != channels || pcm.isEmpty) return false;
    final n = pcm.first.length ~/ 2;
    if (n == 0) return false;
    final views = [for (final b in pcm) ByteData.sublistView(b)];
    for (var i = 0; i < n; i++) {
      for (var a = 0; a < channels; a++) {
        final x = views[a].getInt16(i * 2, Endian.little);
        final ax = x.abs();
        if (ax > _peak[a]) _peak[a] = ax;
        _sumSq[a] += x * x;
        for (var b = a + 1; b < channels; b++) {
          _cross[a][b] += x * views[b].getInt16(i * 2, Endian.little);
        }
      }
    }
    _frames += n;
    if (_frames < sampleRate * windowSeconds) return false;
    return _judge();
  }

  bool _judge() {
    // Silence is judged afresh every window; a copy verdict is kept through
    // windows where nobody spoke (no evidence either way).
    final next = [
      for (var c = 0; c < channels; c++)
        _peak[c] <= _deadPeak
            ? ChannelHealth.dead
            : (health[c] == ChannelHealth.dead ? ChannelHealth.ok : health[c]),
    ];
    final rms = [
      for (var c = 0; c < channels; c++)
        math.sqrt(_sumSq[c] / _frames) / 32768.0,
    ];
    for (var a = 0; a < channels; a++) {
      if (next[a] == ChannelHealth.dead || rms[a] < activeRms) continue;
      for (var b = a + 1; b < channels; b++) {
        if (next[b] == ChannelHealth.dead || rms[b] < activeRms) continue;
        final denom = math.sqrt(_sumSq[a] * _sumSq[b]);
        final copy = denom > 0 && _cross[a][b] / denom >= duplicateCorrelation;
        next[b] = copy ? ChannelHealth.duplicate : ChannelHealth.ok;
      }
    }
    var changed = false;
    for (var c = 0; c < channels; c++) {
      if (next[c] != health[c]) changed = true;
    }
    health = next;
    // A fresh window: a channel judged dead or a copy can recover.
    for (var a = 0; a < channels; a++) {
      _peak[a] = 0;
      _sumSq[a] = 0;
      for (var b = 0; b < channels; b++) {
        _cross[a][b] = 0;
      }
    }
    _frames = 0;
    return changed;
  }
}

/// Mixes per-channel mono PCM16 into ONE mono stream for live recognition and
/// upload, keeping only the microphones that really carry a voice.
///
/// Per 20 ms block the [gate] picks the owner channels; their samples are
/// summed (divided by sqrt(owners), so two voices are not twice as loud). When
/// nobody passes the gate (quiet room, very soft speech) the plain average of
/// all channels is used, so low-level speech is never cut. The hard switch
/// between blocks can click when ownership flips; the speech models do not
/// mind, and the untouched per-channel recording is kept separately.
class ChannelMixdown {
  ChannelMixdown({
    this.gate = const ChannelGate(),
    this.blockSamples = 320,
    this.log,
  });

  final ChannelGate gate;
  final int blockSamples;

  /// When set, every mixed block records which channels carried the voice, on
  /// the timeline of the mixed output (the one the live transcript uses).
  final ChannelActivityLog? log;
  int _position = 0;

  /// [channels] are equal-length mono PCM16 buffers. Channels in [muted] are
  /// left out entirely (they neither own a block nor dilute the average); when
  /// every channel is muted the result is silence.
  Uint8List mix(List<Uint8List> channels, {Set<int> muted = const {}}) {
    if (channels.isEmpty) return Uint8List(0);
    final samples = channels.first.length ~/ 2;
    final out = ByteData(samples * 2);
    final active = [
      for (var c = 0; c < channels.length; c++)
        if (!muted.contains(c)) c,
    ];
    if (active.isEmpty) {
      _position += samples;
      return out.buffer.asUint8List();
    }
    final views = [for (final c in active) ByteData.sublistView(channels[c])];
    for (var start = 0; start < samples; start += blockSamples) {
      final end = math.min(samples, start + blockSamples);
      final rms = <double>[];
      for (final v in views) {
        var sum = 0.0;
        for (var i = start; i < end; i++) {
          final x = v.getInt16(i * 2, Endian.little) / 32768.0;
          sum += x * x;
        }
        rms.add(math.sqrt(sum / (end - start)));
      }
      final owners = gate.owners(rms);
      log?.add(
        _position + start,
        end - start,
        channelMask([for (final i in owners) active[i]]),
      );
      final use = owners.isEmpty
          ? List<int>.generate(views.length, (i) => i)
          : owners.toList();
      final scale = owners.isEmpty
          ? 1.0 / use.length
          : 1.0 / math.sqrt(use.length);
      for (var i = start; i < end; i++) {
        var acc = 0.0;
        for (final c in use) {
          acc += views[c].getInt16(i * 2, Endian.little);
        }
        out.setInt16(i * 2, softLimit(acc * scale), Endian.little);
      }
    }
    _position += samples;
    return out.buffer.asUint8List();
  }
}
