import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/models/download_manager.dart';
import '../../../core/models/model_catalog.dart';
import '../../../core/models/model_spec.dart';
import '../../../core/providers.dart';

const String kAsrModelSettingKey = 'selected_asr_model';

class ModelItemState {
  const ModelItemState({
    required this.spec,
    required this.installed,
    required this.selected,
    this.download,
  });

  final ModelSpec spec;
  final bool installed;
  final bool selected;
  final DownloadState? download;
}

class ModelsState {
  const ModelsState({
    this.items = const [],
    this.loading = true,
    this.installingAll = false,
  });

  final List<ModelItemState> items;
  final bool loading;

  /// True while the one-tap "download, install and activate" run is going.
  final bool installingAll;

  bool get allInstalled => items.isNotEmpty && items.every((i) => i.installed);

  /// Everything installed and the speech model switched on.
  bool get ready =>
      allInstalled &&
      items.any((i) => i.spec.kind == ModelKind.asr && i.selected);

  bool get hasFailure => items.any(
    (i) =>
        i.download?.status == DownloadStatus.failed ||
        i.download?.status == DownloadStatus.paused,
  );

  /// Share of the whole bundle already on the phone, from 0 to 1.
  double get progress {
    var total = 0;
    var done = 0;
    for (final i in items) {
      total += i.spec.totalSizeBytes;
      done += i.installed
          ? i.spec.totalSizeBytes
          : (i.download?.receivedBytes ?? 0);
    }
    return total == 0 ? 0 : (done / total).clamp(0.0, 1.0);
  }

  List<ModelItemState> byKind(ModelKind kind) =>
      items.where((i) => i.spec.kind == kind).toList();
}

class ModelsController extends Notifier<ModelsState> {
  final Map<String, DownloadState> _downloads = {};

  @override
  ModelsState build() {
    _load();
    return const ModelsState();
  }

  Future<void> _load() async {
    final store = await ref.read(modelStoreProvider.future);
    final db = await ref.read(appDatabaseProvider.future);
    for (final id in ModelCatalog.retiredIds) {
      await store.deleteById(id);
    }
    var selectedAsr = await db.getSetting(kAsrModelSettingKey);
    if (selectedAsr != null &&
        selectedAsr.isNotEmpty &&
        selectedAsr != ModelCatalog.shenavaKoochikRnnt.id) {
      // The chosen model was retired; the single remaining model replaces it.
      final installed = await store.isInstalled(
        ModelCatalog.shenavaKoochikRnnt,
      );
      selectedAsr = installed ? ModelCatalog.shenavaKoochikRnnt.id : '';
      await db.setSetting(kAsrModelSettingKey, selectedAsr);
    }
    final items = <ModelItemState>[];
    for (final spec in ModelCatalog.all) {
      final installed = await store.isInstalled(spec);
      final selected = switch (spec.kind) {
        ModelKind.asr => spec.id == selectedAsr,
        ModelKind.vad ||
        ModelKind.denoiser ||
        ModelKind.speakerEmbedding ||
        ModelKind.speakerSegmentation => installed,
      };
      items.add(
        ModelItemState(
          spec: spec,
          installed: installed,
          selected: selected,
          download: _downloads[spec.id],
        ),
      );
    }
    state = ModelsState(
      items: items,
      loading: false,
      installingAll: state.installingAll,
    );
  }

  Future<void> download(String modelId) async {
    final spec = ModelCatalog.byId(modelId);
    final starting = DownloadState(
      status: DownloadStatus.downloading,
      totalBytes: spec.totalSizeBytes,
    );
    _downloads[modelId] = starting;
    _patchDownload(modelId, starting);
    try {
      final downloader = await ref.read(modelDownloaderProvider.future);
      await downloader.download(
        spec,
        onState: (downloadState) {
          _downloads[modelId] = downloadState;
          if (downloadState.status == DownloadStatus.completed) {
            _downloads.remove(modelId);
            _onInstalled(spec);
          } else {
            // Keep failed/paused states visible, including the concrete
            // network error, instead of replacing them immediately via _load.
            _patchDownload(modelId, downloadState);
          }
        },
      );
    } catch (e) {
      final failed = DownloadState(
        status: DownloadStatus.failed,
        totalBytes: spec.totalSizeBytes,
        error: e.toString(),
      );
      _downloads[modelId] = failed;
      _patchDownload(modelId, failed);
    }
  }

  void _patchDownload(String modelId, DownloadState download) {
    state = ModelsState(
      loading: state.loading,
      installingAll: state.installingAll,
      items: [
        for (final item in state.items)
          item.spec.id == modelId
              ? ModelItemState(
                  spec: item.spec,
                  installed: item.installed,
                  selected: item.selected,
                  download: download,
                )
              : item,
      ],
    );
  }

  Future<void> _onInstalled(ModelSpec spec) async {
    // Auto-select the first installed model of each kind.
    final db = await ref.read(appDatabaseProvider.future);
    final selectedAsr = await db.getSetting(kAsrModelSettingKey);
    if (spec.kind == ModelKind.asr &&
        (selectedAsr == null || selectedAsr.isEmpty)) {
      await db.setSetting(kAsrModelSettingKey, spec.id);
    }
    await _load();
  }

  /// Downloads whatever is missing, one model after another, then switches
  /// the speech model on. Stops at the first failure or pause; calling it
  /// again resumes.
  Future<void> installAll() async {
    if (state.installingAll || state.loading) return;
    state = ModelsState(
      items: state.items,
      loading: false,
      installingAll: true,
    );
    try {
      for (final spec in ModelCatalog.all) {
        final item = state.items.firstWhere((i) => i.spec.id == spec.id);
        if (item.installed) continue;
        await download(spec.id);
        // A completed download clears its entry; anything left is a failure
        // or a pause and ends the run.
        if (_downloads.containsKey(spec.id)) return;
      }
      final db = await ref.read(appDatabaseProvider.future);
      await db.setSetting(
        kAsrModelSettingKey,
        ModelCatalog.shenavaKoochikRnnt.id,
      );
    } finally {
      state = ModelsState(
        items: state.items,
        loading: false,
        installingAll: false,
      );
      await _load();
    }
  }

  Future<void> cancelAll() async {
    final downloader = await ref.read(modelDownloaderProvider.future);
    for (final item in state.items) {
      downloader.cancel(item.spec.id);
    }
  }

  Future<void> cancelDownload(String modelId) async {
    final downloader = await ref.read(modelDownloaderProvider.future);
    downloader.cancel(modelId);
  }

  Future<void> delete(String modelId) async {
    final spec = ModelCatalog.byId(modelId);
    final store = await ref.read(modelStoreProvider.future);
    await store.delete(spec);
    final db = await ref.read(appDatabaseProvider.future);
    if (await db.getSetting(kAsrModelSettingKey) == modelId) {
      await db.setSetting(kAsrModelSettingKey, '');
    }
    await _load();
  }

  Future<void> select(String modelId) async {
    final spec = ModelCatalog.byId(modelId);
    final db = await ref.read(appDatabaseProvider.future);
    final key = switch (spec.kind) {
      ModelKind.asr => kAsrModelSettingKey,
      ModelKind.vad ||
      ModelKind.denoiser ||
      ModelKind.speakerEmbedding ||
      ModelKind.speakerSegmentation => null,
    };
    if (key != null) {
      await db.setSetting(key, modelId);
      await _load();
    }
  }

  Future<void> refresh() => _load();
}

final modelsControllerProvider =
    NotifierProvider<ModelsController, ModelsState>(ModelsController.new);
