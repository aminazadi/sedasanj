import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:jalase_negar/core/asr/asr_common.dart';
import 'package:jalase_negar/core/asr/sherpa_sound_tagger.dart';
import 'package:jalase_negar/core/asr/sound_events.dart';

import 'bench_support.dart';

/// Measures how accurately the detector finds labelled sounds.
///
/// Labelled clips (ESC-50, converted to 16 kHz mono PCM16, listed in
/// `selected.csv`) are placed on a timeline alone and mixed into real Persian
/// meeting speech at several levels. The real CED model scores every window
/// once (cached as JSON); the detector variants are then replayed on the
/// cached scores, so thresholds can be compared in seconds.
///
/// ```bash
/// BENCH_CED=~/.cache/jalase-bench/models/ced-tiny \
/// BENCH_SOUND_AUDIO=../sedasanj/test_data/asr_golden/audio \
/// BENCH_ESC=<dir with audio16/ and selected.csv> \
/// BENCH_CACHE=<dir for the score cache> \
/// flutter test test/bench/bench_sound_accuracy_test.dart
/// ```
void main() {
  final env = Platform.environment;
  final skip =
      env['BENCH_CED'] == null ||
          env['BENCH_SOUND_AUDIO'] == null ||
          env['BENCH_ESC'] == null ||
          env['BENCH_CACHE'] == null
      ? 'Set BENCH_CED, BENCH_SOUND_AUDIO, BENCH_ESC and BENCH_CACHE.'
      : null;

  test(
    'detector accuracy on labelled clips',
    () {
      initHostBindings();
      final home = env['HOME']!;
      String path(String key) => env[key]!.replaceFirst('~', home);
      final bench = _Bench(
        cedDir: path('BENCH_CED'),
        speechDir: path('BENCH_SOUND_AUDIO'),
        escDir: path('BENCH_ESC'),
        cacheDir: path('BENCH_CACHE'),
        negDir: env['BENCH_NEG'] == null ? null : path('BENCH_NEG'),
        windowMs: int.parse(env['BENCH_W'] ?? '3000'),
        hopMs: int.parse(env['BENCH_H'] ?? '1000'),
      );
      bench.run();
    },
    skip: skip,
    timeout: const Timeout(Duration(minutes: 40)),
  );
}

/// What a clip category must produce: the kinds that count as right.
const Map<String, Set<String>> _expected = {
  'laughing': {
    'laughter',
    'belly_laugh',
    'giggle',
    'snicker',
    'chuckle',
    'baby_laughter',
  },
  'crying_baby': {'baby_cry', 'crying', 'whimper', 'wail'},
  'coughing': {'cough'},
  'sneezing': {'sneeze'},
  'clapping': {'applause'},
  'snoring': {'snoring'},
};

class _Clip {
  _Clip(this.file, this.fold, this.category, this.samples);

  final String file;
  final int fold;
  final String category;
  final Float32List samples;

  /// First and last 20 ms frame holding real sound (the clips are padded with
  /// digital silence), in samples.
  late final (int, int) active = _activeRange(samples);
}

(int, int) _activeRange(Float32List x) {
  const frame = 320;
  int? first;
  var last = 0;
  for (var i = 0; i + frame <= x.length; i += frame) {
    var peak = 0.0;
    for (var j = i; j < i + frame; j++) {
      peak = math.max(peak, x[j].abs());
    }
    if (peak > 0.002) {
      first ??= i;
      last = i + frame;
    }
  }
  return (first ?? 0, last == 0 ? x.length : last);
}

double _rms(Float32List x, int from, int to) {
  var sum = 0.0;
  for (var i = from; i < to; i++) {
    sum += x[i] * x[i];
  }
  return math.sqrt(sum / math.max(1, to - from));
}

/// One test timeline with its truth.
class _Stream {
  _Stream(
    this.id,
    this.clip,
    this.scenario,
    this.length,
    this.make,
    this.truthFrom,
    this.truthTo,
  );

  final String id;
  final _Clip? clip; // null: speech only
  final String scenario;
  final int length; // samples
  final Float32List Function() make;
  final int truthFrom; // ms, -1 when none
  final int truthTo;

  Float32List get audio => make();
}

/// Window scores of one stream with the sample at which each window ended.
class _Rec {
  _Rec(this.ends, this.windows);

  final List<int> ends;
  final List<List<SoundScore>> windows;
}

class _ReplayByEnd implements SoundTagger {
  _ReplayByEnd(this.byEnd, this.clock, this.topK);

  final Map<int, List<SoundScore>> byEnd;
  final int Function() clock;
  final int topK;

  @override
  List<SoundScore> tag(Float32List samples) {
    final scores = byEnd[clock()] ?? const <SoundScore>[];
    return topK >= scores.length ? scores : scores.sublist(0, topK);
  }
}

class _Recorder implements SoundTagger {
  _Recorder(this.inner, this.clock);

  final SoundTagger inner;
  final int Function() clock;
  final List<int> ends = [];
  final List<List<SoundScore>> windows = [];

  @override
  List<SoundScore> tag(Float32List samples) {
    final scores = inner.tag(samples);
    ends.add(clock());
    windows.add(scores);
    return scores;
  }
}

class _Bench {
  _Bench({
    required this.cedDir,
    required this.speechDir,
    required this.escDir,
    required this.cacheDir,
    this.negDir,
    required this.windowMs,
    required this.hopMs,
  });

  final String cedDir;
  final String speechDir;
  final String escDir;
  final String cacheDir;

  /// Extra speech-only recordings (noisy, reverberant, overlapped, other
  /// speakers) that must not produce any sound event.
  final String? negDir;
  final int windowMs;
  final int hopMs;

  late final Float32List speech = _loadSpeech();
  late final List<_Clip> clips = _loadClips();

  static const pad = 4 * kAsrSampleRate;

  Float32List _read(String file) {
    final pcm = readPcm16Mono(file);
    final view = ByteData.sublistView(pcm);
    final out = Float32List(pcm.length ~/ 2);
    for (var i = 0; i < out.length; i++) {
      out[i] = view.getInt16(i * 2, Endian.little) / 32768.0;
    }
    return out;
  }

  Float32List _loadSpeech() {
    final parts = [
      for (final f in Directory(speechDir).listSync().whereType<File>())
        if (f.path.endsWith('.wav')) _read(f.path),
    ];
    final total = parts.fold<int>(0, (a, b) => a + b.length);
    final out = Float32List(total);
    var at = 0;
    for (final p in parts) {
      out.setRange(at, at + p.length, p);
      at += p.length;
    }
    return out;
  }

  List<_Clip> _loadClips() {
    final lines = File('$escDir/selected.csv').readAsLinesSync().skip(1);
    return [
      for (final line in lines)
        if (line.trim().isNotEmpty)
          _Clip(
            line.split(',')[0],
            int.parse(line.split(',')[1]),
            line.split(',')[2],
            _read('$escDir/audio16/${line.split(',')[0]}'),
          ),
    ];
  }

  /// 13 s of speech starting where the speech is clearly active.
  Float32List _speechChunk(int index, int samples) {
    final span = speech.length - samples;
    var start = (index * 11 * kAsrSampleRate) % span;
    for (var tries = 0; tries < 40; tries++) {
      if (_rms(speech, start, start + samples) > 0.01) break;
      start = (start + 7 * kAsrSampleRate) % span;
    }
    return Float32List.sublistView(speech, start, start + samples);
  }

  List<_Stream> buildStreams() {
    final streams = <_Stream>[];
    for (var i = 0; i < clips.length; i++) {
      final clip = clips[i];
      final length = pad + clip.samples.length + pad;
      final (a, b) = clip.active;
      final truthFrom = (pad + a) * 1000 ~/ kAsrSampleRate;
      final truthTo = (pad + b) * 1000 ~/ kAsrSampleRate;
      streams.add(
        _Stream(
          '${clip.file}|clean',
          clip,
          'clean',
          length,
          () =>
              Float32List(length)
                ..setRange(pad, pad + clip.samples.length, clip.samples),
          truthFrom,
          truthTo,
        ),
      );
      final bg = _speechChunk(i, length);
      final eventRms = _rms(clip.samples, a, b);
      final speechRms = _rms(bg, 0, bg.length);
      for (final snr in [0, -6]) {
        final gain = eventRms == 0
            ? 0.0
            : speechRms * math.pow(10, snr / 20) / eventRms;
        Float32List mix() {
          final out = Float32List.fromList(bg);
          for (var j = 0; j < clip.samples.length; j++) {
            out[pad + j] = (out[pad + j] + clip.samples[j] * gain).clamp(
              -1.0,
              1.0,
            );
          }
          return out;
        }

        streams.add(
          _Stream(
            '${clip.file}|snr$snr',
            clip,
            'snr$snr',
            length,
            mix,
            truthFrom,
            truthTo,
          ),
        );
      }
    }
    // Speech only: the whole golden clips in 60 s pieces.
    for (
      var i = 0;
      i + 60 * kAsrSampleRate <= speech.length;
      i += 60 * kAsrSampleRate
    ) {
      streams.add(
        _Stream(
          'speech-only-${i ~/ kAsrSampleRate}',
          null,
          'speech',
          60 * kAsrSampleRate,
          () => Float32List.sublistView(speech, i, i + 60 * kAsrSampleRate),
          -1,
          -1,
        ),
      );
    }
    final neg = negDir;
    if (neg != null) {
      final files =
          Directory(neg)
              .listSync()
              .whereType<File>()
              .where((f) => f.path.endsWith('.wav'))
              .toList()
            ..sort((a, b) => a.path.compareTo(b.path));
      for (final file in files) {
        final audio = _read(file.path);
        final name = file.uri.pathSegments.last;
        for (
          var i = 0;
          i + 30 * kAsrSampleRate <= audio.length;
          i += 60 * kAsrSampleRate
        ) {
          final end = math.min(audio.length, i + 60 * kAsrSampleRate);
          streams.add(
            _Stream(
              'neg-$name-${i ~/ kAsrSampleRate}',
              null,
              'speech',
              end - i,
              () => Float32List.sublistView(audio, i, end),
              -1,
              -1,
            ),
          );
        }
      }
    }
    return streams;
  }

  /// Replays recorded scores on the same timeline. Audio is not needed: a
  /// window the silence gate skipped has no recorded scores and votes for
  /// nothing, exactly as when it was skipped.
  List<DetectedSoundEvent> replay(
    _Stream stream,
    _Rec rec,
    List<SoundEventKind> kinds,
    int topK,
  ) {
    late final SoundEventDetector detector;
    final byEnd = {
      for (var i = 0; i < rec.ends.length; i++) rec.ends[i]: rec.windows[i],
    };
    detector = SoundEventDetector(
      tagger: _ReplayByEnd(byEnd, () => detector.fedSamples, topK),
      windowMs: windowMs,
      hopMs: hopMs,
      kinds: kinds,
      silenceRms: 0,
    );
    final out = <DetectedSoundEvent>[];
    const chunk = 3200;
    final zeros = Float32List(chunk);
    for (var i = 0; i < stream.length; i += chunk) {
      out.addAll(
        detector.accept(
          Float32List.sublistView(zeros, 0, math.min(chunk, stream.length - i)),
        ),
      );
    }
    out.addAll(detector.flush());
    return out;
  }

  Map<String, _Rec> _scores(List<_Stream> streams) {
    final cacheFile = File('$cacheDir/scores2-w$windowMs-h$hopMs.json');
    final result = <String, _Rec>{};
    if (cacheFile.existsSync()) {
      final raw =
          jsonDecode(cacheFile.readAsStringSync()) as Map<String, Object?>;
      for (final e in raw.entries) {
        final m = e.value! as Map<String, Object?>;
        result[e.key] = _Rec(
          [for (final v in m['e']! as List) (v as num).toInt()],
          [
            for (final w in m['w']! as List)
              [
                for (final s in w as List)
                  SoundScore(
                    (s as List)[0] as String,
                    (s[1] as num).toDouble(),
                  ),
              ],
          ],
        );
      }
    }
    final missing = [
      for (final s in streams)
        if (!result.containsKey(s.id)) s,
    ];
    if (missing.isEmpty) return result;
    final tagger = SherpaSoundTagger.tryCreate(
      modelPath: '$cedDir/model.int8.onnx',
      labelsPath: '$cedDir/class_labels_indices.csv',
      topK: 80,
    )!;
    final watch = Stopwatch()..start();
    for (final stream in missing) {
      late final SoundEventDetector detector;
      final recorder = _Recorder(tagger, () => detector.fedSamples);
      detector = SoundEventDetector(
        tagger: recorder,
        windowMs: windowMs,
        hopMs: hopMs,
      );
      const chunk = 3200;
      final audio = stream.make();
      for (var i = 0; i < audio.length; i += chunk) {
        detector.accept(
          Float32List.sublistView(audio, i, math.min(audio.length, i + chunk)),
        );
      }
      detector.flush();
      result[stream.id] = _Rec(recorder.ends, recorder.windows);
    }
    stdout.writeln('scored ${missing.length} streams in ${watch.elapsed}');
    Directory(cacheDir).createSync(recursive: true);
    cacheFile.writeAsStringSync(
      jsonEncode({
        for (final e in result.entries)
          e.key: {
            'e': e.value.ends,
            'w': [
              for (final w in e.value.windows)
                [
                  for (final s in w)
                    [s.name, double.parse(s.probability.toStringAsFixed(4))],
                ],
            ],
          },
      }),
    );
    tagger.free();
    return result;
  }

  void run() {
    final streams = buildStreams();
    final scores = _scores(streams);
    final variants = <String, ({List<SoundEventKind> kinds, int topK})>{
      'app table, top-12': (kinds: kSoundEventKinds, topK: 12),
      'app table, top-30': (kinds: kSoundEventKinds, topK: 30),
      'app table, top-80': (kinds: kSoundEventKinds, topK: 80),
    };
    for (final entry in variants.entries) {
      _report(entry.key, streams, scores, entry.value.kinds, entry.value.topK);
    }
    if (Platform.environment['BENCH_SWEEP'] == '1') _sweep(streams, scores);
    if (Platform.environment['BENCH_NEGSWEEP'] == '1')
      _negativeSweep(streams, scores);
  }

  /// For kinds with no labelled clips: the number of events each threshold
  /// would write on audio that has none of them (speech-only recordings and
  /// the ESC clips of other sounds). Recall cannot be measured for these.
  void _negativeSweep(List<_Stream> streams, Map<String, _Rec> scores) {
    for (final base in kSoundEventKinds) {
      stdout.writeln('\n### negsweep ${base.id}');
      for (final t in [
        0.03,
        0.05,
        0.08,
        0.12,
        0.16,
        0.20,
        0.25,
        0.30,
        0.40,
        0.50,
        0.60,
        0.70,
      ]) {
        final kinds = [
          SoundEventKind(
            id: base.id,
            labelFa: base.labelFa,
            group: base.group,
            audioSetNames: base.audioSetNames,
            threshold: t,
            minWindows: base.minWindows,
          ),
        ];
        var speech = 0;
        var humanLike = 0;
        var other = 0;
        final where = <String, int>{};
        for (final stream in streams) {
          final events = replay(stream, scores[stream.id]!, kinds, 80);
          if (events.isEmpty) continue;
          final clip = stream.clip;
          if (clip == null) {
            speech += events.length;
          } else if (_expected[clip.category] != null &&
              !(_expected[clip.category]!.contains(base.id))) {
            humanLike += events.length;
            where[clip.category] = (where[clip.category] ?? 0) + events.length;
          } else if (_expected[clip.category] == null) {
            other += events.length;
            where[clip.category] = (where[clip.category] ?? 0) + events.length;
          }
        }
        stdout.writeln(
          '  t=${t.toStringAsFixed(2)} minW=${base.minWindows} speech-only $speech | other-sound clips (ESC, 3 mixes) $humanLike | non-sound clips $other $where',
        );
      }
    }
  }

  /// For each sound, how recall and false events change with the threshold
  /// (the same value for every kind of the sound). Calibration folds are 1-3;
  /// folds 4-5 are only for checking a chosen value.
  void _sweep(List<_Stream> streams, Map<String, _Rec> scores) {
    const slack = 1500;
    final targets = <String, ({String category, Set<String> kinds})>{
      'laughter': (category: 'laughing', kinds: _expected['laughing']!),
      'crying': (category: 'crying_baby', kinds: _expected['crying_baby']!),
      'cough': (category: 'coughing', kinds: _expected['coughing']!),
      'sneeze': (category: 'sneezing', kinds: _expected['sneezing']!),
      'applause': (category: 'clapping', kinds: _expected['clapping']!),
      'snoring': (category: 'snoring', kinds: _expected['snoring']!),
    };
    for (final entry in targets.entries) {
      stdout.writeln(
        '\n### sweep ${entry.key} (cal = folds 1-3, test = folds 4-5)',
      );
      for (final minWindows in [1, 2]) {
        for (final t in [
          0.04,
          0.06,
          0.08,
          0.10,
          0.13,
          0.16,
          0.20,
          0.25,
          0.30,
          0.40,
        ]) {
          final kinds = [
            for (final k in kSoundEventKinds)
              if (entry.value.kinds.contains(k.id))
                SoundEventKind(
                  id: k.id,
                  labelFa: k.labelFa,
                  group: k.group,
                  audioSetNames: k.audioSetNames,
                  threshold: t,
                  minWindows: minWindows,
                ),
          ];
          final hit = {
            for (final f in ['cal', 'test'])
              for (final sc in ['clean', 'snr0', 'snr-6']) '$f|$sc': [0, 0],
          };
          var falseCal = 0;
          var falseTest = 0;
          var speechFalse = 0;
          for (final stream in streams) {
            final events = replay(stream, scores[stream.id]!, kinds, 80);
            final clip = stream.clip;
            if (clip == null) {
              speechFalse += events.length;
              continue;
            }
            final cal = clip.fold <= 3;
            final near = [
              for (final e in events)
                if (e.endMs >= stream.truthFrom - slack &&
                    e.startMs <= stream.truthTo + slack)
                  e,
            ];
            if (clip.category == entry.value.category) {
              final row = hit['${cal ? 'cal' : 'test'}|${stream.scenario}']!;
              row[1]++;
              if (near.isNotEmpty) row[0]++;
              final far = events.length - near.length;
              if (cal) {
                falseCal += far;
              } else {
                falseTest += far;
              }
            } else if (events.isNotEmpty) {
              if (cal) {
                falseCal += events.length;
              } else {
                falseTest += events.length;
              }
            }
          }
          String r(String k) => '${hit[k]![0]}/${hit[k]![1]}';
          stdout.writeln(
            '  minW=$minWindows t=${t.toStringAsFixed(2)}  cal recall clean ${r('cal|clean')} snr0 ${r('cal|snr0')} snr-6 ${r('cal|snr-6')} | test clean ${r('test|clean')} snr0 ${r('test|snr0')} snr-6 ${r('test|snr-6')} | false: cal $falseCal test $falseTest speech $speechFalse',
          );
        }
      }
    }
  }

  void _report(
    String name,
    List<_Stream> streams,
    Map<String, _Rec> scores,
    List<SoundEventKind> kinds,
    int topK,
  ) {
    const slack = 1500;
    final byScenario = <String, Map<String, List<int>>>{};
    final confusion = <String, Map<String, int>>{};
    var speechOnlyEvents = 0;
    var speechSeconds = 0.0;
    final falseByKind = <String, int>{};
    for (final stream in streams) {
      final events = replay(stream, scores[stream.id]!, kinds, topK);
      if (stream.clip == null) {
        speechOnlyEvents += events.length;
        speechSeconds += stream.length / kAsrSampleRate;
        for (final e in events) {
          falseByKind[e.kind.id] = (falseByKind[e.kind.id] ?? 0) + 1;
          stdout.writeln(
            '  speech-only false: ${e.kind.id} ${e.score.toStringAsFixed(2)} in ${stream.id} at ${e.startMs ~/ 1000}s',
          );
        }
        continue;
      }
      final clip = stream.clip!;
      final want = _expected[clip.category];
      final near = [
        for (final e in events)
          if (e.endMs >= stream.truthFrom - slack &&
              e.startMs <= stream.truthTo + slack)
            e,
      ];
      final far = events.length - near.length;
      final key = '${clip.category}|${stream.scenario}';
      final row = byScenario.putIfAbsent(
        key,
        () => {
          'n': [0],
          'hit': [0],
          'wrong': [0],
          'far': [0],
        },
      );
      row['n']![0]++;
      row['far']![0] += far;
      for (final e in events) {
        if (e.endMs < stream.truthFrom - slack ||
            e.startMs > stream.truthTo + slack) {
          falseByKind[e.kind.id] = (falseByKind[e.kind.id] ?? 0) + 1;
        }
      }
      if (want == null) {
        // A sound that must stay unwritten.
        row['wrong']![0] += near.length;
        for (final e in near) {
          falseByKind[e.kind.id] = (falseByKind[e.kind.id] ?? 0) + 1;
        }
      } else if (near.any((e) => want.contains(e.kind.id))) {
        row['hit']![0]++;
        row['wrong']![0] += near.where((e) => !want.contains(e.kind.id)).length;
      } else {
        row['wrong']![0] += near.length;
        for (final e in near) {
          final c = confusion.putIfAbsent(clip.category, () => {});
          c[e.kind.id] = (c[e.kind.id] ?? 0) + 1;
        }
      }
    }
    stdout.writeln('\n=== $name ===');
    for (final scenario in ['clean', 'snr0', 'snr-6']) {
      stdout.writeln(
        '-- $scenario (recall = right kind found near the sound; wrong = other events near it; far = events away from it)',
      );
      for (final category in [
        ..._expected.keys,
        'breathing',
        'keyboard_typing',
        'footsteps',
        'mouse_click',
      ]) {
        final r = byScenario['$category|$scenario'];
        if (r == null) continue;
        final n = r['n']![0];
        final tag = _expected.containsKey(category)
            ? 'recall ${(100 * r['hit']![0] / n).toStringAsFixed(0)}% (${r['hit']![0]}/$n)'
            : 'false events near: ${r['wrong']![0]} in $n clips';
        stdout.writeln(
          '  ${category.padRight(16)} $tag, wrong ${r['wrong']![0]}, far ${r['far']![0]}',
        );
      }
    }
    stdout.writeln(
      'speech only: $speechOnlyEvents events in ${speechSeconds.toStringAsFixed(0)} s '
      '(${(speechOnlyEvents * 60 / math.max(1, speechSeconds)).toStringAsFixed(2)} per minute)',
    );
    stdout.writeln('all false events by kind: $falseByKind');
    stdout.writeln('missed clips became: $confusion');
  }
}
