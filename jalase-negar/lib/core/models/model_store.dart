import 'dart:io';

import '../io/app_paths.dart';
import 'model_spec.dart';

/// Filesystem layout and installed-state checks for model bundles.
///
/// A bundle is complete only when every file exists with its expected size
/// and the `.complete` marker is present, so an interrupted download can
/// never be mistaken for an installed model.
class ModelStore {
  ModelStore(this._paths);

  final AppPaths _paths;

  Directory dirFor(ModelSpec spec) => _paths.modelDir(spec.id);

  String filePath(ModelSpec spec, ModelFileSpec file) =>
      '${dirFor(spec).path}/${file.filename}';

  String partPath(ModelSpec spec, ModelFileSpec file) =>
      '${filePath(spec, file)}.part';

  File markerFile(ModelSpec spec) => File('${dirFor(spec).path}/.complete');

  Future<bool> isInstalled(ModelSpec spec) async {
    if (!await markerFile(spec).exists()) return false;
    for (final file in spec.files) {
      final f = File(filePath(spec, file));
      if (!await f.exists() ||
          (!file.sizeIsEstimate && await f.length() != file.sizeBytes)) {
        return false;
      }
    }
    return true;
  }

  Future<void> markInstalled(ModelSpec spec) async {
    await markerFile(spec).writeAsString(DateTime.now().toIso8601String());
  }

  Future<void> delete(ModelSpec spec) async {
    final dir = dirFor(spec);
    if (await dir.exists()) await dir.delete(recursive: true);
  }

  /// Removes the folder of a model that is no longer in the catalog.
  Future<void> deleteById(String id) async {
    final dir = _paths.modelDir(id);
    if (await dir.exists()) await dir.delete(recursive: true);
  }

  /// Bytes already on disk (completed files + partial downloads).
  Future<int> bytesOnDisk(ModelSpec spec) async {
    var total = 0;
    for (final file in spec.files) {
      final full = File(filePath(spec, file));
      if (await full.exists()) {
        total += await full.length();
        continue;
      }
      final part = File(partPath(spec, file));
      if (await part.exists()) total += await part.length();
    }
    return total;
  }
}
