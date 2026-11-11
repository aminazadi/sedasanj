import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:jalase_negar/core/platform/secure_storage.dart';

/// Encrypts voiceprints before they are written to the local database, so a
/// copy of the database file alone does not reveal biometric data.
abstract interface class EmbeddingCipher {
  Future<Uint8List> encrypt(Uint8List plain);
  Future<Uint8List> decrypt(Uint8List sealed);
}

/// AES-256-GCM. Stored form: 12-byte nonce, ciphertext, 16-byte tag.
class AesGcmEmbeddingCipher implements EmbeddingCipher {
  AesGcmEmbeddingCipher(this._keyBytes);

  final List<int> _keyBytes;
  final _algorithm = AesGcm.with256bits();

  /// A random key, for tests.
  factory AesGcmEmbeddingCipher.random() {
    final random = Random.secure();
    return AesGcmEmbeddingCipher([
      for (var i = 0; i < 32; i++) random.nextInt(256),
    ]);
  }

  @override
  Future<Uint8List> encrypt(Uint8List plain) async {
    final box = await _algorithm.encrypt(
      plain,
      secretKey: SecretKey(_keyBytes),
    );
    return Uint8List.fromList(box.concatenation());
  }

  @override
  Future<Uint8List> decrypt(Uint8List sealed) async {
    final box = SecretBox.fromConcatenation(
      sealed,
      nonceLength: 12,
      macLength: 16,
    );
    return Uint8List.fromList(
      await _algorithm.decrypt(box, secretKey: SecretKey(_keyBytes)),
    );
  }
}

const _kVoiceKey = 'voiceprint_local_key';

/// Loads the device key from the platform secure storage (Keystore /
/// Keychain), creating it on first use. The key never leaves the device.
Future<EmbeddingCipher> loadDeviceEmbeddingCipher({
  FlutterSecureStorage? storage,
}) async {
  final secure = storage ?? appSecureStorage;
  final stored = await secure.read(key: _kVoiceKey);
  if (stored != null && stored.length == 64) {
    return AesGcmEmbeddingCipher([
      for (var i = 0; i < 64; i += 2)
        int.parse(stored.substring(i, i + 2), radix: 16),
    ]);
  }
  final random = Random.secure();
  final key = [for (var i = 0; i < 32; i++) random.nextInt(256)];
  await secure.write(
    key: _kVoiceKey,
    value: key.map((b) => b.toRadixString(16).padLeft(2, '0')).join(),
  );
  return AesGcmEmbeddingCipher(key);
}
