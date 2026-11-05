import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';

/// Vector helpers for speaker embeddings (plain Dart so they run in any
/// isolate and are unit-tested without native code).

double dot(Float32List a, Float32List b) {
  final n = math.min(a.length, b.length);
  var sum = 0.0;
  for (var i = 0; i < n; i++) {
    sum += a[i] * b[i];
  }
  return sum;
}

double norm(Float32List a) => math.sqrt(dot(a, a));

/// A unit-length copy; an all-zero vector stays zero.
Float32List normalized(Float32List a) {
  final n = norm(a);
  final out = Float32List(a.length);
  if (n == 0) return out;
  for (var i = 0; i < a.length; i++) {
    out[i] = a[i] / n;
  }
  return out;
}

/// Cosine similarity in [-1, 1]; 0 when either vector is empty, all zeros or
/// the lengths differ (embeddings of different models are not comparable).
double cosine(Float32List a, Float32List b) {
  if (a.isEmpty || a.length != b.length) return 0;
  final na = norm(a);
  final nb = norm(b);
  if (na == 0 || nb == 0) return 0;
  return dot(a, b) / (na * nb);
}

/// Mean of the unit-length [vectors], renormalised. Empty input gives an
/// empty vector; vectors of another length than the first are ignored.
Float32List centroid(Iterable<Float32List> vectors) {
  Float32List? sum;
  var count = 0;
  for (final v in vectors) {
    if (v.isEmpty) continue;
    sum ??= Float32List(v.length);
    if (v.length != sum.length) continue;
    final unit = normalized(v);
    for (var i = 0; i < unit.length; i++) {
      sum[i] += unit[i];
    }
    count++;
  }
  if (sum == null || count == 0) return Float32List(0);
  return normalized(sum);
}

/// Little-endian float32 bytes, the wire and storage format of an embedding.
Uint8List embeddingToBytes(Float32List embedding) {
  final bytes = ByteData(embedding.length * 4);
  for (var i = 0; i < embedding.length; i++) {
    bytes.setFloat32(i * 4, embedding[i], Endian.little);
  }
  return bytes.buffer.asUint8List();
}

Float32List embeddingFromBytes(Uint8List bytes) {
  final count = bytes.length ~/ 4;
  final view = ByteData.sublistView(bytes);
  final out = Float32List(count);
  for (var i = 0; i < count; i++) {
    out[i] = view.getFloat32(i * 4, Endian.little);
  }
  return out;
}

String embeddingToBase64(Float32List embedding) =>
    base64Encode(embeddingToBytes(embedding));

Float32List embeddingFromBase64(String encoded) =>
    embeddingFromBytes(base64Decode(encoded));
