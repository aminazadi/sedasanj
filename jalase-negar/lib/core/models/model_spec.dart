/// What a model is used for in the pipeline.
enum ModelKind {
  asr,
  vad,
  denoiser,

  /// Turns a voice into an embedding (who is speaking).
  speakerEmbedding,

  /// Finds speaker changes and overlapping speech.
  speakerSegmentation,

  /// Names non-speech human sounds (laughter, crying, cough, ...) so the
  /// transcript can write them between square brackets.
  soundEvents,
}

enum AsrArchitecture { nemoCtc, transducer }

/// One downloadable file of a model bundle.
class ModelFileSpec {
  const ModelFileSpec({
    required this.url,
    required this.filename,
    required this.sizeBytes,
    this.sizeIsEstimate = false,
    this.sha256,
  });

  final String url;
  final String filename;
  final int sizeBytes;

  /// Lowercase hex SHA-256 of the file, copied from the files the benchmark
  /// used (`docs/asr-benchmark.md`). Recorded only: the downloader does not
  /// check it yet, and the copy hosted on sedasanj.ir has not been compared
  /// with it. ⚠ needs lab confirmation before any check is enforced.
  final String? sha256;

  /// Some upstream release pages do not expose stable byte sizes. Such files
  /// are validated by successful download rather than an invented exact size.
  final bool sizeIsEstimate;
}

/// A downloadable model bundle, referenced by a stable [id].
///
/// Model files are served by SedaSanj; repository links retain attribution.
class ModelSpec {
  const ModelSpec({
    required this.id,
    required this.kind,
    required this.nameFa,
    required this.descriptionFa,
    required this.repoUrl,
    required this.files,
    this.recommended = false,
    this.asrArchitecture = AsrArchitecture.nemoCtc,
    this.license,
  });

  final String id;
  final ModelKind kind;
  final String nameFa;
  final String descriptionFa;
  final String repoUrl;
  final List<ModelFileSpec> files;
  final bool recommended;
  final AsrArchitecture asrArchitecture;

  /// SPDX id of the licence, only where the catalog already states it. Null
  /// means "not confirmed", not "unlicensed".
  final String? license;

  int get totalSizeBytes => files.fold(0, (sum, f) => sum + f.sizeBytes);
}
