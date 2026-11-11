import 'dart:io';
import 'dart:math' as math;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers.dart';

const kCpuCoresSettingKey = 'cpu_cores';

/// The most cores the owner may hand to the app: all but one (8 cores -> 7),
/// never less than 1. One core always stays free for the system and the
/// screen. (Half of the cores was too narrow a range for the slider to make a
/// visible difference, especially with several microphones transcribed in
/// parallel.)
int maxCpuCores([int? processors]) =>
    math.max(1, (processors ?? Platform.numberOfProcessors) - 1);

/// Out of the box the app keeps using what it always used: 2 cores, or fewer
/// on a phone that cannot spare them.
int defaultCpuCores([int? processors]) => math.min(2, maxCpuCores(processors));

/// Brings a stored or chosen value into 1..[maxCpuCores]; null or junk gives
/// the default.
int clampCpuCores(int? value, [int? processors]) {
  if (value == null) return defaultCpuCores(processors);
  return value.clamp(1, maxCpuCores(processors));
}

/// How many threads each kind of work may use for one chosen core budget.
/// At the default of 2 cores this equals the app's earlier fixed values
/// (recognition 2, speaker models 1).
class CpuBudget {
  const CpuBudget(this.cores);

  factory CpuBudget.of(int? stored, [int? processors]) =>
      CpuBudget(clampCpuCores(stored, processors));

  final int cores;

  /// Speech recognition (the heaviest, latency-critical work).
  int get recognitionThreads => cores;

  /// Live speaker models; they share the budget with recognition, so they
  /// get half of it.
  int get liveSpeakerThreads => math.max(1, cores ~/ 2);

  /// Offline speaker analysis of a finished recording; nothing else runs
  /// with it, so it may use the whole budget.
  int get analysisThreads => cores;

  /// The live sound-event tagger; it shares the budget with recognition, so
  /// like the speaker models it gets half (1 at the default of 2 cores).
  int get soundEventThreads => math.max(1, cores ~/ 2);

  /// Making or enrolling a voiceprint; nothing else runs beside it. At the
  /// default of 2 cores this equals the earlier fixed 2.
  int get voiceprintThreads => cores;

  // The voice-activity detector stays at one thread on purpose: the Silero
  // model is tiny and runs on every audio window, so more threads cost more
  // in hand-offs than they save.
}

final cpuBudgetProvider = AsyncNotifierProvider<CpuBudgetNotifier, CpuBudget>(
  CpuBudgetNotifier.new,
);

class CpuBudgetNotifier extends AsyncNotifier<CpuBudget> {
  @override
  Future<CpuBudget> build() async {
    final db = await ref.watch(appDatabaseProvider.future);
    final raw = await db.getSetting(kCpuCoresSettingKey);
    return CpuBudget.of(raw == null ? null : int.tryParse(raw));
  }

  Future<void> setCores(int cores) async {
    final value = clampCpuCores(cores);
    final db = await ref.read(appDatabaseProvider.future);
    await db.setSetting(kCpuCoresSettingKey, '$value');
    state = AsyncData(CpuBudget(value));
  }
}
