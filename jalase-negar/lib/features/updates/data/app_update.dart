/// The only origin the app ever asks for updates and downloads them from.
const kUpdateOrigin = 'https://api.sedasanj.ir';

/// Absolute path prefix every download link must start with.
const kUpdateDownloadPrefix = '/v1/jalase-negar/android/releases/';

/// What the installed app tells the server so it can pick a compatible build.
class UpdateEnvironment {
  const UpdateEnvironment({
    required this.versionName,
    required this.versionCode,
    required this.sdkInt,
    required this.abis,
    required this.certSha256,
    this.installId = '',
  });

  final String versionName;
  final int versionCode;
  final int sdkInt;
  final List<String> abis;

  /// SHA-256 of the public signing certificate of the installed app (lowercase hex).
  final String certSha256;

  /// Anonymous random id of this installation (never tied to a person). The
  /// server hashes it into a stable rollout bucket.
  final String installId;

  Map<String, String> toQuery() => {
    'version_code': '$versionCode',
    'sdk_int': '$sdkInt',
    'abis': abis.join(','),
    'cert_sha256': certSha256,
    if (installId.isNotEmpty) 'install_id': installId,
  };
}

/// A newer, compatible build the server offers.
class AppUpdateOffer {
  const AppUpdateOffer({
    required this.id,
    required this.version,
    required this.versionCode,
    required this.title,
    required this.notes,
    required this.size,
    required this.downloadUri,
    this.sha256 = '',
    this.minSdk = 0,
    this.mandatory = false,
  });

  final String id;
  final String version;
  final int versionCode;
  final String title;

  /// Plain text release notes; never rendered as markup.
  final String notes;
  final int size;
  final Uri downloadUri;

  /// Lowercase hex SHA-256 of the APK as the server computed it; empty when
  /// the server did not send a valid one (then no automatic install happens).
  final String sha256;
  final int minSdk;

  /// The installed build is below the release's minimum supported build.
  final bool mandatory;

  /// Only an offer with a checksum may be downloaded and installed by the app.
  bool get canAutoInstall => sha256.isNotEmpty && size > 0;

  /// Reads one offer from the update response. Returns null when the response
  /// has no update; throws [FormatException] for a malformed or foreign link.
  static AppUpdateOffer? fromResponse(Object? body) {
    if (body is! Map || !body.containsKey('update')) {
      throw const FormatException('update response has no "update" field');
    }
    final raw = body['update'];
    if (raw == null) return null;
    if (raw is! Map) throw const FormatException('update is not an object');
    final id = raw['id'];
    final version = raw['version'];
    final code = raw['version_code'];
    final path = raw['download_path'];
    if (id is! String ||
        version is! String ||
        code is! int ||
        path is! String ||
        id.isEmpty ||
        version.isEmpty) {
      throw const FormatException('update offer is incomplete');
    }
    return AppUpdateOffer(
      id: id,
      version: version,
      versionCode: code,
      title: raw['title'] is String ? raw['title'] as String : '',
      notes: raw['notes'] is String ? (raw['notes'] as String).trim() : '',
      size: raw['size'] is int ? raw['size'] as int : 0,
      downloadUri: resolveDownloadUri(path),
      sha256: _parseSha256(raw['sha256']),
      minSdk: raw['min_sdk'] is int ? raw['min_sdk'] as int : 0,
      mandatory: raw['mandatory'] == true,
    );
  }
}

final _sha256Pattern = RegExp(r'^[0-9a-f]{64}$');

String _parseSha256(Object? value) {
  if (value is! String) return '';
  final lower = value.trim().toLowerCase();
  return _sha256Pattern.hasMatch(lower) ? lower : '';
}

/// Resolves a relative download path against the fixed origin. Anything that
/// points elsewhere (another host, scheme tricks, path escapes) is rejected so
/// a tampered response can never send the user to a foreign download.
Uri resolveDownloadUri(String path) {
  final uri = Uri.tryParse(path);
  if (uri == null ||
      uri.hasScheme ||
      uri.hasAuthority ||
      uri.hasQuery ||
      uri.hasFragment ||
      !path.startsWith(kUpdateDownloadPrefix) ||
      path.contains('..') ||
      path.contains('\\')) {
    throw const FormatException('download path is not allowed');
  }
  return Uri.parse('$kUpdateOrigin$path');
}
