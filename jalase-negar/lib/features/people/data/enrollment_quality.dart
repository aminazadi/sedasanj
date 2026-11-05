import 'dart:math' as math;
import 'dart:typed_data';

import '../../../core/asr/asr_common.dart';
import '../../../core/asr/energy_vad.dart';

/// Why a recorded sample is not good enough to enrol a voice.
enum EnrollmentIssue { ok, tooShort, tooQuiet, tooNoisy, clipped }

/// Result of checking one enrolment recording.
class EnrollmentAssessment {
  const EnrollmentAssessment({
    required this.issue,
    required this.speechMs,
    required this.snrDb,
    required this.clippedShare,
  });

  final EnrollmentIssue issue;

  /// Net speech found by the voice detector.
  final int speechMs;

  /// Speech level over the noise floor, in dB.
  final double snrDb;

  /// Share of samples at full scale.
  final double clippedShare;

  bool get ok => issue == EnrollmentIssue.ok;

  /// 0..100 stored with the voiceprint.
  int get quality {
    final bySpeech = (speechMs / 20000).clamp(0.0, 1.0);
    final bySnr = ((snrDb - 8) / 22).clamp(0.0, 1.0);
    return (100 * (0.5 * bySpeech + 0.5 * bySnr) * (1 - clippedShare * 20).clamp(0.0, 1.0)).round();
  }

  /// What went wrong and what to do, in Persian.
  String get messageFa => switch (issue) {
    EnrollmentIssue.ok => 'صدا مناسب بود.',
    EnrollmentIssue.tooShort =>
      'گفتار خیلی کوتاه بود؛ متن را تا آخر و با صدای عادی بخوانید و دوباره ضبط کنید.',
    EnrollmentIssue.tooQuiet =>
      'صدا خیلی ضعیف بود؛ گوشی را نزدیک‌تر بگیرید و کمی بلندتر بخوانید.',
    EnrollmentIssue.tooNoisy =>
      'محیط پرسروصداست؛ به جای ساکت‌تر بروید و دوباره بخوانید.',
    EnrollmentIssue.clipped =>
      'صدا بریده شد؛ گوشی را کمی دورتر بگیرید و آرام‌تر بخوانید.',
  };
}

/// Quality gates for an enrolment recording (16 kHz mono floats).
///
/// ⚠ needs lab confirmation: the limits are starting values; they have not
/// been tuned on real phones and rooms.
EnrollmentAssessment assessEnrollmentSample(
  Float32List samples, {
  int minSpeechMs = 10000,
  double minSnrDb = 12,
  double maxClippedShare = 0.005,
  double minPeak = 0.02,
}) {
  var peak = 0.0;
  var clipped = 0;
  for (final v in samples) {
    final a = v.abs();
    if (a > peak) peak = a;
    if (a >= 0.99) clipped++;
  }
  final clippedShare = samples.isEmpty ? 0.0 : clipped / samples.length;

  final regions = energyVadRegions(samples, kAsrSampleRate);
  final speechMs = regions.fold<int>(
    0,
    (sum, r) => sum + ((r.end - r.start) * 1000).round(),
  );
  final snr = _snrDb(samples, regions);

  EnrollmentIssue issue = EnrollmentIssue.ok;
  if (peak < minPeak) {
    issue = EnrollmentIssue.tooQuiet;
  } else if (clippedShare > maxClippedShare) {
    issue = EnrollmentIssue.clipped;
  } else if (speechMs < minSpeechMs) {
    issue = EnrollmentIssue.tooShort;
  } else if (snr < minSnrDb) {
    issue = EnrollmentIssue.tooNoisy;
  }
  return EnrollmentAssessment(
    issue: issue,
    speechMs: speechMs,
    snrDb: snr,
    clippedShare: clippedShare,
  );
}

double _snrDb(Float32List samples, List<SpeechRegion> regions) {
  if (samples.isEmpty || regions.isEmpty) return 0;
  var speechPower = 0.0;
  var speechCount = 0;
  var noisePower = 0.0;
  var noiseCount = 0;
  var region = 0;
  for (var i = 0; i < samples.length; i++) {
    final t = i / kAsrSampleRate;
    while (region < regions.length && regions[region].end < t) {
      region++;
    }
    final inSpeech =
        region < regions.length &&
        t >= regions[region].start &&
        t <= regions[region].end;
    final p = samples[i] * samples[i];
    if (inSpeech) {
      speechPower += p;
      speechCount++;
    } else {
      noisePower += p;
      noiseCount++;
    }
  }
  if (speechCount == 0) return 0;
  final speech = speechPower / speechCount;
  // Without a real pause, estimate the noise floor from the quietest frames.
  final noise = noiseCount < kAsrSampleRate ~/ 4
      ? math.max(_quietestFramePower(samples), 1e-10)
      : math.max(noisePower / noiseCount, 1e-10);
  return 10 * math.log(math.max(speech, 1e-12) / noise) / math.ln10;
}

/// Mean power of the quietest tenth of 30 ms frames.
double _quietestFramePower(Float32List samples) {
  final frame = kAsrSampleRate * 30 ~/ 1000;
  final powers = <double>[];
  for (var i = 0; i + frame <= samples.length; i += frame) {
    var sum = 0.0;
    for (var j = i; j < i + frame; j++) {
      sum += samples[j] * samples[j];
    }
    powers.add(sum / frame);
  }
  if (powers.isEmpty) return 1e-7;
  powers.sort();
  final take = math.max(1, powers.length ~/ 10);
  return powers.take(take).reduce((a, b) => a + b) / take;
}
